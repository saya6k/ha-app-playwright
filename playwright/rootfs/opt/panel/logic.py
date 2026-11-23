"""Pure helpers for the Ingress panel — no websockify dependency, unit-tested."""

import json
import os
import shutil
import urllib.request
from pathlib import Path

# Supervisor's Ingress gateway, plus loopback for in-container checks. VNC has
# no password, so nothing else on the hassio network may reach the panel.
ALLOWED_CLIENTS = frozenset({"172.30.32.2", "127.0.0.1", "::1"})
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "browser-panel"
CDP_LIST = "http://127.0.0.1:9222/json/list"
PROFILE = Path("/data/profile")


def client_allowed(address: str) -> bool:
    if address.startswith("::ffff:"):
        address = address[7:]
    return address in ALLOWED_CLIENTS


def csrf_ok(headers) -> bool:
    return headers.get(CSRF_HEADER) == CSRF_VALUE


def parse_targets(raw: str) -> list[dict]:
    """CDP /json/list → page tabs as {title, url}."""
    try:
        targets = json.loads(raw)
    except ValueError:
        return []
    return [{"title": str(t.get("title", "")), "url": str(t.get("url", ""))}
            for t in targets if isinstance(t, dict) and t.get("type") == "page"]


def status(fetch=None) -> dict:
    fetch = fetch or (lambda: urllib.request.urlopen(CDP_LIST, timeout=1).read().decode())
    try:
        tabs = parse_targets(fetch())
    except OSError:
        return {"chromium": False, "tabs": []}
    return {"chromium": True, "tabs": tabs}


def wipe_profile(profile: Path = PROFILE) -> int:
    """Delete everything in the profile directory, keep the directory. Returns entries removed."""
    removed = 0
    if not profile.is_dir():
        return 0
    for entry in profile.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed += 1
    os.chmod(profile, 0o700)
    return removed
