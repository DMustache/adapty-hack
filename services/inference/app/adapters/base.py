"""Integration boundary only: ML research, training and labeling live outside this repo."""
from typing import Any, Protocol


class ModelAdapter(Protocol):
    model_id: str
    model_version: str
    source: str

    def load(self) -> None: ...
    def get_input_schema(self) -> dict[str, Any]: ...
    def predict(self, user_id: str, features: dict[str, Any], context: dict[str, Any]) -> float: ...
