"""Local development only: load API keys from the workspace credentials/ folder into os.environ.
In GitHub Actions the same names come from repository secrets. Values are never printed.
This file holds no secrets itself — only file and key NAMES."""
import json
import os
from pathlib import Path

CRED = Path(os.environ.get("VT_CRED_DIR", "/home/kenny/ai/credentials"))


def load():
    p = CRED / ".repasovanyiphone-credentials.env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip("\"'"))
    feeds = CRED / ".repasovanyiphone-feeds.json"       # {feed_key: URL}; URLs carry tokens -> only here and in the FEEDS_JSON secret
    if feeds.exists():
        os.environ.setdefault("FEEDS_JSON", json.dumps(json.load(feeds.open()), separators=(",", ":")))
