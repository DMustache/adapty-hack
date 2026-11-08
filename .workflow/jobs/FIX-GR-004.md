# FIX-GR-004: show risk changes and correct demo units

- ID: FIX-GR-004
- Milestone: M8 follow-up
- Develop commit SHA: `92c1323d2f079786640013d700429519ee3da108`
- Gate command: `bash scripts/gate.sh M8`
- Expected behavior: Grafana shows the signed risk change in the staged M8 demo; subscriber counts use count units and revenue uses USD units.
- Actual behavior: panel 7 filters `churn_probability_change > 0`, while the staged subscriber's second risk is lower, so the panel stays empty. Mixed units obscure the count and revenue values.
- Log/error excerpt: the dashboard SQL contains `churn_probability_change > 0`; the M8 fixture's repeated subscriber has a negative change.
- Owner role: Grafana
- Minimal reproduction: `python scripts/m8_live_demo.py --pause`, then inspect panel 7 after stage 2 and panel units after stage 3.
- Regression test: dashboard JSON and Grafana query checks; M8 exact-SHA gate.
- Acceptance criteria: show signed nonzero changes ordered by magnitude, preserve source/time filters and read-only SQL, format subscriber counts and USD revenue correctly, update the presenter documentation.
