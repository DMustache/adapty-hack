import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data import default_data_dir, load  # noqa: E402
from metrics import product_values  # noqa: E402


@pytest.fixture(scope="session")
def ds():
    return load()


@pytest.fixture(scope="session")
def survivals(ds):
    return product_values(ds, 12)


@pytest.fixture(scope="session")
def raw():
    d = default_data_dir()  # same lookup as the app: $DISCOUNT_DATA_DIR, then local fallbacks
    return pd.read_csv(d / "users.csv.gz"), pd.read_csv(d / "transactions.csv.gz")
