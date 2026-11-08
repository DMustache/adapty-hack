"""Streamlit 'Retention offers' tab: existing subscribers at risk (CatBoost predictions from PostgreSQL), revenue
exposure, break-even discount scenarios and a randomized experiment from the existing planner.

Independent of the acquisition Discount Advisor: it reads nothing from the sidebar and changes nothing there.
"""
from __future__ import annotations

from datetime import UTC, datetime, time

import retention_offers as R
import streamlit as st

USD = st.column_config.NumberColumn(format="$%.2f")
PCT = st.column_config.NumberColumn(format="percent")


@st.cache_data(ttl=60, show_spinner="Loading predictions from analytics…")
def _load(analytics_url, model_id, app_id, model_version, as_of, max_age_days):
    return R.fetch_at_risk(analytics_url, model_id=model_id, app_id=app_id or None,
                           model_version=model_version or None, as_of=as_of, max_age_days=max_age_days)


def render() -> None:
    st.subheader("Retention offers · existing subscribers")
    st.caption("Who is likely **not to renew** at their next renewal, how much revenue that puts at risk, and which "
               "renewal discounts are worth a **randomized test**. Churn probabilities come from the deployed CatBoost "
               "model (`lumen-temporal-catboost`), stored in PostgreSQL by the analytics service. This tab is separate "
               "from the acquisition Discount Advisor and ignores its sidebar.")
    st.warning("**No observed discount-response data.** The numbers below are break-even thresholds (how much renewal "
               "would have to improve to pay for a discount) and a test design. They are not predicted uplift, not an "
               "optimal discount, and not guaranteed revenue.", icon="⚠️")

    with st.expander("Data source", expanded=False):
        c1, c2 = st.columns(2)
        analytics_url = c1.text_input("Analytics URL", R.DEFAULT_ANALYTICS_URL, key="ro_analytics")
        inference_url = c2.text_input("Inference URL", R.DEFAULT_INFERENCE_URL, key="ro_inference")
        c3, c4, c5 = st.columns(3)
        model_id = c3.text_input("Model id", R.MODEL_ID, key="ro_model")
        app_id = c4.text_input("App id (blank = all)", "", key="ro_app")
        model_version = c5.text_input("Model version (blank = any)", "", key="ro_version")
        c6, c7 = st.columns(2)
        ref_mode = c6.radio("Evaluate at", ["Newest prediction in the database", "A specific date (UTC)"],
                            key="ro_refmode",
                            help="The synthetic Lumen predictions are dated 2026; 'newest prediction' uses the data's "
                                 "own clock. Renewals already due at this time are excluded.")
        as_of = None
        if ref_mode != "Newest prediction in the database":
            day = c6.date_input("Date", key="ro_date")
            as_of = datetime.combine(day, time(23, 59, 59), tzinfo=UTC)
        max_age = c7.number_input("Ignore predictions older than (days)", 1.0, 90.0, 7.0, 1.0, key="ro_maxage")
        if st.button("Reload", key="ro_reload"):
            _load.clear()

    try:
        payload = _load(analytics_url, model_id, app_id, model_version, as_of, max_age)
    except R.ServiceError as exc:
        st.error(f"Could not load predictions. {exc}")
        st.info("Start the services (`docker compose up --build`), then store predictions, e.g. "
                "`python scripts/score_temporal_snapshots.py --data-dir <adapty-seed-data-hack>/data/offline`. "
                "Apply `postgres/init/005-retention-offers.sql` once to an existing database volume.")
        return

    df_all = R.subscribers_frame(payload)
    counts = payload["counts"]
    st.caption(f"Reference time **{payload['reference_time'] or '—'}** · {counts['subscribers_with_predictions']} "
               f"subscribers with a valid prediction · excluded: {counts['renewal_already_due']} renewal already due, "
               f"{counts['stale']} prediction older than {payload['max_age_days']:g} days · "
               f"{counts['returned']} shown.")
    if df_all.empty:
        st.info("No subscriber has a valid, current prediction with a renewal price and date. Nothing to plan.")
        return

    # ------------------------------------------------ filters
    f1, f2, f3 = st.columns(3)
    min_p = f1.slider("Minimum churn probability", 0.0, 1.0, 0.0, 0.05, key="ro_minp")
    max_days = f2.slider("Renewal within (days)", 1, 45, 45, key="ro_days")
    plans = sorted(df_all["plan_type"].fillna("unknown").unique())
    chosen = f3.multiselect("Plan", plans, plans, key="ro_plans")
    df = df_all[(df_all["churn_probability"] >= min_p) & (df_all["days_until_renewal"] <= max_days)
                & df_all["plan_type"].fillna("unknown").isin(chosen)].reset_index(drop=True)
    if df.empty:
        st.info("No subscribers match these filters.")
        return

    # ------------------------------------------------ 1. at risk + exposure
    ex = R.exposure(df)
    m = st.columns(4)
    m[0].metric("Subscribers", f"{ex['subscribers']:,}")
    m[1].metric("Renewal revenue due", f"${ex['renewal_revenue_due_usd']:,.2f}")
    m[2].metric("Expected revenue at risk", f"${ex['revenue_at_risk_usd']:,.2f}",
                help="Σ churn probability × renewal price (face value, before store fee).")
    m[3].metric("Expected non-renewals", f"{ex['expected_non_renewals']:,.1f}",
                help=f"Mean churn probability {ex['mean_churn_probability']:.1%}.")

    st.markdown("#### Subscribers at risk")
    st.dataframe(df.head(200), hide_index=True, use_container_width=True, column_config={
        "churn_probability": st.column_config.ProgressColumn("churn probability", min_value=0, max_value=1,
                                                             format="percent"),
        "renewal_price_usd": USD, "revenue_at_risk_usd": USD,
        "days_until_renewal": st.column_config.NumberColumn(format="%.1f")})
    if len(df) > 200:
        st.caption(f"Top 200 of {len(df):,} by revenue at risk.")

    st.markdown("#### Revenue exposure")
    by = st.radio("Group by", ["risk", "renewal", "plan"], horizontal=True, key="ro_by",
                  format_func={"risk": "Churn-probability band", "renewal": "Days until renewal",
                               "plan": "Plan"}.get)
    table = R.exposure_by(df, by)
    st.dataframe(table, hide_index=True, use_container_width=True, column_config={
        "renewal_revenue_due_usd": USD, "revenue_at_risk_usd": USD, "mean_churn_probability": PCT,
        "share_of_revenue_at_risk": PCT})

    # ------------------------------------------------ 2. discount scenarios
    st.markdown("#### Discount scenarios (break-even, from the retention planner)")
    s1, s2 = st.columns(2)
    discounts = s1.multiselect("Renewal discounts to evaluate", [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50],
                               list(R.DEFAULT_DISCOUNTS), format_func=lambda d: f"{d:.0%}", key="ro_discounts")
    control_share = s2.slider("Control share", 0.05, 0.5, 0.2, 0.05, key="ro_control")
    if not discounts:
        st.info("Pick at least one discount.")
        return
    scen = R.discount_scenarios(df, discounts, control_share)
    st.dataframe(scen, hide_index=True, use_container_width=True, column_config={
        "discount": PCT, "baseline_renewal_rate": PCT, "renewal_rate_needed": PCT,
        "relative_improvement_needed": PCT, "revenue_at_risk_usd": USD,
        "discount_cost_on_baseline_renewers_usd": USD,
        "users_per_arm_available": st.column_config.NumberColumn(format="%.0f")})
    st.caption("Offering discount d on one renewal breaks even only if renewal rises from p₀ to p₀ ÷ (1 − d), a "
               "+d/(1−d) relative improvement for every subscriber (20% → +25%). Subscribers whose churn probability "
               "is below d can't break even. *Discount cost on baseline renewers* = discount paid to people who would "
               "have renewed anyway = the revenue extra renewals must win back. Sample size: two-proportion test, "
               "α 0.05 split across arms, power 80%, at exactly the break-even change.")

    # ------------------------------------------------ 3. experiment
    st.markdown("#### Experiment recommendation")
    e1, e2, e3 = st.columns(3)
    budget = e1.number_input("Budget for face-value discount exposure ($)", 0.0, 1e7, 100.0, 10.0, key="ro_budget")
    seed = e2.number_input("Random seed", 0, 2**31 - 1, 42, key="ro_seed")
    default_id = f"retention-{(app_id or 'all')}-{datetime.now(UTC):%Y%m%d}"
    experiment_id = e3.text_input("Experiment id", default_id, key="ro_expid")
    try:
        req, unknown_plan = R.plan_request(df, app_id=app_id or "lumen", experiment_id=experiment_id,
                                           budget_usd=budget, control_share=control_share, discounts=discounts,
                                           random_seed=int(seed))
    except ValueError as exc:
        st.info(str(exc))
        return
    result = R.preview_plan(req)
    if unknown_plan:
        st.caption(f"{unknown_plan} subscriber(s) left out: plan type unknown (predictions stored before plan_type "
                   "existed).")
    for line in R.recommendations(scen, result):
        st.markdown("- " + line)
    st.markdown("**Randomized allocation preview** (the planner's `make_plan`; nothing stored yet)")
    st.dataframe(R.arm_summary(result), hide_index=True, use_container_width=True, column_config={
        "revenue_at_risk_usd": USD, "max_discount_exposure_usd": USD, "mean_baseline_renewal": PCT,
        "mean_renewal_needed": PCT})
    st.caption(f"Max face-value discount exposure ${result.max_allocated_discount_exposure_usd:,.2f} of "
               f"${result.budget_usd:,.2f} · {result.disclaimer}")
    if st.button("Register this experiment (POST /v1/retention/plan)", key="ro_register"):
        try:
            stored = R.register_plan(req, inference_url)
        except R.ServiceError as exc:
            st.error(str(exc))
        else:
            same = stored.get("request_fingerprint") == result.request_fingerprint
            st.success(f"Registered `{stored['experiment_id']}` · {len(stored['assignments'])} assignments · "
                       + ("matches the preview." if same else "fingerprint differs from the preview!"))
    st.caption(R.DISCLAIMER)
