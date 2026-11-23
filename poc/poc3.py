"""Phase 0 round 3: isolate each variable (llvm already removed for every case)."""

import glob
import json
import os
import shutil
import subprocess
import time
import urllib.request

import mcp
import poc
from poc import SITE, record, start, stop, wait_port

FLAGS = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
         "--disable-backgrounding-occluded-windows"]
BASE = list(poc.CHROME[:-1])
CSV = "/share/code-interpreter/abc/data.csv"


def boot(cwd, extra=()):
    shutil.rmtree(poc.PROFILE, ignore_errors=True)
    poc.CHROME[:] = BASE + FLAGS + list(extra) + ["about:blank"]
    open("/tmp/chromium.log", "w").close()
    if not poc.start_chrome():
        print("CHROME FAILED:", open("/tmp/chromium.log").read()[-600:], flush=True)
    start("mcp", ["node", "/pw/node_modules/@playwright/mcp/cli.js", "--port", "8099", "--host", "127.0.0.1",
                  "--allowed-hosts", "*", "--cdp-endpoint", "http://127.0.0.1:9222", "--shared-browser-context",
                  "--image-responses", "omit", "--output-dir", poc.OUT, "--codegen", "none"], cwd=cwd)
    wait_port(8099)


def down():
    stop("mcp")
    stop("chromium")
    time.sleep(1)


def short(r):
    return mcp.text(r).strip().split("\n### Page")[0].replace("\n", " | ")[:160]


def upload_flow():
    c = mcp.call("browser_click", {"target": "#f"})
    u = mcp.call("browser_file_upload", {"paths": [CSV]})
    _, t = poc.evaluate("() => document.getElementById('out')?.textContent")
    return c, u, t


def cdp_targets():
    return json.load(urllib.request.urlopen("http://127.0.0.1:9222/json/list"))


def main():
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    open(CSV, "w").write("a,b\n1,2\n")
    os.makedirs(poc.OUT, exist_ok=True)
    start("site", ["python3", "/smoke/site.py"])
    start("xvfb", ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"])
    wait_port(8000)
    time.sleep(1)

    # E1: single tab, cwd=/share -> upload sibling file
    boot("/share")
    mcp.call("browser_navigate", {"url": f"{SITE}/upload"})
    c, u, t = upload_flow()
    record("E1 single tab, cwd=/share: click+upload", "data.csv:8" in t,
           f"click={c['ok']} upload={u['ok']} out={t.strip()[-25:]!r} | {short(u) if not u['ok'] else ''}")
    gl = sum("libLLVM" in ln for ln in open("/tmp/chromium.log"))
    down()

    # E2: single tab, cwd=/share/playwright -> upload sibling file
    boot(poc.OUT)
    mcp.call("browser_navigate", {"url": f"{SITE}/upload"})
    c, u, t = upload_flow()
    record("E2 single tab, cwd=/share/playwright: upload sibling", "data.csv:8" in t,
           f"click={c['ok']} upload={u['ok']} | {short(u)}")
    down()

    # E3: user opens a tab -> which tab is agent's current, and can we fix it by activating?
    boot("/share")
    mcp.call("browser_navigate", {"url": f"{SITE}/upload"})
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:9222/json/new?{SITE}/setcookie", method="PUT"))
    time.sleep(1.5)
    tabs = mcp.call("browser_tabs", {"action": "list"})
    record("E3 tabs after user tab opens", None, short(tabs))
    c, u, t = upload_flow()
    record("E3 click+upload with user tab in front", "data.csv:8" in t,
           f"click={c['ok']} upload={u['ok']} out={str(t).strip()[-25:]!r} | {short(c) if not c['ok'] else ''}")
    mcp.call("browser_file_upload", {})
    agent = [x for x in cdp_targets() if x["type"] == "page" and x["url"].endswith("/upload")]
    if agent:
        urllib.request.urlopen(f"http://127.0.0.1:9222/json/activate/{agent[0]['id']}")
        time.sleep(0.5)
    c, u, t = upload_flow()
    record("E3b after CDP activate of agent tab", "data.csv:8" in t,
           f"activated={bool(agent)} click={c['ok']} upload={u['ok']} out={str(t).strip()[-25:]!r}")
    down()

    # E4: agent opens a tab itself, user tab stays behind
    boot("/share")
    mcp.call("browser_navigate", {"url": f"{SITE}/whoami"})
    n = mcp.call("browser_tabs", {"action": "new", "url": f"{SITE}/upload"})
    c, u, t = upload_flow()
    record("E4 agent-created new tab: click+upload", "data.csv:8" in t,
           f"new={n['ok']} click={c['ok']} upload={u['ok']} | {short(c) if not c['ok'] else ''}")
    down()

    # E5: background-tab screenshot per GL mode (llvm present)
    for extra in ([], ["--disable-gpu"], ["--use-angle=swiftshader"], ["--use-gl=angle", "--use-angle=swiftshader-webgl"]):
        boot("/share", extra)
        mcp.call("browser_navigate", {"url": "https://en.wikipedia.org/wiki/Raspberry_Pi"})
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:9222/json/new?{SITE}/setcookie", method="PUT"))
        time.sleep(1.5)
        s = mcp.call("browser_take_screenshot", {"filename": "playwright/e5.png"})
        size = os.path.getsize("/share/playwright/e5.png") if os.path.exists("/share/playwright/e5.png") else 0
        lines = sum("libLLVM" in ln or "ANGLE" in ln for ln in open("/tmp/chromium.log"))
        _, gl = poc.evaluate("() => { const c=document.createElement('canvas').getContext('webgl'); return c ? c.getParameter(c.RENDERER) : 'no-webgl' }")
        record(f"E5 bg-tab screenshot {' '.join(extra) or '(default)'}", s["ok"] and size > 20000,
               f"png={size}B gl-log-lines={lines} renderer={gl.split(chr(10))[1][:60] if chr(10) in gl else gl[:60]!r}")
        if os.path.exists("/share/playwright/e5.png"):
            os.remove("/share/playwright/e5.png")
        down()
    record("E1 default flags gl-error-lines", None, str(gl))

    pw = subprocess.run("grep -rln bringToFront /pw/node_modules/playwright*/lib | head; "
                        "grep -rhoE '.{100}bringToFront.{60}' /pw/node_modules/playwright/lib/mcp 2>/dev/null | head -5",
                        shell=True, capture_output=True, text=True).stdout
    record("bringToFront usage in playwright mcp", None, pw.strip().replace("\n", " || ")[:700])

    for name in list(poc.PROCS):
        stop(name)
    print("\n=== SUMMARY ===")
    for name, ok, detail in poc.RESULTS:
        print(f"{'PASS' if ok else 'FAIL' if ok is False else 'INFO':4} | {name} | {detail}")


if __name__ == "__main__":
    main()
