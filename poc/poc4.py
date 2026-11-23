"""Phase 0 round 4: does ONE persistent MCP session fix per-call state loss?

Compares per-call sessions (HA behaviour) with a single long-lived session
(what a gate in front of Playwright MCP would hold) for: file upload modal
state, snapshot refs, and the agent's current tab when the user opens a tab.
"""

import os
import re
import shutil
import time
import urllib.request

import mcp
import poc
from poc import SITE, record, start, stop, wait_port

CSV = "/share/code-interpreter/abc/data.csv"
FLAGS = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
         "--disable-backgrounding-occluded-windows", "--disable-gpu"]


class Persistent:
    """One MCP session reused for every call (gate model)."""

    def __init__(self):
        self.s = mcp.Session(30)
        self.s.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "gate", "version": "0"}})
        self.s.rpc("notifications/initialized", notify=True)

    def call(self, tool, args):
        ev = self.s.rpc("tools/call", {"name": tool, "arguments": args})
        res = [e for e in ev if "result" in e or "error" in e][-1]
        content = res.get("result", {}).get("content", [])
        return {"ok": "result" in res and not res["result"].get("isError"), "content": content}


def boot():
    shutil.rmtree(poc.PROFILE, ignore_errors=True)
    poc.CHROME[:] = poc.CHROME[:-1] + FLAGS + ["about:blank"] if "--disable-gpu" not in poc.CHROME else poc.CHROME
    poc.start_chrome()
    start("mcp", ["node", "/pw/node_modules/@playwright/mcp/cli.js", "--port", "8099", "--host", "127.0.0.1",
                  "--allowed-hosts", "*", "--cdp-endpoint", "http://127.0.0.1:9222", "--shared-browser-context",
                  "--image-responses", "omit", "--output-dir", poc.OUT, "--codegen", "none"], cwd="/share")
    wait_port(8099)


def down():
    stop("mcp")
    stop("chromium")
    time.sleep(1)


def user_tab():
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:9222/json/new?{SITE}/setcookie", method="PUT"))
    time.sleep(1.5)


def run(label, call):
    boot()
    # upload
    call("browser_navigate", {"url": f"{SITE}/upload"})
    c = call("browser_click", {"target": "#f"})
    u = call("browser_file_upload", {"paths": [CSV]})
    t = mcp.text(call("browser_evaluate", {"function": "() => document.getElementById('out').textContent"}))
    record(f"[{label}] click + file_upload", "data.csv:8" in t, f"click={c['ok']} upload={u['ok']}")

    # snapshot ref reused in the next call
    call("browser_navigate", {"url": f"{SITE}/form"})
    snap = mcp.text(call("browser_snapshot", {}))
    m = re.search(r'textbox[^\n]*\[ref=(\w+)\]', snap)
    if not m:
        print(f"[{label}] SNAPSHOT TEXT:", snap[:600], flush=True)
    ref = m.group(1) if m else None
    ty = call("browser_type", {"target": ref or "e0", "element": "query box", "text": "refs", "submit": True})
    t = mcp.text(call("browser_evaluate", {"function": "() => document.body.innerText"}))
    record(f"[{label}] snapshot ref across calls", "RESULT:refs" in t, f"ref={ref} type={ty['ok']} "
           f"{mcp.text(ty).strip()[:90]!r}" if not ty["ok"] else f"ref={ref}")

    # user opens a tab -> agent keeps its tab?
    call("browser_navigate", {"url": f"{SITE}/upload"})
    user_tab()
    t = mcp.text(call("browser_evaluate", {"function": "() => location.pathname"}))
    c = call("browser_click", {"target": "#f"})
    u = call("browser_file_upload", {"paths": [CSV]})
    t2 = mcp.text(call("browser_evaluate", {"function": "() => document.getElementById('out')?.textContent"}))
    record(f"[{label}] user tab opened: agent stays + upload in bg tab", "/upload" in t and "data.csv:8" in t2,
           f"agent page={t.split(chr(10))[1] if chr(10) in t else t[:40]!r} click={c['ok']} upload={u['ok']} "
           f"{(mcp.text(c) if not c['ok'] else '').strip()[:100]!r}")
    # bring the agent's tab to front via browser_tabs select, then retry
    lst = mcp.text(call("browser_tabs", {"action": "list"}))
    idx = next((int(m.group(1)) for m in re.finditer(r"- (\d+): [^\n]*/upload", lst)), None)
    sel = call("browser_tabs", {"action": "select", "index": idx}) if idx is not None else {"ok": False}
    call("browser_file_upload", {})
    c = call("browser_click", {"target": "#f"})
    u = call("browser_file_upload", {"paths": [CSV]})
    t2 = mcp.text(call("browser_evaluate", {"function": "() => document.getElementById('out')?.textContent"}))
    fg = urllib.request.urlopen("http://127.0.0.1:9222/json/list").read().decode()
    record(f"[{label}] after browser_tabs select", "data.csv:8" in t2,
           f"idx={idx} select={sel['ok']} click={c['ok']} upload={u['ok']}")
    down()


def main():
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    open(CSV, "w").write("a,b\n1,2\n")
    os.makedirs(poc.OUT, exist_ok=True)
    start("site", ["python3", "/smoke/site.py"])
    start("xvfb", ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"])
    wait_port(8000)
    time.sleep(1)

    run("per-call sessions", mcp.call)
    holder = {}

    def persistent(tool, args):
        if "p" not in holder:
            holder["p"] = Persistent()
        return holder["p"].call(tool, args)

    run("one persistent session", persistent)

    for name in list(poc.PROCS):
        stop(name)
    print("\n=== SUMMARY ===")
    for name, ok, detail in poc.RESULTS:
        print(f"{'PASS' if ok else 'FAIL' if ok is False else 'INFO':4} | {name} | {detail}")


if __name__ == "__main__":
    main()
