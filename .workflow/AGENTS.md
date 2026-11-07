# Lead-only planning scope

Only Lead edits files under `.workflow/`. Read `.workflow/roles/lead.md`, then the active milestone and relevant jobs. Commit job files on `main` and sync them to `develop` **before** spawning worker worktrees. Report failures as new FIX jobs; never silently mutate active tasks.
