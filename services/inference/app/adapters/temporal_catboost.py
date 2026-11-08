"""Adapter for the researcher-supplied temporal churn model (CatBoost, see ml/temporal_churn/).

No training here: the service loads a checksummed artifact (CatBoost's own .cbm format, never pickle) and scores
one point-in-time snapshot. The artifact directory holds model.cbm, model.cbm.sha256 and metadata.json
(feature order, categorical/boolean features, input JSON schema, metrics, provenance).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "models" / "temporal_catboost"


class ArtifactIntegrityError(RuntimeError):
    pass


class TemporalCatBoostAdapter:
    source = "external"

    def __init__(self, model_dir: str | Path | None = None):
        self.model_dir = Path(model_dir or os.getenv("TEMPORAL_CHURN_MODEL_DIR") or DEFAULT_DIR)
        meta = json.loads((self.model_dir / "metadata.json").read_text(encoding="utf-8"))
        self.metadata = meta
        self.model_id = meta["model_id"]
        self.model_version = meta["model_version"]
        self.features: list[str] = meta["features"]
        self.categorical = set(meta["categorical_features"])
        self.boolean = set(meta["boolean_features"])
        self._model = None

    def load(self) -> None:
        path = self.model_dir / "model.cbm"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        recorded = (self.model_dir / "model.cbm.sha256").read_text(encoding="utf-8").split()[0]
        if digest != recorded or digest != self.metadata["sha256"]:
            raise ArtifactIntegrityError(f"{path}: checksum mismatch")
        from catboost import CatBoostClassifier  # imported lazily: only needed when this model is installed
        model = CatBoostClassifier()
        model.load_model(str(path), format="cbm")
        self._model = model
        self._cat_idx = [i for i, f in enumerate(self.features) if f in self.categorical]

    def get_input_schema(self) -> dict[str, Any]:
        return self.metadata["input_schema"]

    def _row(self, features: dict[str, Any]) -> list:
        row = []
        for f in self.features:
            v = features.get(f)
            if f in self.categorical:
                row.append("nan" if v is None else str(v))      # training encoded missing categories as "nan"
            elif f in self.boolean:
                row.append(1.0 if v else 0.0)
            else:
                row.append(float("nan") if v is None else float(v))
        return row

    def predict(self, user_id: str, features: dict[str, Any], context: dict[str, Any]) -> float:
        return self.predict_batch([features])[0]

    def predict_batch(self, rows: list[dict[str, Any]]) -> list[float]:
        if self._model is None:
            raise RuntimeError("load() must be called before predict()")
        from catboost import Pool
        pool = Pool([self._row(r) for r in rows], cat_features=self._cat_idx, feature_names=self.features)
        out = [float(p[1]) for p in self._model.predict_proba(pool)]
        if not all(math.isfinite(p) and 0.0 <= p <= 1.0 for p in out):
            raise ValueError("model produced an invalid probability")
        return out
