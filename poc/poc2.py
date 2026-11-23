"""Phase 0 round 2: background-tab throttling, llvm removal, and file roots.

Each variant starts a fresh profile, lets the agent open a page, then opens a
"user" tab via CDP (which comes to the foreground) and retries the actions that
failed in round 1.
"""

import glob
import os
import shutil
import subprocess
import time
import urllib.request

import mcp
import poc
from poc import SITE, record, start, start_mcp, stop, wait_port

NO_THROTTLE = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
               "--disable-backgrounding-occluded-windows"]


def scenario(label, extra_flags, cwd="/share"):
    shutil.rmtree(poc.PROFILE, ignore_errors=True)
    shutil.rmtree(poc.OUT, ignore_errors=True)
    os.makedirs(poc.OUT)
    poc.CHROME[:] = BASE_CHROME[:-1] + extra_flags + ["about:blank"]
    poc.start_chrome()
    start("mcp", ["node", "/pw/node_modules/@playwright/mcp/cli.js", "--port", "8099", "--host", "127.0.0.1",
                  "--allowed-hosts", "*", "--cdp-endpoint", "http://127.0.0.1:9222", "--shared-browser-context",
                  "--image-responses", "omit", "--output-dir", poc.OUT, "--codegen", "none"], cwd=cwd)
    wait_port(8099)

    mcp.call("browser_navigate", {"url": f"{SITE}/upload"})
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:9222/json/new?{SITE}/setcookie", method="PUT"))
    time.sleep(1.5)

    s = mcp.call("browser_take_screenshot", {})
    c = mcp.call("browser_click", {"target": "#f"})
    u = mcp.call("browser_file_upload", {"paths": ["/share/code-interpreter/abc/data.csv"]})
    _, t = poc.evaluate("() => document.getElementById('out').textContent")
    shot = bool(glob.glob(f"{poc.OUT}/*.png"))
    record(f"[{label}] bg-tab screenshot/click/upload", s["ok"] and c["ok"] and "data.csv:8" in t,
           f"shot={s['ok']}/{shot} click={c['ok']} upload={u['ok']} out={t.strip()[-30:]!r} "
           f"err={(mcp.text(s) if not s['ok'] else mcp.text(c) if not c['ok'] else mcp.text(u))[:110]!r}")
    if not s["ok"]:
        mcp.call("browser_file_upload", {})
        sel = mcp.call("browser_tabs", {"action": "select", "index": 0})
        s2 = mcp.call("browser_take_screenshot", {})
        record(f"[{label}] after browser_tabs select", s2["ok"], f"select={sel['ok']} shot={s2['ok']}")

    stop("mcp")
    stop("chromium")
    log = open("/tmp/chromium.log").read()
    return log


def main():
    os.makedirs("/share/code-interpreter/abc", exist_ok=True)
    with open("/share/code-interpreter/abc/data.csv", "w") as f:
        f.write("a,b\n1,2\n")
    start("site", ["python3", "/smoke/site.py"])
    start("xvfb", ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"])
    wait_port(8000)
    time.sleep(1)

    scenario("V1 default", [])
    scenario("V2 no-throttle", NO_THROTTLE)

    usr_before = subprocess.run(["du", "-sm", "/usr"], capture_output=True, text=True).stdout.split()[0]
    for p in glob.glob("/usr/lib/libLLVM*"):
        os.remove(p)
    usr_after = subprocess.run(["du", "-sm", "/usr"], capture_output=True, text=True).stdout.split()[0]
    record("llvm removed", None, f"/usr {usr_before}MB -> {usr_after}MB")

    log = scenario("V3 no-throttle, no llvm", NO_THROTTLE)
    record("[V3] GL errors in log", None, str(sum("libLLVM" in ln for ln in log.splitlines())) + " lines")
    log = scenario("V4 no-throttle, no llvm, --disable-gpu", NO_THROTTLE + ["--disable-gpu"])
    record("[V4] GL errors in log", None, str(sum("libLLVM" in ln for ln in log.splitlines())) + " lines")

    # Roots: with cwd=/share/playwright, can the agent still upload a sibling's file?
    poc.CHROME[:] = BASE_CHROME[:-1] + NO_THROTTLE + ["--disable-gpu", "about:blank"]
    poc.start_chrome()
    start("mcp", ["node", "/pw/node_modules/@playwright/mcp/cli.js", "--port", "8099", "--host", "127.0.0.1",
                  "--allowed-hosts", "*", "--cdp-endpoint", "http://127.0.0.1:9222", "--shared-browser-context",
                  "--image-responses", "omit", "--output-dir", poc.OUT, "--codegen", "none"], cwd=poc.OUT)
    wait_port(8099)
    mcp.call("browser_navigate", {"url": f"{SITE}/upload"})
    mcp.call("browser_click", {"target": "#f"})
    u = mcp.call("browser_file_upload", {"paths": ["/share/code-interpreter/abc/data.csv"]})
    w = mcp.call("browser_take_screenshot", {"filename": "../code-interpreter/abc/evil.png"})
    record("cwd=/share/playwright: upload sibling file", u["ok"], mcp.text(u).strip()[:140].replace("\n", " | "))
    record("cwd=/share/playwright: write outside", None,
           f"ok={w['ok']} exists={os.path.exists('/share/code-interpreter/abc/evil.png')} "
           f"{mcp.text(w).strip()[:120]!r}")

    for name in list(poc.PROCS):
        stop(name)
    print("\n=== SUMMARY ===")
    for name, ok, detail in poc.RESULTS:
        print(f"{'PASS' if ok else 'FAIL' if ok is False else 'INFO':4} | {name} | {detail}")


BASE_CHROME = list(poc.CHROME)

if __name__ == "__main__":
    main()
