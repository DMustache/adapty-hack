"""Integration: CatBoost predictions -> PostgreSQL -> analytics /v1/retention/at-risk -> Retention offers logic ->
existing retention planner (/v1/retention/plan) -> PostgreSQL.

Runs against a real PostgreSQL: $TEST_DATABASE_URL if set (a server where a scratch database may be created), else a
throwaway local server from the `pixeltable-pgserver` package. Skipped if neither is available. All repository init
SQL files (postgres/init/*.sql) are applied to a fresh database.
"""
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
pd = pytest.importorskip("pandas")
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "discount_advisor") not in sys.path:
    sys.path.append(str(ROOT / "discount_advisor"))

T0 = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
MODEL = "lumen-temporal-catboost"


# ---------------------------------------------------------------- real PostgreSQL
@pytest.fixture(scope="session")
def server_uri(tmp_path_factory):
    uri = os.getenv("TEST_DATABASE_URL")
    if uri:
        yield uri
        return
    pgserver = pytest.importorskip("pixeltable_pgserver", reason="no TEST_DATABASE_URL and no pixeltable-pgserver")
    srv = pgserver.get_server(str(tmp_path_factory.mktemp("pg")), cleanup_mode="stop")
    yield srv.get_uri()


@pytest.fixture(scope="session")
def database_url(server_uri):
    name = f"retention_it_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(server_uri, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = server_uri.rpartition("/")
    query = server_uri.split("?", 1)[1] if "?" in server_uri else ""
    url = f"{base}/{name}" + (f"?{query}" if query else "")
    with psycopg.connect(url, autocommit=True) as c:
        for sql in sorted((ROOT / "postgres" / "init").glob("*.sql")):
            c.execute(sql.read_text(encoding="utf-8"))
    yield url
    with psycopg.connect(server_uri, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def stack(database_url, monkeypatch):
    """Analytics + inference wired together in-process, on a clean database."""
    with psycopg.connect(database_url, autocommit=True) as c:
        c.execute("TRUNCATE churn_predictions, retention_experiments, actual_observations")
    monkeypatch.setenv("DATABASE_URL", database_url)
    from services.analytics.app import main as analytics
    from services.inference.app import main as inference
    a = TestClient(analytics.app)

    async def forward(path, payload):  # what inference does over HTTP, without a network
        r = a.post(path, json=payload)
        assert r.status_code in (200, 201), r.text

    monkeypatch.setattr(inference, "forward_to_analytics", forward)
    return {"analytics": a, "inference": TestClient(inference.app), "db": database_url,
            "has_model": MODEL in inference.ADAPTERS}


def ingest(a, user_id, as_of, due, p, price=6.99, *, model=MODEL, version="1.0.0", app="lumen", plan="weekly",
           pid=None, predicted_at=None):
    payload = {"prediction_id": pid or f"{user_id}-{model}-{as_of.isoformat()}-{price}", "request_id": "r",
               "app_id": app, "user_id": user_id, "model_id": model, "model_version": version,
               "prediction_source": "mock" if model.startswith("mock") else "external",
               "predicted_at": (predicted_at or as_of).isoformat(), "renewal_horizon_days": 7,
               "churn_probability": p, "as_of_at": as_of.isoformat(),
               "renewal_due_at": None if due is None else due.isoformat(),
               "renewal_price_usd": price, "plan_type": plan}
    r = a.post("/v1/ingest/predictions", json=payload)
    assert r.status_code == 201, r.text


def at_risk(a, **params):
    r = a.get("/v1/retention/at-risk", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- 1. end to end with the real CatBoost artifact
def test_catboost_predictions_flow_to_stored_experiment(stack):
    import retention_offers as R
    if not stack["has_model"]:
        pytest.skip("CatBoost artifact/runtime not installed")
    cases = json.loads((ROOT / "tests" / "fixtures" / "temporal_churn_fixture.json").read_text())["cases"]
    inf = stack["inference"]
    for i, case in enumerate(cases):
        f = case["features"]
        as_of = T0 - timedelta(hours=len(cases) - 1 - i)   # keeps the fixture's order; the last case is at T0
        due = as_of + timedelta(days=max(0.5, f["days_until_renewal"]))
        r = inf.post("/v1/predict", json={
            "request_id": f"it-{i}", "app_id": "lumen", "user_id": case["user_id"], "model_id": MODEL,
            "renewal_horizon_days": 7, "features": f, "as_of_at": as_of.isoformat(),
            "renewal_due_at": due.isoformat(), "renewal_price_usd": f["renewal_price_usd"], "plan_type": f["plan"]})
        assert r.status_code == 200, r.text
        assert r.json()["churn_probability"] == pytest.approx(case["expected"], rel=1e-9)
        assert r.json()["plan_type"] == f["plan"]

    payload = R.fetch_at_risk(client=stack["analytics"], app_id="lumen")
    df = R.subscribers_frame(payload)
    expected = {c["user_id"]: c for c in cases}            # later cases overwrite: newest snapshot per subscriber
    assert len(expected) < len(cases)                      # the fixture has two snapshots of one subscriber
    assert len(df) == len(expected) and payload["reference_time"].startswith("2026-10-30T12:00")
    for row in df.itertuples():
        c = expected[row.user_id]
        assert row.churn_probability == pytest.approx(c["expected"], rel=1e-9)
        assert row.plan_type == c["features"]["plan"]
        assert row.revenue_at_risk_usd == pytest.approx(round(c["expected"] * c["features"]["renewal_price_usd"], 2))
    assert list(df["revenue_at_risk_usd"]) == sorted(df["revenue_at_risk_usd"], reverse=True)

    req, unknown = R.plan_request(df, app_id="lumen", experiment_id="it-exp-1", budget_usd=50, control_share=0.2)
    assert unknown == 0
    preview = R.preview_plan(req)
    stored = R.register_plan(req, client=stack["inference"])
    assert stored["request_fingerprint"] == preview.request_fingerprint
    assert stored["modeled_discount_uplift"] is False and stored["plan_source"] == "scenario_experiment"
    with psycopg.connect(stack["db"]) as c:
        row = c.execute("SELECT payload FROM retention_experiments WHERE experiment_id='it-exp-1'").fetchone()
    assert row[0]["request_fingerprint"] == preview.request_fingerprint
    assert {a["user_id"] for a in row[0]["assignments"]} == set(df["user_id"])
    # same experiment id + same request is idempotent; a different request is refused, not overwritten
    assert R.register_plan(req, client=stack["inference"])["request_fingerprint"] == preview.request_fingerprint


# ---------------------------------------------------------------- 2. "latest valid" semantics in SQL
def test_latest_valid_prediction_per_subscriber(stack):
    a = stack["analytics"]
    d = timedelta(days=1)
    ingest(a, "u_newer", T0 - 2 * d, T0 + 3 * d, 0.90)
    ingest(a, "u_newer", T0 - d, T0 + 3 * d, 0.20)                      # newest wins
    ingest(a, "u_fallback", T0 - d, T0 + 2 * d, 0.40)
    ingest(a, "u_fallback", T0, None, 0.99)                             # newer but invalid (no renewal date)
    ingest(a, "u_due", T0 - 3 * d, T0 + 5 * d, 0.10)
    ingest(a, "u_due", T0 - d, T0 - 0.5 * d, 0.70)                      # newest is already due -> excluded, no fallback
    ingest(a, "u_stale", T0 - 10 * d, T0 + 5 * d, 0.50)                 # older than max_age_days
    ingest(a, "u_mock", T0, T0 + d, 0.80, model="mock-churn-v1")        # other model
    ingest(a, "u_ref", T0, T0 + d, 0.30)                                # defines the reference time
    out = at_risk(a)
    users = {s["user_id"]: s for s in out["subscribers"]}
    assert out["reference_time"].startswith("2026-10-30T12:00:00")
    assert set(users) == {"u_newer", "u_fallback", "u_ref"}
    assert users["u_newer"]["churn_probability"] == 0.20
    assert users["u_fallback"]["churn_probability"] == 0.40
    assert out["counts"] == {"subscribers_with_predictions": 5, "renewal_already_due": 1, "stale": 1,
                             "eligible": 3, "returned": 3}
    # ordered by revenue at risk (p x price), highest first
    risk = [s["churn_probability"] * s["renewal_price_usd"] for s in out["subscribers"]]
    assert risk == sorted(risk, reverse=True)
    assert at_risk(a, max_age_days=30)["counts"]["stale"] == 0
    assert at_risk(a, limit=1)["counts"]["returned"] == 1 and len(at_risk(a, limit=1)["subscribers"]) == 1


def test_as_of_time_travel_ignores_later_predictions(stack):
    a = stack["analytics"]
    d = timedelta(days=1)
    ingest(a, "u1", T0 - 3 * d, T0 + d, 0.15)
    ingest(a, "u1", T0, T0 + d, 0.85)                                   # after the chosen as_of
    out = at_risk(a, as_of=(T0 - 2 * d).isoformat())
    assert [s["churn_probability"] for s in out["subscribers"]] == [0.15]
    assert out["reference_time"].startswith("2026-10-28T12:00")


def test_filters_by_app_and_model_version(stack):
    a = stack["analytics"]
    ingest(a, "u1", T0, T0 + timedelta(days=1), 0.3, app="lumen")
    ingest(a, "u2", T0, T0 + timedelta(days=1), 0.3, app="other")
    ingest(a, "u3", T0, T0 + timedelta(days=1), 0.3, version="0.9.0")
    assert {s["user_id"] for s in at_risk(a, app_id="other")["subscribers"]} == {"u2"}
    assert {s["user_id"] for s in at_risk(a, model_version="0.9.0")["subscribers"]} == {"u3"}
    assert at_risk(a, model_id="no-such-model") == {
        "model_id": "no-such-model", "model_version": None, "reference_time": None, "max_age_days": 7.0,
        "counts": {"subscribers_with_predictions": 0, "renewal_already_due": 0, "stale": 0, "eligible": 0,
                   "returned": 0}, "subscribers": []}


def test_invalid_query_parameters_rejected(stack):
    a = stack["analytics"]
    assert a.get("/v1/retention/at-risk", params={"as_of": "2026-10-30T12:00:00"}).status_code == 422
    assert a.get("/v1/retention/at-risk", params={"max_age_days": 0}).status_code == 422
    assert a.get("/v1/retention/at-risk", params={"limit": 0}).status_code == 422


def test_plan_type_column_rejects_unknown_values(stack):
    with psycopg.connect(stack["db"]) as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute("INSERT INTO churn_predictions (prediction_id, request_id, app_id, user_id, model_id, "
                  "model_version, prediction_source, predicted_at, renewal_horizon_days, churn_probability, "
                  "plan_type) VALUES ('x','r','a','u','m','1','external',now(),1,0.1,'annual')")


def test_old_rows_without_plan_type_are_shown_but_left_out_of_the_experiment(stack):
    import retention_offers as R
    a = stack["analytics"]
    ingest(a, "u_known", T0, T0 + timedelta(days=2), 0.5, plan="monthly", price=19.99)
    ingest(a, "u_old", T0, T0 + timedelta(days=2), 0.5, plan=None)
    df = R.subscribers_frame(R.fetch_at_risk(client=a))
    assert set(df["user_id"]) == {"u_known", "u_old"}
    req, unknown = R.plan_request(df, app_id="lumen", experiment_id="e", budget_usd=10)
    assert unknown == 1 and [c.user_id for c in req.candidates] == ["u_known"]


# ---------------------------------------------------------------- 3. scenarios reuse the planner's arithmetic
def _frame():
    import retention_offers as R
    subs = [("a", 0.05, 6.99), ("b", 0.15, 6.99), ("c", 0.25, 19.99), ("d", 0.45, 19.99), ("e", 0.80, 4.99)]
    payload = {"reference_time": T0.isoformat(), "subscribers": [
        {"prediction_id": u, "app_id": "lumen", "user_id": u, "model_version": "1.0.0", "plan_type": "weekly",
         "predicted_at": T0.isoformat(), "as_of_at": T0.isoformat(),
         "renewal_due_at": (T0 + timedelta(days=i + 1)).isoformat(), "churn_probability": p,
         "renewal_price_usd": price} for i, (u, p, price) in enumerate(subs)]}
    return R.subscribers_frame(payload)


def test_discount_scenarios_are_break_even_arithmetic_from_the_planner():
    import retention_offers as R
    from economics import ab_sample_size

    from services.inference.app.economics import break_even
    df = _frame()
    scen = R.discount_scenarios(df, [0.1, 0.2, 0.3], control_share=0.2).set_index("discount")
    for d, row in scen.iterrows():
        be = [break_even(p, d) for p in df["churn_probability"]]
        ok = [b.feasible_in_principle for b in be]
        assert row.can_break_even == sum(ok) == sum(p >= d for p in df["churn_probability"])
        assert row.relative_improvement_needed == pytest.approx(d / (1 - d))
        assert row.extra_renewals_needed == pytest.approx(sum(b.required_absolute_uplift for b, k in zip(be, ok) if k))
        sub = df[ok]
        cost = ((1 - sub.churn_probability) * sub.renewal_price_usd * d).sum()
        assert row.discount_cost_on_baseline_renewers_usd == pytest.approx(cost)
        # break-even identity: the extra renewals, paid at the discounted price, exactly repay the discount given to
        # subscribers who would have renewed anyway
        extra = sum(b.required_absolute_uplift * price * (1 - d)
                    for b, k, price in zip(be, ok, df.renewal_price_usd) if k)
        assert extra == pytest.approx(cost)
        base = sum(b.baseline_renewal_probability for b, k in zip(be, ok) if k) / sum(ok)
        assert row.users_per_arm_to_detect == ab_sample_size(base, d / (1 - d), comparisons=3)
        assert row.users_per_arm_available == pytest.approx(sum(ok) * 0.8 / 3)


def test_exposure_totals_and_groupings():
    import retention_offers as R
    df = _frame()
    ex = R.exposure(df)
    assert ex["revenue_at_risk_usd"] == pytest.approx(df.revenue_at_risk_usd.sum())
    assert ex["expected_non_renewals"] + ex["expected_renewals"] == pytest.approx(len(df))
    for by in ("risk", "renewal", "plan"):
        t = R.exposure_by(df, by)
        assert t.subscribers.sum() == len(df)
        assert t.revenue_at_risk_usd.sum() == pytest.approx(ex["revenue_at_risk_usd"])


def test_no_uplift_or_optimal_discount_claims():
    import retention_offers as R
    df = _frame()
    req, _ = R.plan_request(df, app_id="lumen", experiment_id="claims", budget_usd=100)
    result = R.preview_plan(req)
    assert result.modeled_discount_uplift is False
    text = " ".join(R.recommendations(R.discount_scenarios(df), result)).lower()
    for phrase in ("optimal", "will increase", "guarantee", "expected uplift", "best discount"):
        assert phrase not in text
    assert "no observed discount-response data" in R.DISCLAIMER.lower()
    # a discount nobody can break even on is advised against, not recommended
    assert any("don't test it" in s.lower() for s in R.recommendations(R.discount_scenarios(df, [0.9])))


def test_unreachable_service_is_reported_not_raised_raw():
    import retention_offers as R
    with pytest.raises(R.ServiceError, match="cannot reach"):
        R.fetch_at_risk("http://127.0.0.1:9")
