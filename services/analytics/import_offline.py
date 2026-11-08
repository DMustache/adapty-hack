"""Explicit, atomic import of the local synthetic Lumen snapshot.

Run in the analytics container: python -m services.analytics.import_offline.
The two archives are mounted read-only at /seed-data by docker-compose.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg

USER_COLUMNS = (
    "user_id", "platform", "country", "device", "os", "locale", "install_at",
    "acquisition_channel", "onboarding_goal", "ai_edits_first_day", "photos_imported",
    "push_opt_in", "app_version", "placement", "flow", "ab_test",
)
TRANSACTION_COLUMNS = (
    "user_id", "seq", "purchase_type", "product", "store_product_id", "purchased_at",
    "expires_at", "originally_purchased_at", "price_local", "currency", "price_usd",
    "offer", "renew_status", "renew_status_changed_at", "billing_issue_detected_at",
    "refunded_at", "cancellation_reason",
)


def timestamp(value: str, field: str, required: bool = False) -> datetime | None:
    if not value:
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field} must be UTC")
    return parsed


def nonnegative_decimal(value: str, field: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {field}") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"invalid {field}")
    return result


def read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"unexpected columns in {path.name}")
        rows = list(reader)
    if not rows or any(None in row for row in rows):
        raise ValueError(f"empty or malformed {path.name}")
    return rows


def load_snapshot(directory: Path) -> tuple[list[tuple], list[tuple], dict[str, str]]:
    users_path = directory / "users.csv.gz"
    transactions_path = directory / "transactions.csv.gz"
    users_raw = read_csv(users_path, USER_COLUMNS)
    tx_raw = read_csv(transactions_path, TRANSACTION_COLUMNS)
    user_ids: set[str] = set()
    users: list[tuple] = []
    for row in users_raw:
        uid = row["user_id"]
        if not uid or uid in user_ids:
            raise ValueError("blank or duplicate user_id")
        user_ids.add(uid)
        users.append((
            uid, row["platform"], row["country"], row["device"], row["os"],
            row["locale"], timestamp(row["install_at"], "install_at", True),
            row["acquisition_channel"], row["onboarding_goal"],
            nonnegative_decimal(row["ai_edits_first_day"], "ai_edits_first_day"),
            nonnegative_decimal(row["photos_imported"], "photos_imported"),
            row["push_opt_in"], row["app_version"], row["placement"], row["flow"],
            row["ab_test"] or None,
        ))
    transactions: list[tuple] = []
    tx_keys: set[tuple[str, int]] = set()
    for row in tx_raw:
        uid = row["user_id"]
        if uid not in user_ids:
            raise ValueError("transaction references missing user")
        try:
            seq = int(row["seq"])
        except ValueError as exc:
            raise ValueError("invalid transaction seq") from exc
        key = (uid, seq)
        if key in tx_keys:
            raise ValueError("duplicate transaction user_id and seq")
        tx_keys.add(key)
        transactions.append((
            uid, seq, row["purchase_type"], row["product"], row["store_product_id"],
            timestamp(row["purchased_at"], "purchased_at", True),
            timestamp(row["expires_at"], "expires_at"),
            timestamp(row["originally_purchased_at"], "originally_purchased_at"),
            nonnegative_decimal(row["price_local"], "price_local"), row["currency"],
            nonnegative_decimal(row["price_usd"], "price_usd"), row["offer"] or None,
            row["renew_status"] or None,
            timestamp(row["renew_status_changed_at"], "renew_status_changed_at"),
            timestamp(row["billing_issue_detected_at"], "billing_issue_detected_at"),
            timestamp(row["refunded_at"], "refunded_at"), row["cancellation_reason"] or None,
        ))
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (users_path, transactions_path)
    }
    return users, transactions, hashes


SCHEMA = """
CREATE TABLE IF NOT EXISTS offline_users (
  user_id TEXT PRIMARY KEY, platform TEXT NOT NULL, country TEXT NOT NULL,
  device TEXT NOT NULL, os TEXT NOT NULL, locale TEXT NOT NULL,
  install_at TIMESTAMPTZ NOT NULL, acquisition_channel TEXT NOT NULL,
  onboarding_goal TEXT NOT NULL, ai_edits_first_day NUMERIC NOT NULL,
  photos_imported NUMERIC NOT NULL, push_opt_in TEXT NOT NULL,
  app_version TEXT NOT NULL, placement TEXT NOT NULL, flow TEXT NOT NULL,
  ab_test TEXT
);
CREATE TABLE IF NOT EXISTS offline_transactions (
  user_id TEXT NOT NULL REFERENCES offline_users(user_id), seq INTEGER NOT NULL,
  purchase_type TEXT NOT NULL, product TEXT NOT NULL, store_product_id TEXT NOT NULL,
  purchased_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ,
  originally_purchased_at TIMESTAMPTZ, price_local NUMERIC NOT NULL,
  currency TEXT NOT NULL, price_usd NUMERIC NOT NULL, offer TEXT,
  renew_status TEXT, renew_status_changed_at TIMESTAMPTZ,
  billing_issue_detected_at TIMESTAMPTZ, refunded_at TIMESTAMPTZ,
  cancellation_reason TEXT, PRIMARY KEY (user_id, seq)
);
CREATE TABLE IF NOT EXISTS offline_imports (
  source_name TEXT PRIMARY KEY, sha256 TEXT NOT NULL, row_count INTEGER NOT NULL,
  imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS offline_users_install_idx ON offline_users(install_at);
CREATE INDEX IF NOT EXISTS offline_transactions_purchased_idx ON offline_transactions(purchased_at);
GRANT SELECT ON offline_users, offline_transactions, offline_imports TO grafana_ro;
"""


def import_snapshot(directory: Path, database_url: str) -> tuple[int, int]:
    users, transactions, hashes = load_snapshot(directory)
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA)
            cursor.execute("DELETE FROM offline_transactions")
            cursor.execute("DELETE FROM offline_users")
            cursor.executemany(
                "INSERT INTO offline_users VALUES (" + ",".join(["%s"] * 16) + ")", users,
            )
            cursor.executemany(
                "INSERT INTO offline_transactions VALUES (" + ",".join(["%s"] * 17) + ")",
                transactions,
            )
            cursor.execute("DELETE FROM offline_imports")
            cursor.executemany(
                "INSERT INTO offline_imports(source_name,sha256,row_count) VALUES (%s,%s,%s)",
                [("users.csv.gz", hashes["users.csv.gz"], len(users)),
                 ("transactions.csv.gz", hashes["transactions.csv.gz"], len(transactions))],
            )
    return len(users), len(transactions)


if __name__ == "__main__":
    location = Path(os.environ.get("OFFLINE_DATA_DIR", "/seed-data"))
    counts = import_snapshot(location, os.environ["DATABASE_URL"])
    print(f"Imported synthetic Lumen snapshot: {counts[0]} users, {counts[1]} transactions")
