"""App options → Playwright MCP command line."""

import json
from pathlib import Path

OPTIONS_PATH = Path("/data/options.json")
CLI = "/opt/playwright-mcp/node_modules/@playwright/mcp/cli.js"
CDP_ENDPOINT = "http://127.0.0.1:9222"
OUTPUT_DIR = "/share/playwright"
DEFAULTS = {"allowed_origins": [], "blocked_origins": [], "idle_reset_minutes": 5}


def load(path: Path = OPTIONS_PATH) -> dict:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raw = {}
    return {key: raw.get(key, default) for key, default in DEFAULTS.items()}


def _origins(values) -> str:
    return ";".join(v.strip() for v in values or [] if isinstance(v, str) and v.strip())


def upstream_argv(opts: dict) -> list[str]:
    argv = [CLI, "--cdp-endpoint", CDP_ENDPOINT, "--image-responses", "omit", "--codegen", "none",
            "--output-dir", OUTPUT_DIR, "--timeout-navigation", "20000", "--timeout-action", "5000"]
    for flag, key in (("--allowed-origins", "allowed_origins"), ("--blocked-origins", "blocked_origins")):
        if joined := _origins(opts.get(key)):
            argv += [flag, joined]
    return argv


def idle_reset_seconds(opts: dict) -> float | None:
    """Idle time after which the gate resets the tabs; None turns it off."""
    minutes = opts.get("idle_reset_minutes")
    return minutes * 60 if isinstance(minutes, int) and minutes > 0 else None


def child_env(env: dict) -> dict:
    """Environment for the Playwright MCP child: no Supervisor credentials."""
    out = {k: v for k, v in env.items() if k not in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN")}
    out["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] = "1"
    return out
