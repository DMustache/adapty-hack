"""End-to-end pipeline demo in the live Adapty app: a discount A/B test with SIMULATED users.

Creates (idempotently, all titled "(test)"):
  * three products at 30% off: annual, monthly, weekly
  * a copy of the "Main - 3 plans" paywall flow that sells those products
  * an A/B test on placement `main`: full price (control) vs 30% off, all users
Then sends N simulated users through it: offline users who saw placement `main` and are NOT already in the live app
(index >= 5000), outside the US/Canada. Arm = deterministic 50/50 hash.
  * control: the user's real day-one outcome from the offline data
  * discount: the same outcome at 70% of the price, plus extra buyers so conversion rises by the ASSUMED lift at 30%
    from the Discount Advisor's default response curve. The result therefore only demonstrates the pipeline;
    it cannot validate any discount.

These purchases are dated now, so they count toward the account's monthly tracked revenue (MTR); the summary prints
the USD total before anything is sent.

Usage:  python adapty_experiment.py [--users 150] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SEED_REPO = HERE.parent / "adapty-seed-data-hack"
sys.path.insert(0, str(SEED_REPO))
sys.path.insert(0, str(HERE))

import seed_adapty as seed  # noqa: E402

from adapty_live import APP_ID, secret_key  # noqa: E402
from data import load  # noqa: E402
from economics import conversion_at, sigma_from_anchor  # noqa: E402
from metrics import segment_baseline  # noqa: E402

DISCOUNT = 0.30
TAG = "(test)"
TEST_TITLE = f"Discount test: main 30% off vs full price {TAG}"
FLOW_TITLE = f"Main - 3 plans, 30% off {TAG}"
DISCOUNTED = {k: f"{k}_30off" for k in ("annual", "monthly", "weekly")}


def ensure_products(cli, levels: dict) -> dict[str, str]:
    seed.step("Discounted products")
    existing = cli.list_all("products", "list", "--app", APP_ID)
    for p in seed.PRODUCTS:  # ids of the regular products (needed for the control flow config)
        p.adapty_id = seed._id(seed.by_field(existing, "title", p.title))
    ids = {}
    for key, new_key in DISCOUNTED.items():
        base = seed.PRODUCT_BY_KEY[key]
        title = f"{base.title.split(' (')[0]} 30% off {TAG}"
        found = seed.by_field(existing, "title", title)
        if found:
            ids[key] = seed._id(found)
            seed.log(f"  {title}: exists")
            continue
        args = ["products", "create", "--app", APP_ID, "--title", title, "--access-level-id", levels[base.access],
                "--period", base.period, "--ios-product-id", f"lumen.{new_key}",
                "--android-product-id", f"lumen_{new_key}", "--android-base-plan-id", new_key.replace("_", "-")]
        ids[key] = seed._id(cli.run(*args))
        seed.log(f"  {title}: created (lumen.{new_key}, ${base.price_usd * (1 - DISCOUNT):.2f} list)")
    return ids


def ensure_flow(cli, discounted_ids: dict[str, str]) -> str:
    seed.step("Discounted paywall flow")
    existing = cli.list_all("flows", "list", "--app", APP_ID)
    for f in seed.FLOWS:
        f.adapty_id = seed._id(seed.by_field(existing, "name", f.title))
    found = seed.by_field(existing, "name", FLOW_TITLE)
    if found and found.get("status") == "published":
        seed.log(f"  {FLOW_TITLE}: published (exists)")
        return seed._id(found)
    text = seed.FLOW_BY_KEY["main"].config_path.read_text()
    for key, pid in discounted_ids.items():
        text = text.replace(seed.placeholder_product_id(key), pid)
    config = json.loads(text)
    for screen_id, meta in config["_meta"]["screens"].items():
        for entry in meta["products"]:
            entry["flowProductId"] = seed.flow_product_id(screen_id, entry["id"])
    flow_id = seed._id(found) if found else seed._id(cli.run("flows", "create", "--app", APP_ID, "--name", FLOW_TITLE))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(config, f)
    try:
        cli.run("flows", "config", "update", flow_id, "--app", APP_ID, "--config-file", f.name)
    finally:
        os.unlink(f.name)
    cli.run("flows", "publish", flow_id, "--app", APP_ID, "--yes")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(5)
        status = seed._unwrap(cli.run("flows", "get", flow_id, "--app", APP_ID, write=False)).get("status")
        if status == "published":
            seed.log(f"  {FLOW_TITLE}: published")
            return flow_id
        if status == "publication_failed":
            seed.die(f"{FLOW_TITLE}: publication failed")
    seed.die(f"{FLOW_TITLE}: still publishing after 5 minutes")


def ensure_test(cli, control_flow: str, discount_flow: str) -> tuple[str, dict[str, str]]:
    seed.step("A/B test")
    placements = cli.list_all("placements", "list", "--app", APP_ID)
    main = seed.by_field(placements, "developer_id", "main")
    tests = cli.list_all("ab-tests", "list", "--app", APP_ID, "--type", "flow")
    found = seed.by_field(tests, "title", TEST_TITLE)
    if found:
        test_id, state = seed._id(found), found.get("state")
    else:
        arms = [{"flow_id": control_flow, "weight": 50, "title": "A"}, {"flow_id": discount_flow, "weight": 50, "title": "B"}]
        test_id = seed._id(cli.run("ab-tests", "create", "--app", APP_ID, "--title", TEST_TITLE,
                                   "--goal", "Does 30% off the main paywall raise revenue per user? (simulated users)",
                                   "--placement", seed._id(main), "--flows", json.dumps(arms), "--all-users"))
        state = "draft"
    if state == "draft":
        cli.run("ab-tests", "start", "--app", APP_ID, test_id, "--placement", seed._id(main), "--all-users", "--yes")
        state = "live"
    seed.log(f"  {TEST_TITLE}: {state}")
    data = seed._unwrap(cli.run("ab-tests", "get", "--app", APP_ID, test_id, write=False))
    variations = {}
    for arm in seed._items(data.get("flows") or []):
        fid = arm.get("flow_id") or arm.get("id")
        variations["control" if fid == control_flow else "discount"] = arm.get("variation_id")
    if set(variations) != {"control", "discount"} or not all(variations.values()):
        seed.die(f"could not read both arms' variation ids: {variations}")
    return test_id, variations


def plan_users(n: int, run_id: str) -> tuple[list[dict], dict]:
    """Pick and simulate users. Returns payload specs and a summary (no network)."""
    ds = load()
    u, tx = ds.users, ds.tx
    idx = u.user_id.str[1:].astype(int)
    pool = u[(idx >= 5000) & (u.placement == "main") & ~u.country.isin(["US", "CA"])].head(n)
    base = segment_baseline(ds, (u.placement == "main") & ~u.country.isin(["US", "CA"]), "main non-NA", 12)
    c0 = base.conversion
    sigma = sigma_from_anchor(c0, 0.20, 2.0)
    assumed_lift = float(conversion_at(DISCOUNT, c0, sigma, 2.0) / c0 - 1)
    first = tx.sort_values("seq").groupby("user_id").head(1).set_index("user_id")
    local_price = (tx[tx.is_paid].groupby(["country", "product"])[["price_local", "price_usd"]].median())
    currency = tx.groupby("country").currency.first()
    mix = base.product_mix[[p for p in base.product_mix.index if p in DISCOUNTED]]
    mix = mix / mix.sum()
    specs, usd = [], {"control": 0.0, "discount": 0.0}
    rng = np.random.default_rng(int(run_id))
    for k, r in enumerate(pool.itertuples()):
        arm = "discount" if int(hashlib.md5(f"{run_id}:{r.user_id}".encode()).hexdigest()[:8], 16) % 2 else "control"
        # outcome = the advisor's definition: first PAID receipt within the conversion window (sent today)
        paid = bool(r.converted) and r.product in DISCOUNTED
        product, offer = (r.product, None) if paid else (None, None)
        if arm == "discount" and product is None:
            # extra buyers: P(buy | not a day-one buyer) chosen so the arm's conversion rises by the assumed lift
            p_extra = c0 * assumed_lift / max(1e-9, 1 - c0)
            if rng.random() < p_extra:
                product, offer = rng.choice(mix.index, p=mix.values), None
        price = local = 0.0
        if product is not None and offer != "free_trial":
            local = float(local_price.loc[(r.country, product), "price_local"])
            price = float(local_price.loc[(r.country, product), "price_usd"])
            if arm == "discount":
                local, price = round(local * (1 - DISCOUNT), 2), price * (1 - DISCOUNT)
        usd[arm] += price
        specs.append({"k": k, "user_id": r.user_id, "arm": arm, "platform": r.platform, "country": r.country,
                      "currency": currency.get(r.country, "USD"), "product": product, "offer": offer,
                      "local": local, "attrs": {"acquisition_channel": r.acquisition_channel,
                                                "onboarding_goal": r.onboarding_goal, "app_version": r.app_version,
                                                "simulated_user": "discount_test"}})
    summary = {"c0": c0, "assumed_lift": assumed_lift, "users": len(specs),
               "arms": pd.Series([s["arm"] for s in specs]).value_counts().to_dict(),
               "buyers": pd.Series([s["arm"] for s in specs if s["product"]]).value_counts().to_dict(),
               "usd": usd}
    return specs, summary


def send(specs: list[dict], variations: dict, test_id: str, discounted_ids: dict, key: str, run_id: str) -> dict:
    api = seed.Api(key, dry_run=False)
    now = datetime.now(timezone.utc)
    for s in specs:
        store = "app_store" if s["platform"] == "iOS" else "play_store"
        cuid = f"lumen_{run_id}_D{s['k']:04d}"
        profile = {"ip_country": s["country"], "store_country": s["country"], "store": store,
                   "custom_attributes": [{"key": k, "value": v} for k, v in
                                         {**s["attrs"], seed.SEED_MARKER[0]: seed.SEED_MARKER[1]}.items()]}
        headers = {"adapty-customer-user-id": cuid, "adapty-platform": s["platform"]}
        res = api.post("/profile/", profile, headers)
        if res is None:
            api.stats["profiles_failed"] += 1
            continue
        api.stats["profiles"] += 1
        pid = (seed._unwrap(res) or {}).get("profile_id")
        vid = variations[s["arm"]]
        seen = now - timedelta(minutes=30) + timedelta(seconds=10 * s["k"])
        events = [{"event_name": "flow_variation_assigned", "event_id": str(uuid.uuid4()), "profile_id": pid,
                   "session_id": str(uuid.uuid4()), "device_id": str(uuid.uuid4()), "platform": s["platform"],
                   "created_at": seed._iso(seen), "variation_id": vid, "placement_audience_version_id": test_id},
                  {"event_name": "flow_showed", "event_id": str(uuid.uuid4()), "profile_id": pid,
                   "session_id": str(uuid.uuid4()), "device_id": str(uuid.uuid4()), "platform": s["platform"],
                   "created_at": seed._iso(seen), "variation_id": vid}]
        ok = api.request("POST", f"{seed.SDK_BASE}/events/", {"data": {"type": "sdk_background_event",
                                                                   "attributes": {"events": events}}},
                         {"Content-Type": "application/vnd.api+json", "Accept": "application/vnd.api+json",
                          "ADAPTY-SDK-PLATFORM": s["platform"]}, "flow events") is not None
        api.stats["flow_views" if ok else "flow_views_failed"] += 1
        if not s["product"]:
            continue
        base = seed.PRODUCT_BY_KEY[s["product"]]
        pkey = DISCOUNTED[s["product"]] if s["arm"] == "discount" else s["product"]
        tx_id = f"9{run_id}{s['k']:06d}"
        bought = seen + timedelta(seconds=60)
        period = {"weekly": 7, "monthly": 30, "annual": 365}[s["product"]]
        dur = 3 if s["offer"] == "free_trial" else period
        tx = {"purchase_type": "subscription", "store": store, "environment": "Production",
              "store_product_id": f"lumen.{pkey}" if store == "app_store" else f"lumen_{pkey}",
              "store_transaction_id": tx_id, "store_original_transaction_id": tx_id, "is_family_shared": False,
              "price": {"country": s["country"], "currency": s["currency"], "value": s["local"]},
              "purchased_at": seed._iso(bought), "originally_purchased_at": seed._iso(bought),
              "expires_at": seed._iso(bought + timedelta(days=dur)), "renew_status": True, "variation_id": vid,
              "offer": ({"category": "introductory", "type": "free_trial", "id": None}
                        if s["offer"] == "free_trial" else None)}
        if api.post("/purchase/set/transaction/", tx, headers) is None:
            api.stats["transactions_failed"] += 1
        else:
            api.stats["transactions"] += 1
    return dict(api.stats) | {"errors": dict(api.errors.most_common(5))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=150)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%H%M%S"))
    args = ap.parse_args()
    specs, summary = plan_users(args.users, args.run_id)
    seed.step("Plan (simulated users)")
    seed.log(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in summary.items()}, default=str))
    seed.log(f"  tracked revenue this adds (USD, approx.): ${sum(summary['usd'].values()):,.0f}")
    if args.dry_run:
        seed.log("Dry run: nothing created or sent.")
        return
    cli = seed.Cli(False)
    cli.ensure_version()
    cli.ensure_login()
    levels = {seed._unwrap(x).get("sdk_id") or x.get("sdk_id"): seed._id(x)
              for x in cli.list_all("access-levels", "list", "--app", APP_ID)}
    discounted = ensure_products(cli, levels)
    flow_id = ensure_flow(cli, discounted)
    test_id, variations = ensure_test(cli, seed.FLOW_BY_KEY["main"].adapty_id, flow_id)
    seed.step(f"Sending {len(specs)} simulated users")
    stats = send(specs, variations, test_id, discounted, secret_key(), args.run_id)
    seed.log(json.dumps(stats, default=str))


if __name__ == "__main__":
    main()
