"""Seed a NEW Adapty app with the full 50,000-user offline population, using the unmodified hackathon seeder.

Phase 1 creates the app "Lumen 50k - AI Photo Editor (Hackathon)" and its catalog (seeder --skip-data).
Phase 2 replays users and purchases into it (seeder --app-id ... --skip-config) with the app's secret key read from
the logged-in CLI (never printed or stored).

MTR: the seeder dates all history, and the "installed today" users, BEFORE the app's first profile, which is when
Adapty marks the SDK as installed, so none of it counts toward the account's monthly tracked revenue.

Build the dataset first:  python build_seed_dataset.py
Usage:                    python seed_50k.py [--users N] [--workers 8] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "adapty-seed-data-hack"))
sys.path.insert(0, str(HERE))

import seed_adapty as seed  # noqa: E402

from adapty_live import secret_key  # noqa: E402
from build_seed_dataset import DEFAULT_OUT  # noqa: E402

TITLE = "Lumen 50k - AI Photo Editor (Hackathon)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not DEFAULT_OUT.exists():
        sys.exit(f"{DEFAULT_OUT} missing: run build_seed_dataset.py first")
    seed.DATASET = DEFAULT_OUT
    seed.APP_TITLE = TITLE
    # No "installed today" users: at 50k they would carry ~$18k of purchases dated today. The seeder keeps them
    # outside MTR by timing alone; dropping them leaves only history dated before the app existed.
    seed.LIVE_EVERY = (5, 0)
    seed.LIVE_MIN_WINDOW = 0
    extra = (["--users", str(args.users)] if args.users else []) + ["--workers", str(args.workers)]

    if args.dry_run:
        sys.argv = ["seed_adapty.py", "--dry-run", *extra]
        seed.main()
        return

    cli = seed.Cli(False)
    apps = cli.list_all("apps", "list")
    app = seed.by_field(apps, "title", TITLE)
    if app is None:
        sys.argv = ["seed_adapty.py", "--skip-data"]
        seed.main()
        app = seed.by_field(cli.list_all("apps", "list"), "title", TITLE)
    app_id = seed._id(app)
    seed.log(f"\nApp {TITLE}: {app_id}")
    os.environ["ADAPTY_SECRET_KEY"] = secret_key(app_id)
    try:
        sys.argv = ["seed_adapty.py", "--app-id", app_id, "--skip-config", *extra]
        seed.main()
    finally:
        os.environ.pop("ADAPTY_SECRET_KEY", None)


if __name__ == "__main__":
    try:
        main()
    except seed.CliError as e:
        seed.die(f"{e}\nRe-run: what was already created is reused.")
