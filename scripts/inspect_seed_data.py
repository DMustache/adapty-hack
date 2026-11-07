#!/usr/bin/env python3
"""Validate *shape* of hackathon data. Does NOT derive churn labels or train a model.

Usage: python scripts/inspect_seed_data.py path/to/data/offline
"""
import csv
import gzip
import json
import sys
from pathlib import Path


def report(directory: Path) -> dict:
    output = {"dataset_type": "synthetic", "source": "kpotehin/adapty-seed-data-hack", "files": {}}
    user_ids = set()
    for name in ("users.csv.gz", "transactions.csv.gz"):
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing offline dataset: {path}")
        with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            cols = reader.fieldnames or []
            if "user_id" not in cols:
                raise ValueError(f"{name}: missing required user_id column")
            count = 0
            missing = 0
            for row in reader:
                count += 1
                uid = row.get("user_id", "")
                if not uid:
                    missing += 1
                if name == "users.csv.gz" and uid:
                    user_ids.add(uid)
            output["files"][name] = {"rows": count, "columns": cols, "missing_user_ids": missing}
    if not user_ids:
        raise ValueError("users dataset is empty")
    # Intentionally DO NOT join transactions into features or define churn labels here.
    output["caution"] = (
        "Synthetic single-app data; no observed response to discounts. "
        "Use past-only features and researcher-defined renewal/churn labels with time split."
    )
    return output


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/inspect_seed_data.py <offline-data-dir>")
    print(json.dumps(report(Path(sys.argv[1])), indent=2))
