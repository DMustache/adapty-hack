import csv
import gzip
from scripts.inspect_seed_data import report


def test_inspector_validates_synthetic_gzip_shape(tmp_path):
    for name, rows in (
        ("users.csv.gz",[{"user_id":"u1","country":"US"},{"user_id":"u2","country":"DE"}]),
        ("transactions.csv.gz",[{"user_id":"u1","price_usd":"4.99"}]),
    ):
        with gzip.open(tmp_path/name,"wt",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=rows[0].keys())
            writer.writeheader();writer.writerows(rows)
    result=report(tmp_path)
    assert result["files"]["users.csv.gz"]["rows"]==2
    assert result["files"]["transactions.csv.gz"]["rows"]==1
    assert result["dataset_type"]=="synthetic"
    assert "no observed response to discounts" in result["caution"].lower()
