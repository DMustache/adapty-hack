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

## Modules

| File | Role |
|---|---|
| `data.py` | Loads the CSVs; observation cutoff; conversion window and maturity; payment chains; censoring; net receipts |
| `metrics.py` | **DATA**: conversion + Wilson CI, Kaplan–Meier renewals with censoring, refunds, revenue per payer split into observed / estimated / extrapolated, discount-touched share, traffic |
| `economics.py` | **CALCULATED** break-even and test sizing; **ASSUMED** response curve with feasibility checks; Monte Carlo; sensitivity; experiment plan |
| `charts.py` | Plotly figures |
| `app.py` | Streamlit UI: Recommendation · Sensitivity · Compare segments · Baselines · Data reality check · Method |
| `tests/` | data integrity, censoring, maturity, refunds, chains, segment totals, formulas, feasibility, sample sizes, durations, end-to-end UI |
