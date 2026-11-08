"""Stable API boundaries. A separate researcher owns churn probabilities."""
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


def _check_temporal(as_of_at: datetime | None, renewal_due_at: datetime | None) -> None:
    for name, value in (("as_of_at", as_of_at), ("renewal_due_at", renewal_due_at)):
        if value is not None and value.tzinfo is None:
            raise ValueError(f"{name} must include a timezone (UTC)")
    if as_of_at is not None and renewal_due_at is not None and renewal_due_at < as_of_at:
        raise ValueError("renewal_due_at must not be before as_of_at")


class ChurnPredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    renewal_horizon_days: int = Field(ge=1, le=365)
    context: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    # Temporal fields (optional; omitted by older clients). as_of_at = the instant the features describe;
    # renewal_due_at = the next eligible renewal event; renewal_price_usd = its full price (for revenue at risk).
    as_of_at: datetime | None = None
    renewal_due_at: datetime | None = None
    renewal_price_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    plan_type: Literal["weekly", "monthly"] | None = None

    @model_validator(mode="after")
    def validate_temporal(self):
        _check_temporal(self.as_of_at, self.renewal_due_at)
        return self


class ChurnPredictionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    prediction_id: str
    request_id: str
    app_id: str
    user_id: str
    model_id: str
    model_version: str
    prediction_source: Literal["mock", "external"]
    predicted_at: datetime
    renewal_horizon_days: int
    churn_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    as_of_at: datetime | None = None
    renewal_due_at: datetime | None = None
    renewal_price_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    plan_type: Literal["weekly", "monthly"] | None = None

    @model_validator(mode="after")
    def validate_temporal(self):
        _check_temporal(self.as_of_at, self.renewal_due_at)
        return self


class RetentionAtRiskCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscribers_with_predictions: int = Field(ge=0)
    renewal_already_due: int = Field(ge=0)
    stale: int = Field(ge=0)
    missing_plan_type: int = Field(ge=0)
    eligible: int = Field(ge=0)
    returned: int = Field(ge=0)


class RetentionAtRiskCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prediction_id: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    prediction_source: Literal["mock", "external"]
    plan_type: Literal["weekly", "monthly"]
    predicted_at: datetime
    as_of_at: datetime
    renewal_due_at: datetime
    churn_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    renewal_price_usd: float = Field(gt=0, allow_inf_nan=False)


class RetentionAtRiskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    reference_time: datetime | None
    max_age_days: float = Field(gt=0, le=365)
    counts: RetentionAtRiskCounts
    subscribers: list[RetentionAtRiskCandidate]


class RetentionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1)
    churn_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    renewal_price_usd: float = Field(gt=0, allow_inf_nan=False)
    plan_type: Literal["weekly", "monthly"]


class RetentionPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    app_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    budget_usd: float = Field(ge=0, allow_inf_nan=False)
    control_share: float = Field(default=0.2, ge=0, lt=1)
    discounts: list[float] = Field(default_factory=lambda: [0.1, 0.2, 0.3], min_length=1)
    random_seed: int = 42
    candidates: list[RetentionCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_experiment(self):
        if len(set(c.user_id for c in self.candidates)) != len(self.candidates):
            raise ValueError("candidates must have unique user_id values")
        if len(set(self.discounts)) != len(self.discounts):
            raise ValueError("discounts must be unique")
        if any(not 0 < d < 1 for d in self.discounts):
            raise ValueError("discounts must be fractions strictly between 0 and 1")
        return self


class BreakEvenResult(BaseModel):
    baseline_renewal_probability: float
    discount_fraction: float
    min_post_offer_renewal_probability: float
    required_absolute_uplift: float
    feasible_in_principle: bool


class ExperimentAssignment(BaseModel):
    user_id: str
    plan_type: Literal["weekly", "monthly"]
    arm: str
    discount_fraction: float
    max_discount_exposure_usd: float
    renewal_price_usd: float
    expected_revenue_at_risk_usd: float
    baseline_renewal_probability: float
    min_post_offer_renewal_probability: float | None = None
    required_absolute_uplift: float | None = None


class RetentionPlanResult(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    experiment_id: str
    app_id: str
    request_fingerprint: str = Field(min_length=64, max_length=64)
    created_at: datetime
    plan_source: Literal["scenario_experiment"] = "scenario_experiment"
    modeled_discount_uplift: bool = False
    budget_usd: float
    max_allocated_discount_exposure_usd: float
    expected_baseline_revenue_at_risk_usd: float
    unallocated_budget_usd: float
    assignments: list[ExperimentAssignment]
    disclaimer: str


class ActualObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    metric_value: float = Field(allow_inf_nan=False)
    observed_at: datetime
    dimensions: dict[str, str] = Field(default_factory=dict)
    source: Literal["demo", "external"] = "demo"
