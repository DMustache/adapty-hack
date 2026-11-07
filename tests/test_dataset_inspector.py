import csv
import gzip

import pytest

from scripts.inspect_seed_data import report


def write_gzip_csv(path, rows, columns):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_inspector_reports_synthetic_single_app_shape_without_labels(tmp_path):
    write_gzip_csv(
        tmp_path / "users.csv.gz",
        [{"user_id": "u1", "install_at": "2026-01-01"},
         {"user_id": "u2", "install_at": "2026-01-02"}],
        ["user_id", "install_at"],
    )
    write_gzip_csv(
        tmp_path / "transactions.csv.gz",
        [{"user_id": "u1", "purchased_at": "2026-02-01", "renew_status": "cancelled"}],
        ["user_id", "purchased_at", "renew_status"],
    )

    result = report(tmp_path)

    assert result["dataset_type"] == "synthetic"
    assert result["source"] == "kpotehin/adapty-seed-data-hack"
    assert result["files"]["users.csv.gz"] == {
        "rows": 2, "columns": ["user_id", "install_at"], "missing_user_ids": 0,
    }
    assert result["files"]["transactions.csv.gz"]["rows"] == 1
    assert "no observed response to discounts" in result["caution"].lower()
    assert "past-only features" in result["caution"].lower()
    assert not any("label" in key or "churn" in key for key in result)

    # Future transaction outcomes cannot affect this shape-only inspection.
    write_gzip_csv(
        tmp_path / "transactions.csv.gz",
        [{"user_id": "u1", "purchased_at": "2026-02-01", "renew_status": "renewed"}],
        ["user_id", "purchased_at", "renew_status"],
    )
    assert report(tmp_path) == result


def test_inspector_rejects_missing_or_unusable_users_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="users.csv.gz"):
        report(tmp_path)

    write_gzip_csv(tmp_path / "users.csv.gz", [{"country": "US"}], ["country"])
    with pytest.raises(ValueError, match="missing required user_id"):
        report(tmp_path)

    write_gzip_csv(tmp_path / "users.csv.gz", [{"user_id": ""}], ["user_id"])
    write_gzip_csv(tmp_path / "transactions.csv.gz", [], ["user_id"])
    with pytest.raises(ValueError, match="users dataset is empty"):
        report(tmp_path)
