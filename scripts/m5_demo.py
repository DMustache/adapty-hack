#!/usr/bin/env python3
"""Local fixed-model and simulated A/B lineage demo. No Adapty writes or model update."""
import argparse
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "services/inference/models/temporal_catboost/model.cbm"
EXPECTED_SHA = "4f3fd0acc9944b19fd0743d3c0b8a8863b8d59e1e81065c5a0940d5b9fad1491"
INF = "http://127.0.0.1:8001"
ANA = "http://127.0.0.1:8002"


def request(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def digest():
    return hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=uuid4().hex)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    before = digest()
    assert before == EXPECTED_SHA, "fixed model artifact changed"
    fixture = json.loads((ROOT / "tests/fixtures/temporal_churn_fixture.json").read_text())
    experiment_id = f"m5-simulated-{args.run_id}"
    predictions = []
    for index, case in enumerate(fixture["cases"][:3]):
        user_id = f"synthetic-pseudonym-{args.run_id}-{index}"
        prediction = request("POST", INF + "/v1/predict", {
            "request_id": f"{experiment_id}-prediction-{index}", "app_id": "lumen-demo",
            "user_id": user_id, "model_id": fixture["model_id"],
            "renewal_horizon_days": 7,
            "context": {"as_of_at": case["as_of_at"], "renewal_due_at": case["renewal_due_at"],
                        "feature_source_ref": "synthetic-fixed-fixture"},
            "features": case["features"],
        })
        assert prediction["prediction_source"] == "external"
        predictions.append((prediction, case))

    proposal = request("POST", INF + "/v1/retention/plan", {
        "app_id": "lumen-demo", "experiment_id": experiment_id,
        "budget_usd": 20, "control_share": 0.5, "random_seed": 5,
        "candidates": [{"user_id": p["user_id"], "churn_probability": p["churn_probability"],
                        "renewal_price_usd": c["features"]["renewal_price_usd"],
                        "plan_type": c["features"]["plan"]} for p, c in predictions],
    })
    assert proposal["plan_source"] == "scenario_experiment" and not proposal["modeled_discount_uplift"]

    first, first_case = predictions[0]
    example_dir = ROOT / "contracts/examples"
    cohort = json.loads((example_dir / "approved-cohort.json").read_text())
    sync = json.loads((example_dir / "profile-sync.json").read_text())
    draft = json.loads((example_dir / "draft-test.json").read_text())
    for record in (cohort, sync):
        record.update(user_id=first["user_id"], prediction_id=first["prediction_id"],
                      as_of_at=first_case["as_of_at"].replace("+00:00", "Z"),
                      renewal_due_at=first_case["renewal_due_at"].replace("+00:00", "Z"),
                      cohort_id=experiment_id)
    cohort["policy_version"] = f"{experiment_id}-v1"
    sync.update(sync_status="acknowledged", attribute_value=experiment_id,
                propagation_checked_at="2026-11-08T12:02:00Z")
    draft.update(experiment_id=experiment_id, cohort_id=experiment_id,
                 policy_version=cohort["policy_version"])
    readiness = {"cohort": cohort, "profile_sync": sync, "draft": draft,
                 "placement_verified": True, "segment_verified": True,
                 "control_flow_published": True, "treatment_flow_published": True,
                 "offer_price_verified": True, "competing_live_test": False}
    draft_check = request("POST", INF + "/v1/retention/draft/check", readiness)
    assert draft_check["status"] == "ready_for_operator_review" and not draft_check["writes_to_adapty"]
    assert request("POST", INF + "/v1/retention/draft/check",
                   {**readiness, "treatment_flow_published": False})["status"] == "not_ready"

    kinds = ("actual-assignment", "actual-exposure", "next-renewal-outcome")
    examples = {kind: json.loads((ROOT / "contracts/examples" / f"{kind}.json").read_text()) for kind in kinds}
    for index, (prediction, case) in enumerate(predictions):
        common = {"app_id": "lumen-demo", "user_id": prediction["user_id"], "source": "simulated",
                  "prediction_id": prediction["prediction_id"], "model_id": prediction["model_id"],
                  "model_version": prediction["model_version"],
                  "as_of_at": case["as_of_at"].replace("+00:00", "Z"),
                  "renewal_due_at": case["renewal_due_at"].replace("+00:00", "Z"),
                  "experiment_id": experiment_id, "variation_id": "control" if index == 0 else "treatment",
                  "assignment_id": f"{experiment_id}-assignment-{index}"}
        assignment = {**examples["actual-assignment"], **common,
                      "event_at": "2026-07-14T10:00:00Z", "ingested_at": "2026-07-14T10:00:01Z",
                      "randomization_source": "simulated", "cohort_id": experiment_id,
                      "idempotency_key": f"{experiment_id}-assignment-key-{index}",
                      "source_event_id": f"{experiment_id}-assignment-source-{index}"}
        # The first fixture cutoff is July 8; later fixtures may have July 14 cutoff.
        assert request("POST", ANA + "/v1/ingest/lineage/actual-assignment", assignment)["status"] == "stored"
        assert request("POST", ANA + "/v1/ingest/lineage/actual-assignment", assignment)["status"] == "duplicate"
        if index == 2:  # a proposal and assignment are not evidence of an exposure or outcome
            continue
        exposure_id = f"{experiment_id}-exposure-{index}"
        exposure = {**examples["actual-exposure"], **common,
                    "event_at": "2026-07-14T11:00:00Z", "ingested_at": "2026-07-14T11:00:01Z",
                    "exposure_id": exposure_id, "idempotency_key": f"{experiment_id}-exposure-key-{index}",
                    "source_event_id": f"{experiment_id}-exposure-source-{index}"}
        assert request("POST", ANA + "/v1/ingest/lineage/actual-exposure", exposure)["status"] == "stored"
        outcome = {**examples["next-renewal-outcome"], **common,
                   "event_at": "2026-07-17T10:00:00Z", "ingested_at": "2026-07-17T10:00:01Z",
                   "outcome_mature_at": "2026-07-16T10:00:00Z", "exposure_id": exposure_id,
                   "outcome_id": f"{experiment_id}-outcome-{index}", "renewed": index == 0,
                   "paid_usd": case["features"]["renewal_price_usd"] if index == 0 else 0,
                   "idempotency_key": f"{experiment_id}-outcome-key-{index}",
                   "source_event_id": f"{experiment_id}-outcome-source-{index}",
                   "evidence_ref": f"{experiment_id}-complete-simulated-stream"}
        assert request("POST", ANA + "/v1/ingest/lineage/next-renewal-outcome", outcome)["status"] == "stored"
    lineage = request("GET", ANA + f"/v1/lineage/{experiment_id}?app_id=lumen-demo")
    counts = {kind: sum(e["kind"] == kind for e in lineage["events"]) for kind in kinds}
    assert counts == {"actual-assignment": 3, "actual-exposure": 2, "next-renewal-outcome": 2}
    # Versioned illustrative policy review consumes only exposed, mature simulated records.
    exposures = {e["exposure_id"] for e in lineage["events"]
                 if e["kind"] == "actual-exposure" and e["source"] == "simulated"}
    matured = [e for e in lineage["events"] if e["kind"] == "next-renewal-outcome"
               and e["source"] == "simulated" and e["exposure_id"] in exposures
               and datetime.fromisoformat(e["outcome_mature_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)]
    assert len(matured) == 2
    policy = {"policy_version": f"{experiment_id}-v2", "source": "simulated",
              "previous_policy_version": f"{experiment_id}-v1",
              "mature_exposed_records_reviewed": len(matured),
              "decision": "manual_review_required", "model_id": fixture["model_id"],
              "model_version": fixture["model_version"], "model_sha256": EXPECTED_SHA}
    assert digest() == before, "offer policy review changed churn model"
    result = {"experiment_id": experiment_id, "proposal_source": proposal["plan_source"],
              "draft_check": draft_check,
              "lineage_counts": counts, "pending_unexposed": 1, "demo_offer_policy": policy,
              "model_sha256_before": before, "model_sha256_after": digest()}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
