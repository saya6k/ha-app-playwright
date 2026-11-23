"""Pure argument/result rewriting for the gate — no MCP dependency."""

import posixpath
import re

# Tools that act on the rendered page. A background tab does not render, so
# Playwright's actionability wait times out there (Phase 0 PoC): the gate
# brings the agent's current tab to the front before these.
FRONT_TOOLS = frozenset({
    "browser_click", "browser_drag", "browser_drop", "browser_file_upload", "browser_fill_form",
    "browser_hover", "browser_press_key", "browser_select_option", "browser_take_screenshot",
    "browser_type",
})

# PoC: a full Wikipedia snapshot is 225,894 characters; depth 6 is 10,188.
SNAPSHOT_DEFAULT_DEPTH = 6
OUTPUT_SUBDIR = "playwright"  # relative to Playwright MCP's cwd (/share)

_CURRENT = re.compile(r"^- (\d+): \(current\)", re.M)
_TAB = re.compile(r"^- \d+: ", re.M)


def needs_front(tool: str) -> bool:
    return tool in FRONT_TOOLS


def parse_tabs(text: str) -> tuple[int | None, int]:
    """Return (current tab index, tab count) from `browser_tabs list` output."""
    m = _CURRENT.search(text)
    return (int(m.group(1)) if m else None), len(_TAB.findall(text))


def rewrite_args(tool: str, args: dict) -> dict:
    """Confine explicit filenames to /share/playwright and default the snapshot depth."""
    out = dict(args)
    name = out.get("filename")
    if isinstance(name, str):
        base = posixpath.basename(name.replace("\\", "/")).lstrip(".")
        if base:
            out["filename"] = f"{OUTPUT_SUBDIR}/{base}"
        else:
            del out["filename"]
    if tool == "browser_snapshot" and "depth" not in out:
        out["depth"] = SNAPSHOT_DEFAULT_DEPTH
    return out


def truncate_texts(texts: list[str], limit: int) -> list[str]:
    """Cap the combined length of text parts at `limit`, noting the cut on the last kept part."""
    total = sum(len(t) for t in texts)
    if total <= limit:
        return list(texts)
    out, left = [], limit
    for t in texts:
        if left is None:
            out.append("")
        elif len(t) < left:
            out.append(t)
            left -= len(t)
        else:  # total > limit, so text remains past this cut
            out.append(t[:left] + (
                f"\n\n[Truncated by the add-on: {limit} of {total} characters shown. Call browser_snapshot "
                "with a smaller depth or a target ref to read a specific part of the page.]"))
            left = None
    return out
