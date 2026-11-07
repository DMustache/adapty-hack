---
id: FIX-BE-001
milestone: M0
role: backend
status: READY
depends_on: []
owned_paths:
  - scripts/smoke_demo.py
---
# FIX-BE-001: Retry transient startup connection resets

## Failure
`PATH=.worktrees/develop/.venv/bin:$PATH bash scripts/gate.sh M0` failed at the first HTTP health request with `ConnectionResetError: [Errno 104] Connection reset by peer` while Compose had just started the containers. Expected: the existing bounded startup retry should continue until the service is ready. Actual: it catches `URLError` and `AssertionError` but not this socket error. Log: `.worktrees/develop/.agent-runtime/gates/M0.log` at commit `ec8e653`.

## Work
Harden only the startup readiness retry in `scripts/smoke_demo.py` to handle transient connection resets without hiding later application errors. Keep the finite timeout and the rest of the smoke assertions. Add no ML behavior.

## Acceptance and handoff
The smoke script tolerates a transient reset during health readiness, still fails after bounded retries if unavailable, and preserves non-readiness HTTP failures. Run a targeted check. Commit on the fix branch and write `handoffs/FIX-BE-001.md` with commit SHA, tests, and any blocker.
