# FIX-QA-008 handoff

The M5 offline checkpoint now runs `scripts/check_behavior_segments.py` after importing the ignored synthetic seed. It reads the provisioned dashboard SQL, interpolates the selected variables and shared UTC range, and executes the six panels through the Compose PostgreSQL service. Expected group membership comes independently from `users.csv.gz`; no user IDs are printed.

Local run against the imported seed passed: All 50,000/50,000 with 50,000 overlap; iOS/Android 28,895/21,105 with zero overlap; no-test 14,739; empty group zero with NULL behavior averages/share; iOS/US overlap 10,017. Every breakdown's group counts and group-size column agreed with the source cohort.
