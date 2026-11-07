"""Static fixtures: no ML, risk heuristic, or inferred churn labels."""
from typing import Any


class MockChurnAdapter:
    model_id = "mock-churn-v1"
    model_version = "0.0.0-mock"
    source = "mock"
    # Fixture lookup is deliberate: returning fixed values is not a churn algorithm.
    FIXTURES = {
        "demo-u01": 0.80, "demo-u02": 0.45, "demo-u03": 0.25,
        "demo-u04": 0.70, "demo-u05": 0.35, "demo-u06": 0.60,
        "demo-u07": 0.20, "demo-u08": 0.50, "demo-u09": 0.75,
        "demo-u10": 0.40, "demo-u11": 0.30, "demo-u12": 0.65,
    }

    def load(self) -> None:
        pass

    def get_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": True}

    def predict(self, user_id: str, features: dict[str, Any], context: dict[str, Any]) -> float:
        return self.FIXTURES.get(user_id, 0.50)
