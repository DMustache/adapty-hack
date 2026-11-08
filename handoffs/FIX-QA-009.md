# FIX-QA-009 handoff

The offline comparison check now rejects Grafana's unescaped custom All mechanism and requires All to be a regular query option for every Group A/B control. It also checks the reported `onb_trial` versus `onb_weekly` selection while other controls remain All. Run after integrating FIX-GR-002 with the local seed archive through `OFFLINE_DATA_DIR`.
