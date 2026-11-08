"""Read-only access to the live (seeded) Adapty app, used to verify it against the offline dataset.

The seeder replays offline user u{i:05d} as customer user id lumen_<run>_{i:05d}, and every fifth user again as
lumen_<run>_L{i:05d} ("installed today"). Timestamps are shifted by one constant so the history ends on the seeding day.

Secret key: $ADAPTY_SECRET_KEY, else fetched from the logged-in Adapty CLI (`adapty apps get <id> --json`).
The key is never written to disk or printed. Profiles are cached to .live_cache/ so tests can re-run offline.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api.adapty.io/api/v2/server-side-api/profile/"
APP_ID = os.environ.get("ADAPTY_APP_ID", "cc1f40d1-26c1-4f9d-8341-ba719971ac32")
RUN_ID = os.environ.get("ADAPTY_RUN_ID", "261329")
N_USERS = int(os.environ.get("ADAPTY_N_USERS", "5000"))      # historical users replayed
LIVE_EVERY = int(os.environ.get("ADAPTY_LIVE_EVERY", "5"))   # 0 = no "installed today" copies
CACHE_DIR = Path(__file__).resolve().parent / ".live_cache"


def _cli_base() -> list[str]:
    exe = shutil.which("adapty")
    if exe:
        return [exe]
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    run_js = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "adapty" / "bin" / "run.js"
    if Path(node).exists() and run_js.exists():
        return [node, str(run_js)]
    raise RuntimeError("Adapty CLI not found; set ADAPTY_SECRET_KEY instead.")


def secret_key(app_id: str = APP_ID) -> str:
    key = os.environ.get("ADAPTY_SECRET_KEY", "").strip()
    if key:
        return key
    out = subprocess.run(_cli_base() + ["apps", "get", app_id, "--json"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("`adapty apps get` failed (logged in? run `adapty auth login`)")
    key = json.loads(out.stdout).get("secret_key", "")
    if not key:
        raise RuntimeError("No secret key returned for app " + app_id)
    return key


def customer_ids(run_id: str = RUN_ID, n_users: int = N_USERS, live_every: int = LIVE_EVERY) -> list[str]:
    hist = [f"lumen_{run_id}_{i:05d}" for i in range(n_users)]
    live = [f"lumen_{run_id}_L{i:05d}" for i in range(0, n_users, live_every)] if live_every else []
    return hist + live


def fetch_profile(key: str, cuid: str, retries: int = 6) -> dict | None:
    req = urllib.request.Request(API, headers={"Authorization": f"Api-Key {key}", "adapty-customer-user-id": cuid})
    delay = 1.0
    for _ in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r).get("data")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"giving up on {cuid}")


def fetch_all(cuids: list[str], key: str | None = None, workers: int = 8, progress=None) -> dict[str, dict | None]:
    key = key or secret_key()
    out: dict[str, dict | None] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (c, p) in enumerate(zip(cuids, pool.map(lambda c: fetch_profile(key, c), cuids)), 1):
            out[c] = p
            if progress and i % 500 == 0:
                progress(i, len(cuids))
    return out


def snapshot(run_id: str = RUN_ID, refresh: bool = False, progress=None) -> dict[str, dict | None]:
    """All seeded profiles, from the local cache unless refresh=True or no cache exists."""
    path = CACHE_DIR / f"profiles_{run_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch_all(customer_ids(run_id), key=secret_key(APP_ID), progress=progress)
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def snapshot_ids(ids: list[str], name: str, refresh: bool = False) -> dict[str, dict | None]:
    """Like snapshot(), for an explicit list of customer user ids (e.g. the simulated discount-test users)."""
    path = CACHE_DIR / f"{name}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch_all(ids, key=secret_key(APP_ID))
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


EXPERIMENT_RUN_ID = "700001"
EXPERIMENT_USERS = 150


def experiment_ids(run_id: str = EXPERIMENT_RUN_ID, n: int = EXPERIMENT_USERS) -> list[str]:
    return [f"lumen_{run_id}_D{k:04d}" for k in range(n)]


if __name__ == "__main__":
    t = time.time()
    snap = snapshot(refresh=True, progress=lambda i, n: print(f"  {i}/{n} profiles", flush=True))
    print(f"fetched {sum(v is not None for v in snap.values())}/{len(snap)} profiles in {time.time() - t:.0f}s")
