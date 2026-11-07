# Synthetic demo fixtures

`MockChurnAdapter` has 12 fixed, declared churn probabilities keyed by `demo-u01` through `demo-u12`. The model is deliberately NOT trained. `scripts/smoke_demo.py` sends these fixtures to the two-service HTTP path and creates a budget-bounded scenario experiment. For real data, fetch the separate synthetic Adapty repo; its gzip CSVs are not distributed here. Never label a discount-offer outcome as observed from seed data.
