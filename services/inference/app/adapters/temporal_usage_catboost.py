"""Adapter for the OPTIONAL churn model with app-usage features (ml/temporal_churn/train_usage.py).

Loaded next to the deployed 23-feature model (temporal_catboost.py), never instead of it: requests choose it with
model_id "lumen-temporal-usage-catboost". The artifact must
  * have a model.cbm whose SHA-256 equals both model.cbm.sha256 and metadata.json,
  * list exactly the deployed model's 23 features, in the same order, followed by the usage features,
  * mark every usage feature optional: a request may omit them or send null (= no usage history), which is what
    the model saw in training for subscribers without usage data.
No training here; the artifact is CatBoost's own .cbm format, never pickle.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from services.inference.app.adapters.temporal_catboost import (
    DEFAULT_DIR as BASELINE_DIR,
)
from services.inference.app.adapters.temporal_catboost import (
    ArtifactIntegrityError,
    TemporalCatBoostAdapter,
)

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "models" / "temporal_usage_catboost"
MODEL_ID = "lumen-temporal-usage-catboost"


class TemporalUsageCatBoostAdapter(TemporalCatBoostAdapter):
    source = "external"

    def __init__(self, model_dir: str | Path | None = None, baseline_dir: str | Path | None = None):
        self.model_dir = Path(model_dir or os.getenv("TEMPORAL_USAGE_MODEL_DIR") or DEFAULT_DIR)
        meta = json.loads((self.model_dir / "metadata.json").read_text(encoding="utf-8"))
        base = json.loads((Path(baseline_dir or os.getenv("TEMPORAL_CHURN_MODEL_DIR") or BASELINE_DIR)
                           / "metadata.json").read_text(encoding="utf-8"))
        self.metadata = meta
        self.model_id = meta["model_id"]
        self.model_version = meta["model_version"]
        self.features: list[str] = meta["features"]
        self.categorical = set(meta["categorical_features"])
        self.boolean = set(meta["boolean_features"])
        self.optional = list(meta.get("optional_features", []))
        self._model = None
        if self.model_id != MODEL_ID:
            raise ArtifactIntegrityError(f"usage model id must be {MODEL_ID}")
        n = len(base["features"])
        if self.features[:n] != base["features"]:
            raise ArtifactIntegrityError("usage model must start with the deployed model's features, in order")
        if not self.optional or self.features[n:] != self.optional or len(set(self.features)) != len(self.features):
            raise ArtifactIntegrityError("usage features must follow the baseline features and all be optional")
        schema = meta["input_schema"]
        if list(schema["required"]) != base["features"]:
            raise ArtifactIntegrityError("only the baseline features may be required")
        if any("null" not in schema["properties"][f]["type"] for f in self.optional):
            raise ArtifactIntegrityError("usage features must accept null")

    def load(self) -> None:
        path = self.model_dir / "model.cbm"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        recorded = (self.model_dir / "model.cbm.sha256").read_text(encoding="utf-8").split()[0]
        if digest != recorded or digest != self.metadata["sha256"]:
            raise ArtifactIntegrityError(f"{path}: checksum mismatch")
        from catboost import CatBoostClassifier
        model = CatBoostClassifier()
        model.load_model(str(path), format="cbm")
        self._model = model
        self._cat_idx = [i for i, f in enumerate(self.features) if f in self.categorical]
