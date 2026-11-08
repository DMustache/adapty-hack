---
id: FIX-QA-011
milestone: M7
role: qa
priority: P1
status: DONE
depends_on: [M7-AN-001]
owned_paths:
  - tests/test_temporal_storage.py
---
# Update temporal storage fake for optional plan type

Failure: `bash scripts/gate.sh M7` at develop `a9bd305`: `tests/test_temporal_storage.py::test_temporal_snapshot_retry_is_immutable` raises `IndexError: tuple index out of range` in Analytics duplicate check. The test FakeDB returns 11 stored fields while the M7 contract and implementation now read 12. Expected: old payload retry remains idempotent, changed `plan_type` conflicts. Update the fake projection and add the plan conflict case. Parent milestone M7. Rerun this test and exact-SHA M7 gate.
