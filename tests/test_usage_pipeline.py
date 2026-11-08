"""Usage features in the churn pipeline: snapshots -> training -> artifact -> inference adapter -> API -> scoring.

All usage activity here is SIMULATED (synthetic subscribers and synthetic sessions). These tests check that the
pipeline works and does not leak the future; they say nothing about whether real usage data improves accuracy.
"""
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("catboost")
from fastapi.testclient import TestClient

from ml.temporal_churn import snapshots as S
from ml.temporal_churn import train_usage as TU
from ml.usage.features import USAGE_FEATURES
from ml.usage.simulated_check import synthetic_events
from services.inference.app.adapters.temporal_catboost import DEFAULT_DIR as BASELINE_DIR
from services.inference.app.adapters.temporal_catboost import ArtifactIntegrityError
from services.inference.app.adapters.temporal_usage_catboost import TemporalUsageCatBoostAdapter

if not (BASELINE_DIR / "model.cbm").exists():
    pytest.skip("deployed temporal model artifact not installed", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[1]
DAY = pd.Timedelta(days=1)
START = pd.Timestamp("2026-07-01T00:00:00Z")
CUTOFF = pd.Timestamp("2026-10-31T00:00:00Z")
GRID = [{"depth": 3, "iterations": 40}]
RUN = "261329"


# ---------------------------------------------------------------- SIMULATED subscribers
def simulated_lumen(n: int = 220, seed: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """SIMULATED Lumen-shaped users and weekly subscription chains (each chain ends in churn or is still active)."""
    rng = np.random.default_rng(seed)
    users, tx = [], []
    for i in range(1, n + 1):
        uid = f"u{i:05d}"
        install = START + rng.uniform(0, 100) * DAY
        users.append({"user_id": uid, "platform": rng.choice(["iOS", "Android"]), "country": rng.choice(["US", "DE"]),
                      "acquisition_channel": "organic", "onboarding_goal": "travel", "push_opt_in": "yes",
                      "app_version": "3.6.0", "placement": "main", "flow": "main",
                      "ai_edits_first_day": float(rng.integers(0, 6)), "photos_imported": float(rng.integers(0, 30)),
                      "install_at": install, "price_index": 1.0})
        t, k = install + DAY, 0
        while t < CUTOFF:
            tx.append({"user_id": uid, "seq": k, "product": "weekly", "purchase_type": "subscription", "offer": None,
                       "price_usd": 6.99, "purchased_at": t, "expires_at": t + 7 * DAY, "renew_status": True,
                       "renew_status_changed_at": pd.NaT, "refunded_at": pd.NaT,
                       "billing_issue_detected_at": pd.NaT})
            k += 1
            t = t + 7 * DAY
            if rng.random() < 0.18:          # churn: no further renewal
                break
    u, x = pd.DataFrame(users), pd.DataFrame(tx)
    for c in ["purchased_at", "expires_at", "renew_status_changed_at", "refunded_at", "billing_issue_detected_at"]:
        x[c] = pd.to_datetime(x[c], utc=True)
    u["install_at"] = pd.to_datetime(u["install_at"], utc=True)
    return u, x


@pytest.fixture(scope="module")
def world():
    users, tx = simulated_lumen()
    snaps = S.build_snapshots(users, tx, CUTOFF)
    ev = synthetic_events(users, tx, CUTOFF, "signal", np.random.default_rng(5), run_id=RUN)
    ev["subscriber_id"] = "u" + ev["user_id"].str.rsplit("_", n=1).str[1]
    return users, tx, snaps, ev


@pytest.fixture(scope="module")
def trained(world, tmp_path_factory):
    _, _, snaps, ev = world
    before = hashlib.sha256((BASELINE_DIR / "model.cbm").read_bytes()).hexdigest()
    report, models = TU.evaluate(S.add_usage_features(snaps, ev), CUTOFF, grid=GRID, simulated=True)
    out = tmp_path_factory.mktemp("usage_artifact")
    TU.export_usage_model(models[TU.CANDIDATE], report, artifact_dir=out, usage_source="simulated")
    assert hashlib.sha256((BASELINE_DIR / "model.cbm").read_bytes()).hexdigest() == before
    return report, out


@pytest.fixture(scope="module")
def adapter(trained):
    a = TemporalUsageCatBoostAdapter(model_dir=trained[1])
    a.load()
    return a


# ---------------------------------------------------------------- feature set
def test_usage_feature_set_extends_the_unchanged_baseline():
    deployed = json.loads((BASELINE_DIR / "metadata.json").read_text())["features"]
    assert S.FEATURE_SETS["temporal"] == deployed and len(deployed) == 23
    assert S.FEATURE_SETS["temporal_usage"] == deployed + USAGE_FEATURES
    assert {"sessions_7d", "sessions_14d", "sessions_30d", "days_since_last_activity",
            "sessions_trend_7d_delta", "session_rate_7d_vs_30d"} <= set(USAGE_FEATURES)
    assert S.EVALUATED_MODELS == ("static", "temporal_behaviour", "temporal")   # train.py still trains the same


def test_no_usage_source_means_null_usage_features(world):
    _, _, snaps, _ = world
    for events in (None, pd.DataFrame(columns=["subscriber_id", "event_name", "occurred_at"])):
        out = S.add_usage_features(snaps, events)
        assert out[USAGE_FEATURES].isna().all().all() and len(out) == len(snaps)
        pd.testing.assert_frame_equal(out[snaps.columns], snaps)                 # baseline columns untouched


def test_untracked_subscribers_stay_null_and_tracked_get_counts(world):
    _, _, snaps, ev = world
    out = S.add_usage_features(snaps, ev)
    untracked = ~out["user_id"].isin(set(ev["subscriber_id"]))
    assert untracked.any() and out.loc[untracked, USAGE_FEATURES].isna().all().all()
    tracked = out[~untracked & out["sessions_30d"].notna()]
    assert len(tracked) and (tracked["sessions_14d"] >= tracked["sessions_7d"]).all()
    assert (tracked["sessions_30d"] >= tracked["sessions_14d"]).all()


def test_snapshot_usage_features_never_see_the_future(world):
    """Drop every event after a cut: snapshots up to the cut must not change; perturbing later events neither."""
    _, _, snaps, ev = world
    cut = pd.Timestamp("2026-09-01T00:00:00Z")
    full = S.add_usage_features(snaps, ev)
    past_only = S.add_usage_features(snaps, ev[ev["occurred_at"] < cut])
    early = snaps["as_of_at"] <= cut
    pd.testing.assert_frame_equal(full.loc[early, USAGE_FEATURES], past_only.loc[early, USAGE_FEATURES])
    burst = ev[ev["occurred_at"] >= cut].copy()
    burst["occurred_at"] = burst["occurred_at"] + pd.Timedelta(minutes=1)
    noisy = S.add_usage_features(snaps, pd.concat([ev, burst], ignore_index=True))
    pd.testing.assert_frame_equal(full.loc[early, USAGE_FEATURES], noisy.loc[early, USAGE_FEATURES])


# ---------------------------------------------------------------- training
def test_training_report_is_labelled_simulated_and_makes_no_accuracy_claim(trained, tmp_path):
    report, _ = trained
    assert report["simulated"] and report["label"] == TU.SIMULATED_LABEL
    assert set(report["models"]) == {"temporal", "temporal_usage"}
    assert report["models"]["temporal"]["features"] == 23
    assert report["models"]["temporal_usage"]["features"] == 23 + len(USAGE_FEATURES)
    cov = report["info"]["usage_coverage"]["test"]
    assert 0 < cov["share_with_usage"] < 1                                       # tracked and untracked
    assert set(report["acceptance_rule"]) == {"better_in_every_fold", "ci_above_zero", "passes"}
    assert "SIMULATED" in report["verdict"] and "Keep the deployed model" in report["verdict"]
    md = TU.write_report(report, tmp_path)
    assert md.name.startswith("SIMULATED_")
    text = md.read_text(encoding="utf-8")
    assert TU.SIMULATED_LABEL in text and "improv" not in text.lower()


def test_simulated_model_cannot_be_exported_to_the_service_folder(world):
    _, _, snaps, ev = world
    report, models = TU.evaluate(S.add_usage_features(snaps, ev), CUTOFF, grid=GRID, simulated=True)
    with pytest.raises(ValueError, match="simulated"):
        TU.export_usage_model(models[TU.CANDIDATE], report)
    assert not TU.USAGE_ARTIFACT_DIR.exists()


def test_exported_metadata(trained):
    meta = json.loads((trained[1] / "metadata.json").read_text())
    base = json.loads((BASELINE_DIR / "metadata.json").read_text())
    assert meta["model_id"] == "lumen-temporal-usage-catboost" and meta["simulated"] is True
    assert meta["baseline_model"]["sha256"] == base["sha256"]
    assert meta["input_schema"]["required"] == base["features"]
    assert all(meta["input_schema"]["properties"][f]["type"] == ["number", "null"] for f in USAGE_FEATURES)
    assert meta["sha256"] == hashlib.sha256((trained[1] / "model.cbm").read_bytes()).hexdigest()


# ---------------------------------------------------------------- inference
def _record(world, user_tracked: bool):
    _, _, snaps, ev = world
    full = S.add_usage_features(snaps, ev)
    tracked = full["sessions_30d"].notna()
    row = full[tracked if user_tracked else ~tracked].iloc[-1]
    return row, S.feature_record(row, "temporal_usage")


def test_adapter_scores_with_and_without_usage_history(adapter, world):
    _, rec = _record(world, True)
    p_with = adapter.predict("x", rec, {})
    baseline_only = {k: v for k, v in rec.items() if k not in USAGE_FEATURES}
    nulls = {**baseline_only, **{f: None for f in USAGE_FEATURES}}
    p_omitted, p_null = adapter.predict("x", baseline_only, {}), adapter.predict("x", nulls, {})
    assert all(0 < p < 1 for p in (p_with, p_omitted, p_null))
    assert p_omitted == p_null                                   # omitted == null == "no usage history"
    _, untracked = _record(world, False)
    assert all(untracked[f] is None for f in USAGE_FEATURES) and 0 < adapter.predict("y", untracked, {}) < 1


def test_adapter_rejects_tampered_artifacts(trained, tmp_path):
    bad = tmp_path / "bad"
    shutil.copytree(trained[1], bad)
    (bad / "model.cbm").write_bytes((bad / "model.cbm").read_bytes() + b"x")
    with pytest.raises(ArtifactIntegrityError):
        TemporalUsageCatBoostAdapter(model_dir=bad).load()
    reordered = tmp_path / "reordered"
    shutil.copytree(trained[1], reordered)
    meta = json.loads((reordered / "metadata.json").read_text())
    meta["features"][0], meta["features"][1] = meta["features"][1], meta["features"][0]
    (reordered / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(ArtifactIntegrityError, match="deployed model's features"):
        TemporalUsageCatBoostAdapter(model_dir=reordered)


def test_predict_endpoint_serves_both_models_side_by_side(monkeypatch, adapter, world):
    from services.inference.app import main as inference
    from services.inference.app.adapters.temporal_catboost import TemporalCatBoostAdapter
    base = TemporalCatBoostAdapter()
    base.load()
    monkeypatch.setitem(inference.ADAPTERS, adapter.model_id, adapter)
    monkeypatch.setitem(inference.ADAPTERS, base.model_id, base)
    monkeypatch.setattr(inference, "forward_to_analytics", AsyncMock())
    row, rec = _record(world, True)
    ctx = {"as_of_at": row.as_of_at.isoformat(), "renewal_due_at": row.renewal_due_at.isoformat()}
    client = TestClient(inference.app)
    body = {"request_id": "u-1", "app_id": "lumen", "user_id": "p1", "renewal_horizon_days": 7, "context": ctx}
    res = client.post("/v1/predict", json={**body, "model_id": adapter.model_id, "features": rec})
    assert res.status_code == 200, res.text
    assert res.json()["model_id"] == "lumen-temporal-usage-catboost" and res.json()["plan_type"] == "weekly"
    base_rec = {k: v for k, v in rec.items() if k not in USAGE_FEATURES}
    res = client.post("/v1/predict", json={**body, "model_id": base.model_id, "features": base_rec})
    assert res.status_code == 200 and res.json()["model_id"] == "lumen-temporal-catboost"
    # the deployed model's schema still rejects usage features; the usage model rejects unknown ones
    assert client.post("/v1/predict", json={**body, "model_id": base.model_id, "features": rec}).status_code == 422
    assert client.post("/v1/predict", json={**body, "model_id": adapter.model_id,
                                            "features": {**rec, "sessions_90d": 1}}).status_code == 422
    # usage model needs the same UTC cutoff rules as the deployed temporal model
    assert client.post("/v1/predict", json={**body, "context": {}, "model_id": adapter.model_id,
                                            "features": rec}).status_code == 422


def test_scoring_script_builds_usage_requests(world):
    spec = importlib.util.spec_from_file_location("score", ROOT / "scripts" / "score_temporal_snapshots.py")
    score = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(score)
    _, _, snaps, ev = world
    reqs = score.build_requests(S.add_usage_features(snaps, ev), 30, 20, score.USAGE_MODEL_ID)
    assert reqs and all(r["model_id"] == "lumen-temporal-usage-catboost" for r in reqs)
    assert all(set(USAGE_FEATURES) <= set(r["features"]) for r in reqs)
    assert any(r["features"]["sessions_30d"] is not None for r in reqs)        # tracked subscribers have values
    default = score.build_requests(snaps, 30, 20)
    assert all(r["model_id"] == "lumen-temporal-catboost" and len(r["features"]) == 23 for r in default)
