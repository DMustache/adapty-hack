#!/usr/bin/env python3
"""HTTP smoke: fixture churn -> experiment planner -> analytics -> Grafana."""
import base64
import json
import os
import time
import urllib.error
import urllib.request
from uuid import uuid4

INF = os.getenv("INFERENCE_URL", "http://127.0.0.1:8001")
ANA = os.getenv("ANALYTICS_URL", "http://127.0.0.1:8002")
GRAFANA = os.getenv("GRAFANA_URL", "http://127.0.0.1:3000")


def env_config(name: str, default: str) -> str:
    if name in os.environ:
        return os.environ[name]
    envfile = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(envfile):
        with open(envfile, encoding="utf-8") as stream:
            for line in stream:
                key, sep, val = line.strip().partition("=")
                if sep and key == name:
                    return val.strip().strip('"').strip("'")
    return default


def request(method: str, url: str, payload=None, auth=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if auth:
        raw = f"{auth[0]}:{auth[1]}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.load(resp)


def main():
    for i in range(40):
        try:
            assert request("GET", INF + "/health")["status"] == "ok"
            assert request("GET", ANA + "/health")["status"] == "ok"
            break
        except (urllib.error.URLError, AssertionError):
            if i == 39:
                raise
            time.sleep(1)

    candidates = []
    runid = uuid4().hex[:8]
    for n in range(1, 13):
        user_id = f"demo-u{n:02d}"
        payload = {
            "request_id": f"{runid}-pred-{n}", "app_id": "lumen-demo",
            "user_id": user_id, "model_id": "mock-churn-v1",
            "renewal_horizon_days": 30, "context": {"category": "photo_video"},
            "features": {"event_count": 4},
        }
        pred = request("POST", INF + "/v1/predict", payload)
        assert pred["prediction_source"] == "mock"
        saved = request("GET", ANA + "/v1/predictions/" + pred["prediction_id"])
        assert saved["prediction_id"] == pred["prediction_id"]
        candidates.append({
            "user_id": user_id, "churn_probability": pred["churn_probability"],
            "renewal_price_usd": 9.99 if n % 2 == 0 else 4.99,
            "plan_type": "monthly" if n % 2 == 0 else "weekly",
        })

    plan = request("POST", INF + "/v1/retention/plan", {
        "app_id": "lumen-demo", "experiment_id": f"smoke-{runid}",
        "budget_usd": 12.00, "control_share": 0.25, "discounts": [0.1, 0.2, 0.3],
        "candidates": candidates,
    })
    assert plan["max_allocated_discount_exposure_usd"] <= 12.00
    assert any(a["arm"] == "control" for a in plan["assignments"])
    assert plan["modeled_discount_uplift"] is False
    persisted = request("GET", ANA + "/v1/experiments/" + plan["experiment_id"])
    assert persisted["experiment_id"] == plan["experiment_id"]
    assert len(request("GET", ANA + "/v1/metrics/churn-risk?app_id=lumen-demo")["points"]) >= 12

    for i in range(40):
        try:
            assert request("GET", GRAFANA + "/api/health")["database"] == "ok"
            break
        except (urllib.error.URLError, AssertionError, KeyError):
            if i == 39:
                raise
            time.sleep(1)
    user = env_config("GF_SECURITY_ADMIN_USER", "admin")
    password = env_config("GF_SECURITY_ADMIN_PASSWORD", "admin_demo")
    board = request("GET", GRAFANA + "/api/dashboards/uid/smart-retention", auth=(user, password))
    assert board["dashboard"]["uid"] == "smart-retention"
    print("PASS: mock churn -> break-even/budget experiment -> Analytics -> PostgreSQL + Grafana")
    print("NO inferred discount uplift/savings; demo model predictions are static fixtures")
    print("Grafana dashboard: http://localhost:3000/d/smart-retention")


if __name__ == "__main__":
    main()
