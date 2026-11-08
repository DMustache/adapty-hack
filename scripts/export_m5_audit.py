#!/usr/bin/env python3
"""Export only synthetic, mature M5 demo lineage with frozen fixture inputs.

This local-only export does not accept real customers or train a model. The output
file is owner-readable because it contains pseudonymous decision-time features.
"""
import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANA = "http://127.0.0.1:8002"


def get(path):
    with urllib.request.urlopen(ANA + path, timeout=10) as response:
        return json.load(response)


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def export(experiment_id):
    fixture = json.loads((ROOT / "tests/fixtures/temporal_churn_fixture.json").read_text())
    events = get("/v1/lineage/" + urllib.parse.quote(experiment_id, safe="") + "?app_id=lumen-demo")["events"]
    assignments = [e for e in events if e["kind"] == "actual-assignment"]
    exposures = {e["assignment_id"]: e for e in events if e["kind"] == "actual-exposure"}
    outcomes = {e["assignment_id"]: e for e in events if e["kind"] == "next-renewal-outcome"}
    excluded = {"missing_exposure": 0, "missing_or_immature_outcome": 0,
                "unverified_fixture_or_source": 0, "post_decision_feature": 0}
    rows = []
    for assignment in assignments:
        exposure = exposures.get(assignment["assignment_id"])
        outcome = outcomes.get(assignment["assignment_id"])
        if exposure is None:
            excluded["missing_exposure"] += 1
            continue
        if outcome is None or instant(outcome["outcome_mature_at"]) > datetime.now(timezone.utc):
            excluded["missing_or_immature_outcome"] += 1
            continue
        prediction = get("/v1/predictions/" + urllib.parse.quote(assignment["prediction_id"], safe=""))
        try:
            index = int(prediction["request_id"].rsplit("-prediction-", 1)[1])
            case = fixture["cases"][index]
        except (IndexError, ValueError):
            excluded["unverified_fixture_or_source"] += 1
            continue
        if (any(e["source"] != "simulated" for e in (assignment, exposure, outcome))
                or prediction["prediction_source"] != "external"
                or prediction["model_id"] != fixture["model_id"]
                or prediction["model_version"] != fixture["model_version"]
                or instant(case["as_of_at"]) != instant(prediction["as_of_at"])
                or instant(case["renewal_due_at"]) != instant(prediction["renewal_due_at"])
                or instant(exposure["event_at"]) < instant(assignment["event_at"])
                or instant(outcome["event_at"]) < instant(outcome["outcome_mature_at"])):
            excluded["unverified_fixture_or_source"] += 1
            continue
        # The committed synthetic fixture is the only feature source in this demo.
        # It contains the original decision snapshot, not any subsequent event values.
        rows.append({"app_id": assignment["app_id"], "user_id": assignment["user_id"],
                     "prediction_id": prediction["prediction_id"], "model_id": fixture["model_id"],
                     "model_version": fixture["model_version"], "feature_cutoff_at": prediction["as_of_at"],
                     "renewal_due_at": prediction["renewal_due_at"], "decision_features": case["features"],
                     "experiment_id": experiment_id, "variation_id": assignment["variation_id"],
                     "assignment_event_id": assignment["source_event_id"],
                     "exposure_event_id": exposure["source_event_id"],
                     "outcome_event_id": outcome["source_event_id"], "renewed": outcome["renewed"],
                     "paid_usd": outcome["paid_usd"], "source": "simulated",
                     "consent_basis": "synthetic_non_customer"})
    return {"audit_schema_version": "1.0", "source": "simulated", "experiment_id": experiment_id,
            "rows": rows, "excluded": excluded, "disclaimer": "Synthetic lineage audit only; no customer or uplift claim."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment_id = json.loads(args.demo_output.read_text())["experiment_id"]
    result = export(experiment_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    assert len(result["rows"]) == 2 and result["excluded"]["missing_exposure"] == 1
    print(f"M5 synthetic audit: {len(result['rows'])} mature rows, {sum(result['excluded'].values())} excluded")


if __name__ == "__main__":
    main()
