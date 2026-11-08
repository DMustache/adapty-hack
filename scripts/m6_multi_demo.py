"""Three local experiment examples using the fixed model and simulated events only.

The model predicts next-renewal risk; it neither creates tests nor predicts their outcomes.
No Adapty API calls, churn-model updates, or treatment-effect estimates occur here.
"""

import argparse
import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from export_m5_audit import export as audit_export

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "services/inference/models/temporal_catboost/model.cbm"
PINNED_SHA = "4f3fd0acc9944b19fd0743d3c0b8a8863b8d59e1e81065c5a0940d5b9fad1491"
INF = "http://127.0.0.1:8001"
ANA = "http://127.0.0.1:8002"
SCENARIOS = (
    ("A", 0.10, (0, 1), (0, 1)),  # complete lineage for two subscribers
    ("B", 0.20, (0, 1), (0,)),    # one exposed subscriber has a pending outcome
    ("C", 0.30, (0,), (0,)),      # two assigned subscribers have no exposure
)
DASHBOARDS = ("model-health", "business-revenue", "behavior-segments",
              "smart-retention", "churn-risk-trajectory")


def request(method, url, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def utc(value):
    return datetime.fromisoformat(value)


def iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sha():
    return hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()


def grafana_config(name, default):
    if name in os.environ:
        return os.environ[name]
    for path in (Path.cwd() / ".env", ROOT / ".env", ROOT.parent / "develop" / ".env"):
        if path.exists():
            for line in path.read_text().splitlines():
                key, sep, value = line.strip().partition("=")
                if sep and key == name:
                    return value.strip().strip('"').strip("'")
    return default


def check_dashboards():
    user = grafana_config("GF_SECURITY_ADMIN_USER", "admin")
    password = grafana_config("GF_SECURITY_ADMIN_PASSWORD", "admin_demo")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    for uid in DASHBOARDS:
        req = urllib.request.Request("http://127.0.0.1:3000/api/dashboards/uid/" + uid,
                                     headers={"Authorization": "Basic " + token})
        with urllib.request.urlopen(req, timeout=10) as response:
            dashboard = json.load(response)["dashboard"]
        assert dashboard["uid"] == uid
    return list(DASHBOARDS)


def send_event(kind, record, check_conflict=False):
    url = ANA + "/v1/ingest/lineage/" + kind
    assert request("POST", url, record)["status"] == "stored"
    assert request("POST", url, record)["status"] == "duplicate"
    if check_conflict:
        changed = {**record, "source_event_id": record["source_event_id"] + "-conflict"}
        try:
            request("POST", url, changed)
        except urllib.error.HTTPError as exc:
            assert exc.code == 409, f"expected conflict, got HTTP {exc.code}"
        else:
            raise AssertionError("conflicting idempotency key was accepted")


def run_scenario(run_id, label, discount, exposed_indices, outcome_indices, fixture, examples):
    experiment_id = f"m6-simulated-{run_id}-{label.lower()}"
    predictions = []
    for index, case in enumerate(fixture["cases"][:3]):
        user_id = f"synthetic-pseudonym-{run_id}-{label.lower()}-{index}"
        prediction = request("POST", INF + "/v1/predict", {
            "request_id": f"{experiment_id}-prediction-{index}", "app_id": "lumen-demo",
            "user_id": user_id, "model_id": fixture["model_id"],
            "renewal_horizon_days": 7,
            "context": {"as_of_at": case["as_of_at"], "renewal_due_at": case["renewal_due_at"],
                        "feature_source_ref": "synthetic-fixed-fixture"},
            "features": case["features"],
        })
        assert (prediction["prediction_source"], prediction["model_version"]) == ("external", "1.0.0")
        predictions.append((prediction, case))

    proposal = request("POST", INF + "/v1/retention/plan", {
        "app_id": "lumen-demo", "experiment_id": experiment_id,
        "budget_usd": 20, "control_share": 0.34, "random_seed": 11,
        "discounts": [discount],
        "candidates": [{"user_id": pred["user_id"], "churn_probability": pred["churn_probability"],
                        "renewal_price_usd": case["features"]["renewal_price_usd"],
                        "plan_type": case["features"]["plan"]} for pred, case in predictions],
    })
    assert proposal["plan_source"] == "scenario_experiment"
    assert proposal["modeled_discount_uplift"] is False
    assert any(arm["arm"] == "control" for arm in proposal["assignments"])

    for index, (prediction, case) in enumerate(predictions):
        due = utc(case["renewal_due_at"])
        assignment_at = due - timedelta(minutes=30)
        common = {
            "app_id": "lumen-demo", "user_id": prediction["user_id"], "source": "simulated",
            "prediction_id": prediction["prediction_id"], "model_id": prediction["model_id"],
            "model_version": prediction["model_version"],
            "as_of_at": iso(utc(case["as_of_at"])), "renewal_due_at": iso(due),
            "experiment_id": experiment_id, "variation_id": "control" if index == 0 else "treatment",
            "assignment_id": f"{experiment_id}-assignment-{index}",
        }
        prefix = f"{experiment_id}-{index}"
        assignment = {
            **examples["actual-assignment"], **common,
            "event_at": iso(assignment_at), "ingested_at": iso(assignment_at + timedelta(seconds=1)),
            "cohort_id": experiment_id, "policy_version": f"{experiment_id}-v1",
            "randomization_source": "simulated", "idempotency_key": prefix + "-assignment-key",
            "source_event_id": prefix + "-assignment-source",
        }
        send_event("actual-assignment", assignment, check_conflict=index == 0)
        if index not in exposed_indices:
            continue
        exposure_at = assignment_at + timedelta(minutes=5)
        exposure_id = prefix + "-exposure"
        exposure = {
            **examples["actual-exposure"], **common,
            "event_at": iso(exposure_at), "ingested_at": iso(exposure_at + timedelta(seconds=1)),
            "exposure_id": exposure_id, "idempotency_key": prefix + "-exposure-key",
            "source_event_id": prefix + "-exposure-source",
        }
        send_event("actual-exposure", exposure)
        if index not in outcome_indices:
            continue
        mature_at = due + timedelta(days=1)
        outcome_at = mature_at + timedelta(minutes=1)
        renewed = index == 0 and label != "C"
        outcome = {
            **examples["next-renewal-outcome"], **common,
            "event_at": iso(outcome_at), "ingested_at": iso(outcome_at + timedelta(seconds=1)),
            "outcome_mature_at": iso(mature_at), "exposure_id": exposure_id,
            "outcome_id": prefix + "-outcome", "renewed": renewed,
            "paid_usd": case["features"]["renewal_price_usd"] if renewed else 0,
            "idempotency_key": prefix + "-outcome-key", "source_event_id": prefix + "-outcome-source",
            "evidence_ref": prefix + "-simulated-stream",
        }
        send_event("next-renewal-outcome", outcome)

    lineage = request("GET", ANA + f"/v1/lineage/{experiment_id}?app_id=lumen-demo")["events"]
    counts = {kind: sum(event["kind"] == kind for event in lineage) for kind in examples}
    assert counts == {"actual-assignment": 3, "actual-exposure": len(exposed_indices),
                      "next-renewal-outcome": len(outcome_indices)}
    assert all(event["source"] == "simulated" for event in lineage)
    audit = audit_export(experiment_id)
    assert len(audit["rows"]) == len(outcome_indices)
    assert audit["excluded"]["missing_exposure"] == 3 - len(exposed_indices)
    assert audit["excluded"]["missing_or_immature_outcome"] == len(exposed_indices) - len(outcome_indices)
    exposure_by_assignment = {e["assignment_id"]: e for e in lineage if e["kind"] == "actual-exposure"}
    outcome_by_assignment = {e["assignment_id"]: e for e in lineage if e["kind"] == "next-renewal-outcome"}
    simulated_results = []
    for assignment in (e for e in lineage if e["kind"] == "actual-assignment"):
        exposure = exposure_by_assignment.get(assignment["assignment_id"])
        outcome = outcome_by_assignment.get(assignment["assignment_id"])
        simulated_results.append({
            "user_id": assignment["user_id"], "variation_id": assignment["variation_id"],
            "assignment_event_id": assignment["source_event_id"],
            "exposure_event_id": exposure["source_event_id"] if exposure else None,
            "outcome_event_id": outcome["source_event_id"] if outcome else None,
            "state": "mature" if outcome else "outcome_pending" if exposure else "exposure_pending",
            "renewed": outcome["renewed"] if outcome else None,
            "paid_usd": outcome["paid_usd"] if outcome else None,
            "source": "simulated",
        })
    return {
        "scenario": label, "experiment_id": experiment_id, "source": "simulated",
        "discount_fraction_proposed": discount, "budget_usd_proposed": proposal["budget_usd"],
        "proposal_arms": [{"user_id": a["user_id"], "arm": a["arm"]} for a in proposal["assignments"]],
        "predictions": [{"prediction_id": p["prediction_id"], "user_id": p["user_id"],
                         "churn_probability": p["churn_probability"], "model_id": p["model_id"],
                         "model_version": p["model_version"], "prediction_source": p["prediction_source"],
                         "as_of_at": p["as_of_at"], "renewal_due_at": p["renewal_due_at"]}
                        for p, _ in predictions],
        "lineage_event_ids": [e["source_event_id"] for e in lineage],
        "lineage_counts": counts, "mature_audit_rows": len(audit["rows"]),
        "audit_excluded": audit["excluded"], "simulated_results": simulated_results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=uuid4().hex[:12])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.run_id.isalnum():
        parser.error("--run-id must be alphanumeric")
    before = sha()
    assert before == PINNED_SHA, "fixed model artifact changed"
    fixture = json.loads((ROOT / "tests/fixtures/temporal_churn_fixture.json").read_text())
    examples = {kind: json.loads((ROOT / "contracts/examples" / f"{kind}.json").read_text())
                for kind in ("actual-assignment", "actual-exposure", "next-renewal-outcome")}
    scenarios = [run_scenario(args.run_id, *spec, fixture, examples) for spec in SCENARIOS]
    assert len({scenario["experiment_id"] for scenario in scenarios}) == 3
    assert sha() == before, "churn artifact changed during demo"
    report = {
        "report_version": "1.0", "source": "simulated", "model_id": fixture["model_id"],
        "model_version": fixture["model_version"], "model_sha256_before": before,
        "model_sha256_after": sha(), "dashboards_checked": check_dashboards(), "tests": scenarios,
        "disclaimer": "Synthetic experiment mechanics only; no measured treatment effect or saved revenue.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "experiment_ids": [s["experiment_id"] for s in scenarios],
                      "lineage_counts": [s["lineage_counts"] for s in scenarios],
                      "model_sha256": before, "source": "simulated"}, sort_keys=True))


if __name__ == "__main__":
    main()
