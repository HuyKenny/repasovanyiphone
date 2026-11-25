#!/usr/bin/env python3
"""Deploy dist/ as Workers static assets: no Worker script, so no request is ever billed (Cloudflare Free).

    python3 scripts/deploy.py staging       # Worker "repasovanyiphone-staging" on workers.dev (noindex build)
    python3 scripts/deploy.py production    # Worker "repasovanyiphone" on repasovanyiphone.cz/* and www

Needs CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID in the environment. Prints no secrets.
"""
import json
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
DIST = APP / "dist"
WRANGLER = "wrangler@4.151.3"
ZONE = "repasovanyiphone.cz"
FORBIDDEN = ("main", "d1_databases", "kv_namespaces", "r2_buckets", "durable_objects", "queues", "services", "ai", "browser",
             "vectorize", "hyperdrive", "analytics_engine_datasets", "triggers", "cron", "workflows")


def main():
    env = sys.argv[1] if len(sys.argv) > 1 else "staging"
    n = sum(1 for p in DIST.rglob("*") if p.is_file())
    if n > 19_000:                      # Workers Free: 20 000 asset files per version
        sys.exit(f"dist has {n} files, over the Free plan limit")
    name = "repasovanyiphone" + ("-staging" if env == "staging" else "")
    cfg = {"name": name, "compatibility_date": "2026-10-01", "preview_urls": False, "observability": {"enabled": False},
           "workers_dev": env == "staging",
           "assets": {"directory": str(DIST), "html_handling": "auto-trailing-slash", "not_found_handling": "404-page"}}
    if env == "production":
        cfg["routes"] = [{"pattern": f"{ZONE}/*", "zone_name": ZONE}, {"pattern": f"www.{ZONE}/*", "zone_name": ZONE}]
    bad = [k for k in FORBIDDEN if k in cfg]
    if bad:                             # cost guard: assets only, nothing billed
        sys.exit(f"refusing: billed features in config: {bad}")
    path = APP / f".wrangler-{name}.json"
    path.write_text(json.dumps(cfg, indent=1))
    try:
        r = subprocess.run(["npx", "--yes", WRANGLER, "deploy", "--config", str(path), "--message", "repasovanyiphone build"], cwd=APP)
    finally:
        path.unlink(missing_ok=True)
    print(f"deployed {n} files to {name}")
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
