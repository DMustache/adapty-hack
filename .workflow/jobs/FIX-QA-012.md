---
id: FIX-QA-012
milestone: M7
role: qa
priority: P1
status: DONE
depends_on: [FIX-AN-002]
owned_paths:
  - tests/test_m7_candidate_bridge.py
---
# Check OpenAPI documents the candidate response

Failure: the M7 endpoint's OpenAPI 200 response schema is `{}`. Expected: the schema references `RetentionAtRiskResponse`; its required fields include candidate provenance and planner inputs. The live HTTP response validates against the frozen response schema. Add a regression check and rerun the exact-SHA M7 gate. Parent milestone M7.
