# Discount Advisor (Adapty Hackathon)

A Streamlit decision-support tool that answers:

> **Should we test a discount for this subscription audience, and if so, which discount is worth testing?**

The dataset is **synthetic** (the hackathon's fictional *Lumen* app) and contains **no discount exposure**. So the tool
does not learn a discount response. It **measures** baselines, **calculates** exact break-even arithmetic, treats
customer response as an explicit **assumption**, and recommends an **experiment**, never a proven "best" discount.
See [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) for the full explanation.

## Run

```bash
# from the folder that contains discount_advisor/ (and the data, see below)
python -m venv .venv && .venv\Scripts\activate          # or: source .venv/bin/activate
pip install -r discount_advisor/requirements.txt
cd discount_advisor
streamlit run app.py                                    # http://localhost:8501
```

**Data location.** The loader uses the first of these that contains `users.csv.gz` and `transactions.csv.gz`:
1. `$DISCOUNT_DATA_DIR`
2. `discount_advisor/source/data/offline/`
3. `source/data/offline/` next to `discount_advisor/`
4. `adapty-seed-data-hack/data/offline/` next to `discount_advisor/` (the hackathon repo clone; used in this workspace)

## Tests

```bash
pip install pytest hypothesis
python -m pytest tests -q          # ~5 min; tests/test_app.py drives the real app headlessly
python -m pytest tests -q --ignore tests/test_app.py   # ~20 s, core maths and data only
```

### Live Adapty checks (optional, read-only)

`tests/test_live_adapty.py` compares every seeded profile in a live Adapty app with the offline CSVs (presence, attributes,
store, products, cancellation reasons, trial offers, expiry incl. refund rule, revenue net of refunds incl. FX, today's
users). It is skipped unless `ADAPTY_LIVE=1`; profiles are cached in `.live_cache/` (`ADAPTY_LIVE_REFRESH=1` re-downloads).
The secret key comes from `$ADAPTY_SECRET_KEY` or the logged-in Adapty CLI and is never stored.

```bash
ADAPTY_LIVE=1 python -m pytest tests/test_live_adapty.py -q                       # 5k app (defaults)
ADAPTY_LIVE=1 ADAPTY_APP_ID=92ceed1c-9d18-4610-89fa-e94374cfe3a5 ADAPTY_RUN_ID=247954 \
  ADAPTY_N_USERS=50000 ADAPTY_LIVE_EVERY=0 python -m pytest tests/test_live_adapty.py -q   # 50k app
```

Related scripts: `adapty_live.py` (download profiles), `build_seed_dataset.py` (50k CSVs → seeder format; `--verify`
reproduces the shipped 5k file exactly), `seed_50k.py` (seed a new app with 50k users, no same-day purchases),
`adapty_experiment.py` (discount A/B test with simulated users; adds tracked revenue, see its docstring).

## Modules

| File | Role |
|---|---|
| `data.py` | Loads the CSVs; observation cutoff; conversion window and maturity; payment chains; censoring; net receipts |
| `metrics.py` | **DATA**: conversion + Wilson CI, Kaplan–Meier renewals with censoring, refunds, revenue per payer split into observed / estimated / extrapolated, discount-touched share, traffic |
| `economics.py` | **CALCULATED** break-even and test sizing; **ASSUMED** response curve with feasibility checks; Monte Carlo; sensitivity; experiment plan |
| `charts.py` | Plotly figures |
| `app.py` | Streamlit UI: Recommendation · Sensitivity · Compare segments · Baselines · Data reality check · Live Adapty · Method |
| `tests/` | data integrity, censoring, maturity, refunds, chains, segment totals, formulas, feasibility, sample sizes, durations, end-to-end UI |
