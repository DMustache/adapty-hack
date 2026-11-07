"""Discount Advisor: should we test a discount for this subscription audience, and which one?

Run:  streamlit run app.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import charts
from data import CATALOG, CONVERSION_WINDOW_DAYS, SUBSCRIPTION_PRODUCTS, load
from economics import (ANCHOR_DISCOUNT, SENSITIVITY_PARAMS, Assumptions, Experiment, InfeasibleAssumption,
                       max_feasible_lift, plan_test, sensitivity_grid, simulate, switch_points, win_frequency)
from metrics import (MIN_AT_RISK, MIN_PAYERS, SEGMENT_DIMENSIONS, TAIL_RATES, country_price_vs_conversion,
                     periods_in_horizon, product_values, refund_rate, segment_baseline, segment_table)

st.set_page_config(page_title="Discount Advisor", layout="wide")

DURATIONS = {"First paid payment only": "first_payment", "First month of payments": "1m",
             "First 3 months of payments": "3m", "Every payment (permanent price cut)": "all"}
DATA = ":blue-background[**DATA**]"
CALC = ":violet-background[**CALCULATED**]"
ASSUMED = ":orange-background[**ASSUMED**]"
FILTER_DIMS = ["None", "Country", "Price tier", "Platform", "Acquisition channel", "Flow (paywall)"]


@st.cache_resource
def get_data():
    return load()


ds = get_data()
U = ds.users

# ================================================================ sidebar
with st.sidebar:
    st.header("1 · Audience")
    _placements = sorted(U["placement"].unique()) + ["All placements (pooled)"]
    placement = st.selectbox("Paywall placement (where the offer is shown)", _placements,
                             index=_placements.index("onboarding") if "onboarding" in _placements else 0,
                             help="Every install in the data saw exactly one placement. The selected placement's "
                                  "installs are the denominator for conversion, revenue and traffic.")
    dim = st.selectbox("Segment filter", FILTER_DIMS)
    mask = (U["placement"] == placement) if placement != "All placements (pooled)" else pd.Series(True, index=U.index)
    audience = f"placement `{placement}`"
    if dim != "None":
        col = SEGMENT_DIMENSIONS[dim]
        seg_value = st.selectbox(dim, sorted(U.loc[mask, col].dropna().astype(str).unique()))
        mask = mask & (U[col].astype(str) == seg_value)
        audience += f" · {dim.lower()} = {seg_value}"

    st.header("2 · Offer")
    duration_label = st.radio("Discount applies to", list(DURATIONS),
                              help="A free trial is not a paid receipt: 'first paid payment' is the first receipt with "
                                   "a price above zero.")
    duration = DURATIONS[duration_label]
    horizon = st.select_slider("Revenue horizon (months)", [3, 6, 12], value=12)
    max_discount = st.slider("Max allowed discount", 0.05, 0.50, 0.40, 0.05, format="%.2f")

    st.header("3 · Assumptions (not in the data)")
    st.caption(f"Relative conversion lift from a **{ANCHOR_DISCOUNT:.0%} discount**:")
    lift_low, lift_high = st.slider("Low – high", 0.0, 1.5, (0.05, 0.50), 0.01, format="%.2f")
    if lift_high > lift_low:
        lift_mode = st.slider("Most likely", lift_low, lift_high, float(np.clip(0.20, lift_low, lift_high)), 0.01,
                              format="%.2f")
    else:
        lift_mode = lift_low
        st.caption(f"Most likely = {lift_mode:.2f} (single-value range: no response uncertainty)")
    q = st.slider("Market ceiling q (max conversion = min(1, q × baseline))", 1.2, 5.0, 2.0, 0.1)
    rho = st.slider("ρ: value of a discount-driven buyer vs a regular one", 0.3, 1.0, 0.85, 0.05)
    k = st.slider("k: step-up churn when full price returns", 0.0, 1.0, 0.3, 0.05)
    store_fee = st.selectbox("Store fee (applied to baseline and discount alike)", [0.15, 0.30],
                             format_func=lambda x: f"{x:.0%}")
    include_sampling = st.checkbox("Include sampling uncertainty of measured c₀ and V₀", value=True)

    st.header("4 · Experiment")
    arms = st.select_slider("Discount arms (plus one control)", [1, 2, 3], value=1)
    min_plaus = st.slider("Worth testing only if it beats full price in ≥ this share of scenarios", 0.3, 0.9, 0.5, 0.05)
    max_weeks = st.slider("Longest acceptable test (weeks)", 2, 16, 8)
    allocation = st.slider("Share of eligible traffic in the test", 0.1, 1.0, 1.0, 0.1)
    override = st.checkbox("Use my real weekly traffic instead of the dataset sample")
    traffic_override = st.number_input("Real eligible users per week", 100, 10_000_000, 5000, 100) if override else None

asm = Assumptions(lift_low=lift_low, lift_mode=lift_mode, lift_high=lift_high, rho=rho, k=k, q=q,
                  store_fee=store_fee, include_sampling=include_sampling)
survivals = product_values(ds, horizon)
base = segment_baseline(ds, mask, audience, horizon, survivals)
a = base.affected_share(duration)
weekly = float(traffic_override) if traffic_override else base.weekly_installs
traffic_source = "your real-traffic input" if traffic_override else "dataset sample"
sub_mix = base.product_mix[[p for p in base.product_mix.index if p in SUBSCRIPTION_PRODUCTS]]
main_plan = sub_mix.idxmax() if len(sub_mix) else None
review_days = CONVERSION_WINDOW_DAYS + (CATALOG[main_plan]["period_days"] if main_plan else 0)
exp = Experiment(weekly_eligible=weekly, allocation=allocation, arms=arms, max_weeks=max_weeks,
                 min_plausibility=min_plaus, max_discount=max_discount, wait_days=CONVERSION_WINDOW_DAYS,
                 review_days=review_days, traffic_source=traffic_source)

st.title("Discount Advisor")
st.caption("Should we **test** a discount for this subscription audience, and which one? · "
           "**Synthetic data** (Adapty hackathon *Lumen* app) · data observed up to "
           f"{ds.as_of:%d %b %Y %H:%M} UTC")
st.markdown(f"{DATA} measured from the data · {CALC} exact arithmetic on measured inputs and stated assumptions · "
            f"{ASSUMED} your scenario inputs or model structure the data can't identify")
st.markdown(f"**Audience:** {audience} · {base.installs:,} mature installs · {base.payers:,} payers")

problem = None
if base.small:
    problem = (f"Only {base.payers} payers in this audience (minimum {MIN_PAYERS}). Baselines are too noisy for a "
               "recommendation. Widen the audience.")
sim = plan = None
if problem is None:
    try:
        sim = simulate(base.measured(duration), asm)
        plan = plan_test(sim, base.conversion, exp, rev_sd=base.revenue_sd)
    except InfeasibleAssumption as e:
        problem = f"Assumptions can't be used: {e}"

max_lift = float(max_feasible_lift(base.conversion, q)) if base.conversion > 0 else float("nan")

tab_rec, tab_sens, tab_cmp, tab_base, tab_data, tab_method = st.tabs(
    ["Recommendation", "Sensitivity", "Compare segments", "Baselines", "Data reality check", "Method"])

# ================================================================ recommendation
with tab_rec:
    lo, hi = base.conversion_ci
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Baseline conversion · DATA", f"{base.conversion:.1%}", help=f"95% Wilson CI {lo:.1%}–{hi:.1%}; "
              f"first paid receipt within {CONVERSION_WINDOW_DAYS} days of install")
    c1.caption(f"95% CI {lo:.1%}–{hi:.1%}")
    c2.metric("Payers · DATA", f"{base.payers:,}", help=f"of {base.installs:,} mature installs")
    c3.metric(f"Revenue per payer, {horizon} mo · DATA + tail", f"${base.value_per_converter:.2f}",
              help="Net of refunds, before store fee. "
                   f"{base.v0_split.get('extrapolated_tail', 0):.0%} comes from the extrapolated renewal tail.")
    c3.caption(f"{base.v0_split.get('extrapolated_tail', 0):.0%} extrapolated")
    c4.metric("Discount touches · CALCULATED", f"{a:.0%} of payer revenue", help=duration_label)
    c5.metric(f"Eligible users/week · {'ASSUMED' if traffic_override else 'DATA'}", f"{weekly:,.0f}",
              help=traffic_source)

    if problem:
        st.error(problem)
    else:
        (st.success if plan.test_discount else st.info)(plan.headline)
        if plan.decision_rule:
            st.markdown(plan.decision_rule)

        st.subheader("Which discounts are worth testing?")
        t = plan.table
        st.dataframe(t.rename(columns={
            "discount": "Discount", "breakeven_lift": "Break-even lift · CALC", "breakeven_conv": "Conversion needed · CALC",
            "assumed_lift_mode": "Assumed lift · ASSUMED", "p_beats_base": "P(beats full price) · ASSUMED",
            "uplift_vs_base": "Exp. revenue vs full price · ASSUMED", "n_per_arm": "Users / arm · CALC",
            "weeks": "Weeks incl. wait · CALC", "n_per_arm_revenue": "Users / arm, revenue test · CALC",
            "verdict": "Verdict"}).style.format({
            "Discount": "{:.0%}", "Break-even lift · CALC": "{:.1%}", "Conversion needed · CALC": "{:.1%}",
            "Assumed lift · ASSUMED": "{:.0%}", "P(beats full price) · ASSUMED": "{:.0%}",
            "Exp. revenue vs full price · ASSUMED": "{:+.1%}", "Users / arm · CALC": "{:,}",
            "Weeks incl. wait · CALC": "{:.1f}", "Users / arm, revenue test · CALC": "{:,.0f}"}, na_rep="—"),
            hide_index=True, width="stretch")
        st.caption("Break-even lift = the smallest conversion improvement that pays for the discount, so the "
                   "conversion test is sized to detect exactly that. P(beats full price) is the share of simulated "
                   "scenarios in which the discount earns more. It's only as good as your assumptions.")

        left, right = st.columns(2)
        left.plotly_chart(charts.revenue_curve(sim, plan.test_discount or None), width="stretch")
        left.caption(f"Band = {sim.attrs['interval_label']}. Not included: uncertainty in ρ, k, q, the renewal tail "
                     "rule, or the shape of the response curve.")
        right.plotly_chart(charts.breakeven_vs_assumed(sim), width="stretch")
        right.caption("A discount can only pay off where the orange (assumed) line sits above the blue "
                      "(break-even) line.")

    st.subheader("What this rests on")
    split = base.v0_split
    rr = refund_rate(ds.tx)
    data_rows = pd.DataFrame([
        ["Baseline conversion c₀", f"{base.conversion:.1%} (95% CI {lo:.1%}–{hi:.1%})",
         f"{base.payers:,} payers / {base.installs:,} installs aged ≥ {CONVERSION_WINDOW_DAYS} days"],
        ["Observed net receipts per payer so far", f"${base.observed_net_per_payer:.2f}",
         "cash actually received up to the cutoff, refunded receipts = $0"],
        ["Refund rate (paid receipts)", f"{base.refund_rate_receipts:.1%}", f"{base.paid_receipts:,} receipts"],
        ["Plan mix of payers", ", ".join(f"{p} {v:.0%}" for p, v in base.product_mix.items()), "first paid receipt"],
        ["Eligible installs per week", f"{base.weekly_installs:,.0f}", "dataset sample, not real app volume"],
    ], columns=["Input", "Value", "Basis"])
    calc_rows = pd.DataFrame([
        [f"Revenue per payer V₀ ({horizon} mo, before fee)", f"${base.value_per_converter:.2f}",
         f"first receipt {split.get('first_receipt', 1):.0%} · estimated renewals {split.get('estimated_renewals', 0):.0%}"
         f" · extrapolated tail {split.get('extrapolated_tail', 0):.0%}"],
        ["Share of V₀ the discount touches (a)", f"{a:.0%}", f"{duration_label}, this audience's plan mix"],
        ["Net revenue per eligible user at full price", f"${base.revenue_per_install * (1 - store_fee):.2f}",
         f"c₀ × V₀ × (1 − {store_fee:.0%} fee)"],
        ["Max lift the ceiling allows", f"< {max_lift:.0%}" if max_lift == max_lift else "—", "min(1, q·c₀)/c₀ − 1"],
    ], columns=["Input", "Value", "How"])
    asm_rows = pd.DataFrame([
        [f"Lift from a {ANCHOR_DISCOUNT:.0%} discount (L₂₀)", f"{lift_low:.0%} / {lift_mode:.0%} / {lift_high:.0%}",
         "low / most likely / high (triangular)"],
        ["Response curve shape", "lognormal willingness-to-pay", "a modelling choice, not identified by the data"],
        ["Market ceiling q", f"{q:.1f}×", "most users who could ever convert"],
        ["ρ (discount-driven buyer value)", f"{rho:.0%}", "deal-seekers renew less"],
        ["k (step-up churn)", f"{k:.2f}", f"{max_discount:.0%} off loses {k * max_discount:.0%} of later payments"],
        ["Store fee", f"{store_fee:.0%}", "same for baseline and discount"],
        ["Renewal tail rule", f"mean of last {TAIL_RATES} observed renewal rates", "beyond the observed periods"],
        ["Weekly traffic", f"{traffic_override:,.0f}" if traffic_override else "— (dataset)", "override"],
    ], columns=["Input", "Value", "Note"])
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"{DATA}")
    c1.dataframe(data_rows, hide_index=True, width="stretch")
    c2.markdown(f"{CALC}")
    c2.dataframe(calc_rows, hide_index=True, width="stretch")
    c3.markdown(f"{ASSUMED}")
    c3.dataframe(asm_rows, hide_index=True, width="stretch")

    with st.expander("How the test size and duration are calculated"):
        st.markdown(f"""
- **Population:** installs in *{audience}*. Conversion, revenue and traffic all use this same audience.
- **Users per arm:** two-sided two-proportion z-test (pooled variance under H₀, no continuity correction),
  α = 0.05{'' if arms == 1 else f' ÷ {arms} arms (Bonferroni)'}, power 80%, detecting c₀ → c₀ × (1 + break-even lift).
  Check: 10% → 12% needs 3,841 per arm (textbook value).
- **Duration** = users per arm ÷ (weekly eligible × {allocation:.0%} allocation ÷ {arms + 1} groups)
  + {CONVERSION_WINDOW_DAYS}-day outcome wait.
- **Traffic:** {weekly:,.0f}/week from the {traffic_source}. The dataset is a 50k-user sample, so enter real traffic
  for real durations.
- **Revenue test** (guardrail): z-test on mean revenue per user, using the measured spread (${base.revenue_sd:.2f}),
  detecting the *expected* revenue gain. It needs far more users, so it's a guardrail, not the launch criterion.
""")

# ================================================================ sensitivity
with tab_sens:
    if problem:
        st.error(problem)
    else:
        st.markdown("How the **best discount under the assumptions** changes when the assumptions change. Everything "
                    "else is held at the sidebar values.")
        sp = switch_points(base.conversion, base.value_per_converter, a, asm)
        l, r = st.columns([2, 3])
        l.markdown(f"{ASSUMED} **Switch points** (q = {q}, ρ = {rho}, k = {k})")
        l.dataframe(pd.DataFrame({
            "If a 20% discount lifts conversion by": [f"{x.lift_from:.0%} – {x.lift_to:.0%}" for x in sp.itertuples()],
            "…the best discount is": ["keep full price" if x.best_discount == 0 else f"{x.best_discount:.0%}"
                                      for x in sp.itertuples()]}), hide_index=True, width="stretch")
        l.caption(f"Lifts of {sp.attrs['max_feasible_lift']:.0%} or more are impossible under q = {q}, so they're not shown.")
        wins = sp[sp.best_discount > 0]
        if not wins.empty:
            l.info(f"A discount can only beat full price if a 20% discount lifts conversion by at least "
                   f"**{wins.lift_from.iloc[0]:.0%}**.")
        else:
            l.info("Full price wins across every feasible response.")
        param = r.selectbox("Second assumption", list(SENSITIVITY_PARAMS), format_func=SENSITIVITY_PARAMS.get)
        grid = sensitivity_grid(base.conversion, base.value_per_converter, a, asm, param)
        r.plotly_chart(charts.sensitivity_heatmap(grid, param, SENSITIVITY_PARAMS[param], (lift_low, lift_high)),
                       width="stretch")
        freq = win_frequency(base.conversion, base.value_per_converter, a, asm)
        st.markdown("**How often each discount wins across your L₂₀ range** (evenly spaced, 1-point steps): " + ", ".join(
            f"{'full price' if d == 0 else f'{d:.0%}'} {s:.0%}" for d, s in freq.items())
            + ". A wide spread means the data can't settle it; that's what the test is for.")
        st.caption("Why can the best discount *fall* when the assumed lift is very high? A strong response means a "
                   "modest discount already reaches most users who could ever convert. Deeper discounts then mostly "
                   "give money away to people who'd buy anyway.")

# ================================================================ compare segments
with tab_cmp:
    cmp_dim = st.selectbox("Compare across", ["Placement"] + FILTER_DIMS[1:])
    ccol = SEGMENT_DIMENSIONS[cmp_dim]
    scope = pd.Series(True, index=U.index) if cmp_dim == "Placement" or placement.startswith("All") \
        else (U["placement"] == placement)
    st.caption(("All placements." if cmp_dim == "Placement" else f"Within placement `{placement}`.") +
               " Each row uses its **own** measured conversion, revenue, plan mix and traffic (dataset volumes), with "
               "the sidebar's offer, assumptions and experiment settings.")
    rows = []
    for v in sorted(U.loc[scope, ccol].dropna().astype(str).unique()):
        m = scope & (U[ccol].astype(str) == v)
        b = segment_baseline(ds, m, v, horizon, survivals)
        lo_, hi_ = b.conversion_ci
        row = {"Segment": v, "Payers": b.payers, "Conversion": b.conversion, "95% CI": f"{lo_:.1%}–{hi_:.1%}",
               "Rev/payer": b.value_per_converter, "Extrapolated": b.v0_split.get("extrapolated_tail", 0),
               "Discount touches": b.affected_share(duration), "Installs/wk": b.weekly_installs}
        if b.small:
            row["Status"] = f"too few payers (<{MIN_PAYERS})"
        else:
            try:
                s = simulate(b.measured(duration), asm)
                e = Experiment(**{**exp.__dict__, "weekly_eligible": b.weekly_installs, "traffic_source": "dataset sample"})
                p = plan_test(s, b.conversion, e)
                row["Break-even @20%"] = float(s.set_index("discount").loc[0.20, "breakeven_lift"])
                ch = p.table[p.table.discount == p.test_discount]
                row["Test candidate"] = p.test_discount
                row["P(beats)"] = ch.p_beats_base.iloc[0] if not ch.empty else np.nan
                row["Users/arm"] = ch.n_per_arm.iloc[0] if not ch.empty else np.nan
                row["Weeks"] = ch.weeks.iloc[0] if not ch.empty else np.nan
                row["Status"] = "ok"
            except InfeasibleAssumption:
                row["Status"] = "assumption infeasible here"
        rows.append(row)
    cmp = pd.DataFrame(rows)
    st.dataframe(cmp.style.format({
        "Payers": "{:,}", "Conversion": "{:.1%}", "Rev/payer": "${:.2f}", "Extrapolated": "{:.0%}",
        "Discount touches": "{:.0%}", "Installs/wk": "{:,.0f}", "Break-even @20%": "{:.1%}",
        "Test candidate": lambda x: "keep full price" if x == 0 else f"{x:.0%}", "P(beats)": "{:.0%}",
        "Users/arm": "{:,.0f}", "Weeks": "{:.1f}"}, na_rep="—"), width="stretch", hide_index=True)
    st.info("Segments differ here through **measured** conversion, plan mix, revenue and traffic. The assumed response "
            "to a discount is the same for every segment. Country and price-tier differences in conversion are "
            "**not** evidence of different price sensitivity, because the data can't separate price from country.")

# ================================================================ baselines
with tab_base:
    st.markdown(f"{DATA} Conversion = first paid receipt within {CONVERSION_WINDOW_DAYS} days of install, among installs "
                f"at least {CONVERSION_WINDOW_DAYS} days old at the cutoff.")
    bdim = st.selectbox("Break down by", ["Placement"] + FILTER_DIMS[1:], key="bdim")
    within = None if bdim == "Placement" or placement.startswith("All") else (U["placement"] == placement)
    tbl = segment_table(ds, bdim, horizon, within)
    st.dataframe(tbl.drop(columns=["small"]).assign(flag=np.where(tbl["small"], f"< {MIN_PAYERS} payers", "")).style.format({
        "installs": "{:,}", "payers": "{:,}", "conversion": "{:.1%}", "conv_ci_low": "{:.1%}", "conv_ci_high": "{:.1%}",
        "refund_rate": "{:.1%}", "observed_net_per_payer": "${:.2f}", "value_per_converter": "${:.2f}",
        "extrapolated_share": "{:.0%}", "first_payment_share": "{:.0%}", "revenue_per_install": "${:.2f}",
        "weekly_installs": "{:,.0f}"}), width="stretch", hide_index=True)
    st.caption("observed_net_per_payer = cash received so far (DATA). value_per_converter = expected over the horizon "
               "(DATA renewal curves + extrapolated tail). revenue_per_install is before store fee.")

    if horizon == 12:
        st.warning("12-month horizon: the data covers only ~17 weeks. Weekly and monthly revenue past the observed periods "
                   "is extrapolated, and annual renewals can't be observed at all (annual plans count as one payment).")
    l, r = st.columns(2)
    l.plotly_chart(charts.survival_curves(survivals), width="stretch")
    l.caption("Kaplan–Meier on paid receipts, one payment chain per payer. A chain whose current period hadn't ended "
              f"by the cutoff is censored (outcome unknown), even if auto-renew was switched off. A step counts as "
              f"observed if ≥ {MIN_AT_RISK} chains had a known outcome. Lifetime purchases are excluded.")
    surv_rows = []
    for p in SUBSCRIPTION_PRODUCTS:
        s = survivals[p]
        surv_rows.append({"Plan": p, "Payments in horizon": periods_in_horizon(p, horizon),
                          "Observed steps": s.observed_periods, "2nd payment": s.s[1] if len(s.s) > 1 else np.nan,
                          "Tail retention/period": s.tail_retention if s.extrapolated else np.nan,
                          "Expected payments": s.s.sum(), "Refund rate": rr.get(p, np.nan)})
    r.dataframe(pd.DataFrame(surv_rows).style.format({"2nd payment": "{:.1%}", "Tail retention/period": "{:.1%}",
                                                      "Expected payments": "{:.2f}", "Refund rate": "{:.1%}"},
                                                     na_rep="—"), hide_index=True, width="stretch")
    r.markdown(f"**Plan mix of payers: {audience}**")
    r.dataframe(base.product_mix.rename("share of payers").to_frame().style.format("{:.0%}"), width="stretch")

# ================================================================ data reality check
with tab_data:
    st.subheader("What this dataset can and can't tell us")
    chains_per_user = ds.tx.groupby("user_id")["originally_purchased_at"].nunique().max()
    refunded = ds.tx[ds.tx.is_refunded]
    last_seq = ds.tx.groupby("user_id")["seq"].max()
    trial_len = ((ds.tx.loc[~ds.tx.is_paid, "expires_at"] - ds.tx.loc[~ds.tx.is_paid, "purchased_at"])
                 .dt.total_seconds() / 86400).round(1).unique()
    st.markdown(f"""
| | |
|---|---|
| Source | **Synthetic.** Fictional app *Lumen*, generated by the hackathon organisers (generator not included). No real customers. |
| Size | {len(U):,} installs · {len(ds.tx):,} receipts · {len(ds.chains):,} payers · installs {U.install_at.min():%d %b} – {U.install_at.max():%d %b %Y} |
| Observation cutoff | **{ds.as_of:%d %b %Y %H:%M} UTC**: the latest *observed event* (install, purchase, renewal-status change, billing issue, refund). `expires_at` is a scheduled date (up to {ds.tx.expires_at.max():%b %Y}) and is never used as a cutoff. |
| Payment chains | at most **{chains_per_user}** chain per user; receipts contiguous (`seq` 0, 1, 2…); no re-subscriptions |
| Trials | price $0, always `seq` 0, lengths {", ".join(f"{x:g}" for x in sorted(trial_len))} days; not counted as payments |
| Time to first paid receipt | max {U.days_to_first_paid.max():.1f} days → {CONVERSION_WINDOW_DAYS}-day conversion window |
| Refunds | {len(refunded):,} receipts; {(refunded.seq.values == last_seq.reindex(refunded.user_id).values).mean():.0%} are the user's last receipt |
| ✅ Contained | prices (one per product × country), conversion, trials, renewals, cancellations, refunds, billing issues, placement, flow, A/B arm, user attributes |
| ❌ **No discount exposure** | `offer` is only `free_trial` or empty: no promo, intro price or randomised price test |
| ❌ No within-market price variation | price sensitivity is **not identifiable** |
| ❌ Annual renewals, long-run retention | the window is ~17 weeks |
| ❌ Costs | no acquisition or compute costs, so this is revenue, not profit |
""")
    l, r = st.columns([3, 2])
    l.plotly_chart(charts.price_vs_conversion(country_price_vs_conversion(ds)), width="stretch")
    r.markdown("""
**Why this chart is not a discount-response estimate**

Cheaper countries convert *less*. A naive regression would conclude that raising prices *increases* conversion.

Country drives both the price tier and people's willingness and ability to pay. That's **confounding**, so the slope
says nothing about what a discount would do. There's no randomised price or discount exposure in the data, so
the customer response is an explicit **ASSUMPTION**, and the tool designs the experiment that would measure it.
""")

# ================================================================ method
with tab_method:
    st.markdown(rf"""
### Definitions
- **Eligible install:** an install in the selected placement (and segment). Each install saw exactly one placement.
- **Mature install:** installed at least {CONVERSION_WINDOW_DAYS} days before the cutoff, so it has had the full
  conversion window. Recent installs (still in a trial) are excluded from the conversion denominator, not counted as non-payers.
- **Payer / conversion:** first **paid** receipt (price > 0) within {CONVERSION_WINDOW_DAYS} days of install. A later refund
  doesn't undo the conversion; the refunded receipt counts $0.
- **Payment chain:** user_id + `originally_purchased_at` (one per payer in this data). Lifetime purchases are payers but
  have no renewals.

### Revenue per payer V₀
For each payer: (first paid price) × (1 − refund rate of that plan) × (expected number of payments in the horizon).
Expected payments come from a discrete **Kaplan–Meier** curve over paid receipts:
- **Censoring rule:** a chain whose current paid period hadn't ended by the cutoff and wasn't refunded is censored at
  that step (its renewal is unknown). This includes users who switched auto-renew off; counting them as churned would
  bias renewal downwards. A refund ends the entitlement on an observed date, so it counts as an event.
- A step counts as **observed** if at least {MIN_AT_RISK} chains had a known outcome. Beyond that, the **tail rule**
  repeats the mean of the last {TAIL_RATES} observed renewal rates. Its share of V₀ is reported as *extrapolated*.
- Payments occur on days 0, P, 2P… with P = 7 / 30 / 365 days (as observed). The horizon counts payments on days < 3, 6 or
  12 × 365/12 days, so annual plans have exactly one payment in every horizon.
- V₀ is before store fee. The fee is applied identically to baseline and discounted revenue, so it doesn't change
  break-even.

### Discount economics · CALCULATED
$V_d = V_0\,[(1-d)\,a + (1-a)(1-k\,d)]$ · $R(d) = (c_0 V_d + (c(d)-c_0)\,\rho\,V_d)(1-\text{{fee}})$ ·
**break-even lift** $L^*(d) = (V_0/V_d - 1)/\rho$.

$a$ = share of V₀ paid during the discounted periods, from the audience's plan mix and renewal curves.
Simplifications: the plan mix doesn't change with the discount; step-up churn is linear in $d$; incremental buyers
differ only through $\rho$.

### Response curve · ASSUMED
A share $M = \min(1, q\,c_0)$ of users is in-market. Their willingness to pay is **lognormal** (a modelling choice,
not identified by the data), located so that today's conversion is $c_0$. Its spread comes from $L_{{20}}$. Hence any
lift must be **< M/c₀ − 1**. Infeasible inputs are rejected with a warning, never clipped. $L_{{20}}$ is drawn
4,000 times from a triangular distribution. Optionally $c_0$ (Jeffreys Beta posterior) and $V_0$ (normal, standard
error across payers) are drawn too. The band is labelled with exactly what it includes.

### Recommendation
*Worth testing* = beats full price in ≥ the chosen share of scenarios **and** the break-even lift can be detected
within the time limit. *Not plausible* = fails the first. *Too slow to test* = fails the second. Among *worth testing*,
the discount with the highest expected revenue under the assumptions is proposed, with a decision rule fixed before
launch. Nothing here is a causal estimate.

### Sample size
Two-sided two-proportion z-test, pooled variance under H₀, no continuity correction, α = 0.05 (Bonferroni-split for
several arms), power 80%, at the break-even effect. Duration = n ÷ (weekly traffic × allocation ÷ groups) +
{CONVERSION_WINDOW_DAYS}-day outcome wait.

### Limits
Synthetic data · response assumed, the same for every segment · ~17 weeks of history (annual renewals unobservable;
long horizons partly extrapolated) · revenue, not profit · traffic is a sample.
""")
