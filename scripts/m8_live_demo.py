"""Stage synthetic predictions and experiment lineage so Grafana can refresh between writes.

All event times come from the historical fixture; records are ingested now. No Adapty calls.
"""

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from m6_multi_demo import (ANA, INF, PINNED_SHA, ROOT, check_dashboards, iso,
                           request, send_event, sha, utc)


def dashboard_url(app_id, subscriber, earliest):
    params = {"var-source": "external", "var-app": app_id,
              "var-model": "lumen-temporal-catboost", "var-version": "1.0.0",
              "var-user": hashlib.md5(subscriber.encode()).hexdigest(),
              "from": str(int((earliest - timedelta(days=1)).timestamp() * 1000)),
              "to": "now", "refresh": "5s"}
    return "http://127.0.0.1:3000/d/churn-risk-trajectory?" + urlencode(params)


def stage(label, explanation, pause, delay_seconds):
    print(f"\n[{label}] {explanation}", flush=True)
    if pause:
        input("Откройте Grafana, дождитесь обновления и нажмите Enter... ")
    elif delay_seconds:
        time.sleep(delay_seconds)


def lineage_counts(app_id, experiment_id):
    events = request("GET", ANA + f"/v1/lineage/{experiment_id}?app_id={app_id}")["events"]
    assert all(event["source"] == "simulated" for event in events)
    return {kind: sum(event["kind"] == kind for event in events) for kind in
            ("actual-assignment", "actual-exposure", "next-renewal-outcome")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=uuid4().hex[:10])
    parser.add_argument("--output", type=Path, default=ROOT / ".agent-runtime/m8-live-demo.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pause", action="store_true", help="wait for Enter after each stage")
    mode.add_argument("--delay-seconds", type=float, default=0,
                      help="automatically wait this many seconds after each stage")
    args = parser.parse_args()
    if not args.run_id.isalnum() or args.delay_seconds < 0:
        parser.error("run ID must be alphanumeric and delay must be nonnegative")

    assert sha() == PINNED_SHA, "approved model artifact changed"
    fixture = json.loads((ROOT / "tests/fixtures/temporal_churn_fixture.json").read_text())
    cases = fixture["cases"][:4]
    assert cases[0]["user_id"] == cases[1]["user_id"]
    assert len({case["user_id"] for case in cases}) == 3
    examples = {kind: json.loads((ROOT / "contracts/examples" / f"{kind}.json").read_text())
                for kind in ("actual-assignment", "actual-exposure", "next-renewal-outcome")}
    app_id = f"lumen-m8-{args.run_id}"
    experiment_id = f"m8-simulated-{args.run_id}"
    pseudonyms = {raw: f"synthetic-m8-{args.run_id}-{index}" for index, raw in
                  enumerate(dict.fromkeys(case["user_id"] for case in cases))}
    first_subscriber = pseudonyms[cases[0]["user_id"]]
    url = dashboard_url(app_id, first_subscriber, min(utc(c["as_of_at"]) for c in cases))
    print("ИСТОЧНИК: фиксированная модель + синтетический fixture + симулированные события", flush=True)
    print("EXPERIMENT:", experiment_id, flush=True)
    print("GRAFANA:", url, flush=True)
    print("Время на графиках — историческое время fixture; строки появляются сейчас при записи.", flush=True)

    latest = {}
    predictions = []
    for index, case in enumerate(cases):
        uid = pseudonyms[case["user_id"]]
        prediction = request("POST", INF + "/v1/predict", {
            "request_id": f"{experiment_id}-prediction-{index}", "app_id": app_id,
            "user_id": uid, "model_id": fixture["model_id"],
            "renewal_horizon_days": int(case["features"]["days_until_renewal"]),
            "context": {"as_of_at": case["as_of_at"], "renewal_due_at": case["renewal_due_at"],
                        "feature_source_ref": "synthetic-fixed-fixture"},
            "features": case["features"],
        })
        assert prediction["model_version"] == "1.0.0"
        assert prediction["prediction_source"] == "external"  # model origin; input is synthetic
        assert prediction["churn_probability"] == case["expected"]
        assert prediction["plan_type"] == case["features"]["plan"]
        assert request("GET", ANA + "/v1/predictions/" + prediction["prediction_id"])["plan_type"] == prediction["plan_type"]
        latest[uid] = (prediction, case)
        predictions.append(prediction)
        if index == 0:
            stage("1/7", "Первый прогноз записан: одна точка траектории риска.", args.pause, args.delay_seconds)
        elif index == 1:
            stage("2/7", "Второй срез того же подписчика: траектория и изменение риска.",
                  args.pause, args.delay_seconds)
    stage("3/7", "Три уникальных подписчика: изменились current risk и средний риск.",
          args.pause, args.delay_seconds)

    plan = request("POST", INF + "/v1/retention/plan", {
        "app_id": app_id, "experiment_id": experiment_id, "budget_usd": 30,
        "control_share": 0.34, "discounts": [0.20], "random_seed": 11,
        "candidates": [{"user_id": uid, "churn_probability": pred["churn_probability"],
                        "renewal_price_usd": pred["renewal_price_usd"], "plan_type": pred["plan_type"]}
                       for uid, (pred, _) in latest.items()],
    })
    assert plan["modeled_discount_uplift"] is False
    assert {arm["user_id"] for arm in plan["assignments"]} == set(latest)
    assert any(arm["arm"] == "control" for arm in plan["assignments"])
    print("PLAN:", json.dumps({"arms": {arm["arm"]: sum(a["arm"] == arm["arm"] for a in plan["assignments"])
                                           for arm in plan["assignments"]},
                               "max_exposure_usd": plan["max_allocated_discount_exposure_usd"],
                               "modeled_discount_uplift": plan["modeled_discount_uplift"]}), flush=True)
    stage("4/7", "План сохранён. Grafana не показывает предложения как фактический тест.",
          args.pause, args.delay_seconds)

    arms = {arm["user_id"]: arm for arm in plan["assignments"]}
    records = {}
    for uid, (prediction, case) in latest.items():
        due = utc(case["renewal_due_at"])
        assignment_at = due - timedelta(minutes=30)
        common = {"app_id": app_id, "user_id": uid, "source": "simulated",
                  "prediction_id": prediction["prediction_id"], "model_id": prediction["model_id"],
                  "model_version": prediction["model_version"], "as_of_at": iso(utc(case["as_of_at"])),
                  "renewal_due_at": iso(due), "experiment_id": experiment_id,
                  "variation_id": "control" if arms[uid]["arm"] == "control" else "treatment",
                  "assignment_id": f"{experiment_id}-assignment-{uid}"}
        prefix = f"{experiment_id}-{uid}"
        assignment = {**examples["actual-assignment"], **common,
                      "event_at": iso(assignment_at), "ingested_at": iso(datetime.now(UTC)),
                      "cohort_id": experiment_id, "policy_version": f"{experiment_id}-v1",
                      "randomization_source": "simulated", "idempotency_key": prefix + "-assignment-key",
                      "source_event_id": prefix + "-assignment-source"}
        send_event("actual-assignment", assignment)
        records[uid] = (common, prefix, assignment_at, due, case)
    assert lineage_counts(app_id, experiment_id) == {
        "actual-assignment": 3, "actual-exposure": 0, "next-renewal-outcome": 0}
    stage("5/7", "Три назначения: bar chart +3, таблица показывает exposure pending.",
          args.pause, args.delay_seconds)

    exposed = list(latest)[:2]
    exposure_ids = {}
    for uid in exposed:
        common, prefix, assignment_at, _, _ = records[uid]
        exposure_id = prefix + "-exposure"
        exposure = {**examples["actual-exposure"], **common,
                    "event_at": iso(assignment_at + timedelta(minutes=5)),
                    "ingested_at": iso(datetime.now(UTC)), "exposure_id": exposure_id,
                    "idempotency_key": prefix + "-exposure-key",
                    "source_event_id": prefix + "-exposure-source"}
        send_event("actual-exposure", exposure)
        exposure_ids[uid] = exposure_id
    assert lineage_counts(app_id, experiment_id) == {
        "actual-assignment": 3, "actual-exposure": 2, "next-renewal-outcome": 0}
    stage("6/7", "Два показа: bar chart +2, две строки стали outcome pending.",
          args.pause, args.delay_seconds)

    uid = exposed[0]
    common, prefix, _, due, case = records[uid]
    mature_at = due + timedelta(days=1)
    outcome = {**examples["next-renewal-outcome"], **common,
               "event_at": iso(mature_at + timedelta(minutes=1)),
               "ingested_at": iso(datetime.now(UTC)), "outcome_mature_at": iso(mature_at),
               "exposure_id": exposure_ids[uid], "outcome_id": prefix + "-outcome",
               "renewed": True, "paid_usd": case["features"]["renewal_price_usd"],
               "refunded": False, "idempotency_key": prefix + "-outcome-key",
               "source_event_id": prefix + "-outcome-source",
               "evidence_ref": prefix + "-simulated-stream"}
    send_event("next-renewal-outcome", outcome)
    counts = lineage_counts(app_id, experiment_id)
    assert counts == {"actual-assignment": 3, "actual-exposure": 2,
                      "next-renewal-outcome": 1}
    stage("7/7", "Один зрелый исход: bar chart +1; одна строка стала mature.",
          args.pause, args.delay_seconds)

    assert sha() == PINNED_SHA, "approved model artifact changed during demonstration"
    report = {"source": "simulated", "app_id": app_id, "experiment_id": experiment_id,
              "model_id": fixture["model_id"], "model_version": fixture["model_version"],
              "model_sha256": PINNED_SHA, "grafana_url": url,
              "prediction_ids": [p["prediction_id"] for p in predictions],
              "latest_subscribers": list(latest), "plan_source": plan["plan_source"],
              "modeled_discount_uplift": False, "lineage_counts": counts,
              "dashboards_checked": check_dashboards(),
              "disclaimer": "Historical synthetic fixture and simulated events; no Adapty test or measured effect."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("\nГОТОВО:", json.dumps({"output": str(args.output), "app_id": app_id,
                                    "lineage_counts": counts, "grafana_url": url}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
