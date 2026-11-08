"""Load app-usage exports (Amplitude, Firebase, CSV) and match them to subscribers on customer_user_id.

    python -m ml.usage.loader EXPORT [EXPORT ...] [--format amplitude|firebase|csv] [--run-id 261329]
                              [--profiles PATH] [--database-url URL]

Supported shapes (gzipped or plain):
  * amplitude : JSON lines from Amplitude's Export API; uses user_id, event_type, event_time ("YYYY-MM-DD HH:MM:SS[.f]",
                UTC), $insert_id/uuid
  * firebase  : JSON lines of the Firebase -> BigQuery export; uses user_id, event_name, event_timestamp (microseconds
                since epoch, UTC)
  * csv       : columns user_id, event_name, occurred_at (ISO 8601; naive times are taken as UTC)
The export's user_id is the app's user id, which should equal Adapty's customer_user_id.

Read-only with respect to Adapty: subscribers come from local files (offline users.csv + seeding run id, or a cached
profiles_*.json). Writes to Postgres only when --database-url is given (idempotent: ON CONFLICT DO NOTHING).
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import pandas as pd

COLUMNS = ["user_id", "event_name", "occurred_at", "source", "source_event_id"]


def _open(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else open(path, encoding="utf-8")


def _jsonl(path: Path) -> list[dict]:
    with _open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_amplitude(path: Path) -> pd.DataFrame:
    rows = _jsonl(path)
    return pd.DataFrame({
        "user_id": [r.get("user_id") for r in rows],
        "event_name": [r.get("event_type") for r in rows],
        "occurred_at": pd.to_datetime([r.get("event_time") for r in rows], utc=True, errors="coerce", format="mixed"),
        "source": "amplitude",
        "source_event_id": [r.get("$insert_id") or r.get("uuid") for r in rows],
    })


def parse_firebase(path: Path) -> pd.DataFrame:
    rows = _jsonl(path)
    micros = pd.to_numeric(pd.Series([r.get("event_timestamp") for r in rows]), errors="coerce")
    return pd.DataFrame({
        "user_id": [r.get("user_id") for r in rows],
        "event_name": [r.get("event_name") for r in rows],
        "occurred_at": pd.to_datetime(micros, unit="us", utc=True),
        "source": "firebase",
        "source_event_id": None,
    })


def parse_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"user_id": str, "event_name": str})
    missing = {"user_id", "event_name", "occurred_at"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    return pd.DataFrame({"user_id": df["user_id"], "event_name": df["event_name"],
                         "occurred_at": pd.to_datetime(df["occurred_at"], utc=True, errors="coerce", format="mixed"),
                         "source": "csv", "source_event_id": None})


PARSERS = {"amplitude": parse_amplitude, "firebase": parse_firebase, "csv": parse_csv}


def detect_format(path: Path) -> str:
    name = str(path).lower()
    if name.endswith((".csv", ".csv.gz")):
        return "csv"
    with _open(path) as f:
        first = json.loads(next(line for line in f if line.strip()))
    if "event_type" in first and "event_time" in first:
        return "amplitude"
    if "event_name" in first and "event_timestamp" in first:
        return "firebase"
    raise ValueError(f"{path}: unknown export format")


def load_exports(paths: list[str | Path], fmt: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Parse and normalise exports. Returns (events, stats); rows without user_id, event name or time are dropped."""
    frames, raw = [], 0
    for p in map(Path, paths):
        df = PARSERS[fmt or detect_format(p)](p)
        raw += len(df)
        frames.append(df)
    ev = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    ev["user_id"] = ev["user_id"].astype("string").str.strip()
    ok = ev["user_id"].notna() & (ev["user_id"] != "") & ev["event_name"].notna() & ev["occurred_at"].notna()
    ev = ev[ok].drop_duplicates(subset=["user_id", "event_name", "occurred_at", "source"]).reset_index(drop=True)
    ev["user_id"] = ev["user_id"].astype(str)
    return ev[COLUMNS], {"rows_read": int(raw), "rows_dropped_invalid": int((~ok).sum()), "rows_kept": int(len(ev))}


# ---------------------------------------------------------------- subscribers
def subscribers_from_offline(users_csv: str | Path, run_id: str) -> dict[str, str]:
    """customer_user_id -> offline user_id, as replayed by the seeder (offline u00042 = lumen_<run>_00042)."""
    ids = pd.read_csv(users_csv, usecols=["user_id"])["user_id"]
    return {f"lumen_{run_id}_{u[1:]}": u for u in ids}


def subscribers_from_profiles(profiles_json: str | Path) -> dict[str, str]:
    """customer_user_id -> customer_user_id, from a cached Adapty profile snapshot (adapty_live.py)."""
    data = json.loads(Path(profiles_json).read_text(encoding="utf-8"))
    return {p["customer_user_id"]: p["customer_user_id"] for p in data.values() if p}


def match(events: pd.DataFrame, subscribers: dict[str, str]) -> tuple[pd.DataFrame, dict]:
    """Keep events of known subscribers and add `subscriber_id` (the id the churn snapshots use)."""
    known = events["user_id"].isin(subscribers.keys())
    users = events["user_id"].unique()
    matched_users = sorted(set(users) & subscribers.keys())
    report = {"events": int(len(events)), "event_users": int(len(users)),
              "matched_users": int(len(matched_users)), "unmatched_users": int(len(users) - len(matched_users)),
              "matched_events": int(known.sum()), "unmatched_events": int((~known).sum()),
              "subscribers_known": int(len(subscribers)),
              "subscribers_with_events": int(len(matched_users)),
              "unmatched_examples": sorted(set(users) - subscribers.keys())[:5]}
    out = events[known].copy()
    out["subscriber_id"] = out["user_id"].map(subscribers)
    return out, report


# ---------------------------------------------------------------- postgres
INSERT_SQL = """
    INSERT INTO usage_events (user_id, event_name, occurred_at, source, source_event_id)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT ON CONSTRAINT usage_events_dedup DO NOTHING
"""


def insert_events(conn, events: pd.DataFrame, batch: int = 5000) -> int:
    """Insert into usage_events; returns rows inserted (duplicates are skipped by the unique constraint)."""
    inserted = 0
    rows = [(r.user_id, r.event_name, r.occurred_at.to_pydatetime(), r.source, r.source_event_id)
            for r in events.itertuples(index=False)]
    with conn.cursor() as cur:
        for i in range(0, len(rows), batch):
            for row in rows[i:i + batch]:
                cur.execute(INSERT_SQL, row)
                inserted += cur.rowcount
    conn.commit()
    return inserted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("exports", nargs="+")
    ap.add_argument("--format", choices=sorted(PARSERS))
    ap.add_argument("--users-csv", help="offline users.csv (with --run-id) to define the subscribers")
    ap.add_argument("--run-id", default="261329")
    ap.add_argument("--profiles", help="cached Adapty profiles_*.json to define the subscribers")
    ap.add_argument("--database-url", help="insert matched events into usage_events")
    args = ap.parse_args()
    events, stats = load_exports(args.exports, args.format)
    if args.profiles:
        subs = subscribers_from_profiles(args.profiles)
    else:
        from ml.temporal_churn.snapshots import find_data_dir
        subs = subscribers_from_offline(args.users_csv or find_data_dir() / "users.csv.gz", args.run_id)
    matched, report = match(events, subs)
    print(json.dumps({**stats, **report}, indent=1))
    if args.database_url:
        import psycopg
        with psycopg.connect(args.database_url) as conn:
            print(f"inserted {insert_events(conn, matched)} new rows into usage_events")


if __name__ == "__main__":
    main()
