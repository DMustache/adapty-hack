"""Usage events: loader (Amplitude / Firebase / CSV), subscriber matching, point-in-time usage features."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.usage.features import USAGE_FEATURES, usage_features
from ml.usage.loader import detect_format, insert_events, load_exports, match

FIX = Path(__file__).resolve().parent / "fixtures" / "usage"
AS_OF = pd.Timestamp("2026-10-10T12:00:00Z")
SUBSCRIBERS = {"lumen_261329_00001": "u00001", "lumen_261329_00002": "u00002", "lumen_261329_00003": "u00003"}


def _snaps(*users, as_of=AS_OF):
    return pd.DataFrame({"user_id": list(users), "as_of_at": [as_of] * len(users)})


# ---------------------------------------------------------------- loader
def test_formats_are_detected():
    assert detect_format(FIX / "amplitude.jsonl") == "amplitude"
    assert detect_format(FIX / "firebase.jsonl") == "firebase"
    assert detect_format(FIX / "events.csv") == "csv"


def test_load_drops_invalid_rows_and_normalises_to_utc():
    ev, stats = load_exports([FIX / "amplitude.jsonl", FIX / "firebase.jsonl", FIX / "events.csv"])
    assert stats == {"rows_read": 13, "rows_dropped_invalid": 2, "rows_kept": 11}   # 2 rows without user_id
    assert str(ev["occurred_at"].dt.tz) == "UTC"
    naive_csv = ev[(ev.source == "csv") & (ev.user_id == "lumen_261329_00001")].iloc[0]
    assert naive_csv.occurred_at == pd.Timestamp("2026-10-08T10:00:00Z")            # naive time read as UTC
    fb = ev[ev.source == "firebase"].sort_values("occurred_at")
    assert fb.occurred_at.iloc[0] == pd.Timestamp("2026-10-10T11:00:00Z")           # microseconds since epoch


def test_reloading_the_same_export_does_not_duplicate():
    _ev, stats = load_exports([FIX / "amplitude.jsonl", FIX / "amplitude.jsonl"])
    assert stats["rows_read"] == 16 and stats["rows_kept"] == 7


def test_match_report():
    ev, _ = load_exports([FIX / "amplitude.jsonl", FIX / "firebase.jsonl", FIX / "events.csv"])
    matched, report = match(ev, SUBSCRIBERS)
    assert report["event_users"] == 3 and report["matched_users"] == 2 and report["unmatched_users"] == 1
    assert report["unmatched_examples"] == ["someone_else"] and report["unmatched_events"] == 1
    assert report["subscribers_known"] == 3 and report["subscribers_with_events"] == 2
    assert set(matched["subscriber_id"]) == {"u00001", "u00002"}


def test_insert_is_idempotent_sql():
    class FakeConn:
        def __init__(self):
            self.sql, self.rows, self.committed = [], [], False

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, row):
            self.sql.append(" ".join(sql.split()))
            self.rows.append(row)
            self.rowcount = 1

        def commit(self):
            self.committed = True

    ev, _ = load_exports([FIX / "firebase.jsonl"])
    conn = FakeConn()
    assert insert_events(conn, ev) == 2 and conn.committed
    assert "ON CONFLICT ON CONSTRAINT usage_events_dedup DO NOTHING" in conn.sql[0]
    assert conn.rows[0][0] == "lumen_261329_00002" and conn.rows[0][3] == "firebase"


# ---------------------------------------------------------------- point-in-time features
def _matched(*files):
    ev, _ = load_exports([FIX / f for f in files])
    return match(ev, SUBSCRIBERS)[0]


def test_features_from_amplitude_fixture():
    f = usage_features(_snaps("u00001"), _matched("amplitude.jsonl")).iloc[0]
    # sessions strictly before 10 Oct 12:00: 9 Oct, 5 Oct (last 7d); 1 Oct (previous 7d); 5 Sep is > 30 days back
    assert f.sessions_7d == 2 and f.sessions_30d == 3 and f.days_since_last_session == 1.0
    assert f.sessions_trend_7d_delta == 1 and f.sessions_trend_7d_ratio == pytest.approx(1.5)


def test_all_sources_combined():
    f = usage_features(_snaps("u00001", "u00002"), _matched("amplitude.jsonl", "firebase.jsonl", "events.csv"))
    a, b = f.iloc[0], f.iloc[1]
    assert a.sessions_7d == 3 and a.sessions_30d == 4                      # + the CSV app_open on 8 Oct
    assert a.sessions_trend_7d_delta == 2 and a.sessions_trend_7d_ratio == pytest.approx(2.0)
    assert b.sessions_7d == 1 and b.days_since_last_session == pytest.approx(1 / 24)   # 1 hour before


def test_later_events_and_event_at_as_of_are_ignored():
    ev = _matched("amplitude.jsonl")
    base = usage_features(_snaps("u00001"), ev)
    later = pd.DataFrame({"user_id": "lumen_261329_00001", "subscriber_id": "u00001", "event_name": "session_start",
                          "occurred_at": AS_OF + pd.to_timedelta(np.arange(0, 50), unit="h"),   # incl. exactly as_of
                          "source": "csv", "source_event_id": None})
    pd.testing.assert_frame_equal(usage_features(_snaps("u00001"), pd.concat([ev, later], ignore_index=True)), base)


def test_earlier_snapshot_sees_fewer_events():
    ev = _matched("amplitude.jsonl")
    early = usage_features(_snaps("u00001", as_of=pd.Timestamp("2026-10-06T00:00:00Z")), ev).iloc[0]
    assert early.sessions_7d == 2 and early.days_since_last_session == pytest.approx(0.5)   # 5 Oct 12:00, 1 Oct


def test_non_session_events_are_not_sessions():
    ev = _matched("amplitude.jsonl")
    only_edits = ev[ev.event_name == "photo_edited"]
    f = usage_features(_snaps("u00001"), only_edits).iloc[0]
    assert f.sessions_7d == 0 and np.isnan(f.days_since_last_session)      # tracked, but no sessions


def test_untracked_subscriber_gets_nulls_not_zeros():
    f = usage_features(_snaps("u00001", "u00003"), _matched("amplitude.jsonl"))
    assert f.loc[1, USAGE_FEATURES].isna().all()
    assert f.loc[0, "sessions_7d"] == 2


def test_schema_file():
    sql = (Path(__file__).resolve().parents[1] / "postgres" / "init" / "007-usage-events.sql").read_text()
    for col in ("user_id TEXT NOT NULL", "event_name TEXT NOT NULL", "occurred_at TIMESTAMPTZ NOT NULL"):
        assert col in sql
    assert "UNIQUE (user_id, event_name, occurred_at, source)" in sql and "usage_events_user_time_idx" in sql


def test_new_engagement_features():
    f = usage_features(_snaps("u00001"), _matched("amplitude.jsonl")).iloc[0]
    # sessions 9 Oct, 5 Oct, 1 Oct within 14 days; 3 within 30 days
    assert f.sessions_14d == 3
    assert f.session_rate_7d_vs_30d == pytest.approx((2 + 1) / (3 * 7 / 30 + 1))
    ev = _matched("amplitude.jsonl")
    last_any = ev.loc[(ev.subscriber_id == "u00001") & (ev.occurred_at < AS_OF), "occurred_at"].max()
    assert f.days_since_last_activity == pytest.approx((AS_OF - last_any) / pd.Timedelta(days=1))
    assert f.days_since_last_activity <= f.days_since_last_session


def test_tracking_status_is_point_in_time():
    """A subscriber whose first event comes AFTER as_of_at is still untracked at as_of_at (nulls, not zeros)."""
    future = pd.DataFrame({"subscriber_id": ["u00009"], "event_name": ["session_start"],
                           "occurred_at": [AS_OF + pd.Timedelta(days=2)]})
    f = usage_features(_snaps("u00009"), future).iloc[0]
    assert f[USAGE_FEATURES].isna().all()


def test_tracked_since_gives_zeros_for_a_tracked_but_inactive_subscriber():
    empty = pd.DataFrame(columns=["subscriber_id", "event_name", "occurred_at"])
    f = usage_features(_snaps("u00009"), empty, tracked_since={"u00009": AS_OF - pd.Timedelta(days=40)}).iloc[0]
    assert f.sessions_7d == 0 and f.sessions_30d == 0 and np.isnan(f.days_since_last_activity)
    later = usage_features(_snaps("u00009"), empty, tracked_since={"u00009": AS_OF + pd.Timedelta(days=1)}).iloc[0]
    assert later[USAGE_FEATURES].isna().all()                            # tracking had not started yet
