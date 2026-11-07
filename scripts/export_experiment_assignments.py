#!/usr/bin/env python3
"""Export *proposed* experiment arms to CSV; NO live Adapty write calls.

Usage: python scripts/export_experiment_assignments.py plan.json output.csv
"""
import csv
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.contracts.models import RetentionPlanResult


def export_plan(source: Path, destination: Path) -> int:
    plan = RetentionPlanResult.model_validate(json.loads(source.read_text(encoding="utf-8")))
    columns = ["app_id", "experiment_id", "user_id", "plan_type", "arm",
               "discount_fraction", "max_discount_exposure_usd"]
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for assignment in plan.assignments:
            row = assignment.model_dump()
            writer.writerow({key: plan.app_id if key == "app_id" else
                             plan.experiment_id if key == "experiment_id" else row.get(key)
                             for key in columns})
    return len(plan.assignments)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python scripts/export_experiment_assignments.py <plan.json> <output.csv>")
    count = export_plan(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Exported {count} proposed arm assignments (not activated in Adapty).")
