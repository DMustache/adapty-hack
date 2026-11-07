import csv
import json
from services.inference.app.economics import make_plan
from shared.contracts.models import RetentionPlanRequest
from scripts.export_experiment_assignments import export_plan


def test_csv_export_preserves_control_and_plan(tmp_path):
    req=RetentionPlanRequest(app_id="app",experiment_id="exp",budget_usd=5,control_share=0.5,
        candidates=[
            {"user_id":"u1","churn_probability":0.6,"renewal_price_usd":4.99,"plan_type":"weekly"},
            {"user_id":"u2","churn_probability":0.7,"renewal_price_usd":9.99,"plan_type":"monthly"},
        ])
    plan=make_plan(req)
    inp=tmp_path/"plan.json";out=tmp_path/"arms.csv"
    inp.write_text(json.dumps(plan.model_dump(mode="json")))
    assert export_plan(inp,out)==2
    with out.open(newline="") as f:rows=list(csv.DictReader(f))
    assert {r["plan_type"] for r in rows}=={"weekly","monthly"}
    assert "control" in {r["arm"] for r in rows}
