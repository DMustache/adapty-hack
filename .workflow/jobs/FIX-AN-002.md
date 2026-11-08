---
id: FIX-AN-002
milestone: M7
role: analytics
priority: P1
status: READY
depends_on: [M7-AN-001]
owned_paths:
  - services/analytics/app/main.py
---
# Publish the frozen M7 response shape in OpenAPI

Failure: `GET /v1/retention/at-risk` works, but its OpenAPI 200 response schema is `{}`. `openapi-spec-validator` accepts the document, yet clients cannot derive the candidate structure. Expected: FastAPI uses frozen `RetentionAtRiskResponse` as `response_model`, the live endpoint still answers correctly, and the generated 200 schema references the response model. Parent milestone M7. Lead will refresh the OpenAPI snapshot after integration.
