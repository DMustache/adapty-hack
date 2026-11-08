"""Contract checks for the synthetic offline dashboard wave."""

import csv
import gzip
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def importer(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", types.ModuleType("psycopg"))
    path = ROOT / "services/analytics/import_offline.py"
    spec = importlib.util.spec_from_file_location("offline_import", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_snapshot(path, module, *, duplicate=False, missing=False):
    users = []
    for uid in ("u1", "u1" if duplicate else "u2"):
        row = {column: "sample" for column in module.USER_COLUMNS}
        row.update(user_id=uid, install_at="2026-07-01T00:00:00Z",
                   ai_edits_first_day="1.0", photos_imported="2.0")
        users.append(row)
    transactions = [{column: "sample" for column in module.TRANSACTION_COLUMNS}]
    transactions[0].update(user_id="unknown" if missing else "u1", seq="1",
                           purchased_at="2026-07-02T00:00:00Z", expires_at="",
                           originally_purchased_at="", price_local="2.00", price_usd="2.00",
                           renew_status_changed_at="", billing_issue_detected_at="",
                           refunded_at="")
    for name, columns, rows in (
        ("users.csv.gz", module.USER_COLUMNS, users),
        ("transactions.csv.gz", module.TRANSACTION_COLUMNS, transactions),
    ):
        with gzip.open(path / name, "wt", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)


def test_offline_loader_validates_join_and_snapshot(monkeypatch, tmp_path):
    module = importer(monkeypatch)
    write_snapshot(tmp_path, module)
    users, transactions, hashes = module.load_snapshot(tmp_path)
    assert len(users) == 2 and len(transactions) == 1
    assert len(hashes["users.csv.gz"]) == 64
    assert users[0][6].tzinfo is not None

    write_snapshot(tmp_path, module, duplicate=True)
    with pytest.raises(ValueError, match="duplicate user_id"):
        module.load_snapshot(tmp_path)
    write_snapshot(tmp_path, module, missing=True)
    with pytest.raises(ValueError, match="missing user"):
        module.load_snapshot(tmp_path)


def test_four_dashboards_are_read_only_and_source_honest():
    offline_uids = {"model-health", "business-revenue", "behavior-segments", "smart-retention"}
    files = [path for path in (ROOT / "grafana/dashboards").glob("*.json")
             if json.loads(path.read_text())["uid"] in offline_uids]
    dashboards = [json.loads(path.read_text()) for path in files]
    assert {dashboard["uid"] for dashboard in dashboards} == offline_uids
    for dashboard in dashboards:
        assert dashboard["timezone"] == "utc"
        assert "Offline" in dashboard["title"]
        assert dashboard["templating"]["list"]
        for panel in dashboard["panels"]:
            assert panel["datasource"]["uid"] == "adapty-pg"
            for target in panel["targets"]:
                sql = target["rawSql"].strip().upper()
                assert sql.startswith("SELECT ")
                assert not any(word in sql for word in ("INSERT INTO", "UPDATE ", "DELETE FROM"))
                assert "USER_ID AS" not in sql
    model_dashboard = next(dashboard for dashboard in dashboards if dashboard["uid"] == "model-health")
    model_panel = next(panel for panel in model_dashboard["panels"] if panel["title"] == "Stored prediction sources")
    assert "churn_predictions" in model_panel["targets"][0]["rawSql"]
    assert "No external churn model loaded" not in files_content(files)
    assert "Need verified variant assignment" in files_content(files)


def test_model_inventory_shows_mock_external_and_empty_external_state():
    import sqlite3

    dashboard = json.loads((ROOT / "grafana/dashboards/model-health.json").read_text())
    panel = next(panel for panel in dashboard["panels"] if panel["title"] == "Stored prediction sources")
    sql = panel["targets"][0]["rawSql"]
    assert "service is running" in panel["description"]
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE churn_predictions (prediction_source TEXT, model_id TEXT, model_version TEXT)")
        assert db.execute(sql).fetchall() == [("external", "No external predictions stored", None, 0)]
        db.execute("INSERT INTO churn_predictions VALUES ('mock', 'mock-churn-v1', '0.0.0-mock')")
        assert db.execute(sql).fetchall() == [
            ("external", "No external predictions stored", None, 0),
            ("mock", "mock-churn-v1", "0.0.0-mock", 1),
        ]
        db.executemany("INSERT INTO churn_predictions VALUES (?, ?, ?)", [
            ("mock", "mock-churn-v1", "0.0.0-mock"),
            ("external", "lumen-temporal-catboost", "1.0.0"),
        ])
        assert db.execute(sql).fetchall() == [
            ("external", "lumen-temporal-catboost", "1.0.0", 1),
            ("mock", "mock-churn-v1", "0.0.0-mock", 2),
        ]


def files_content(files):
    return "\n".join(path.read_text() for path in files)
