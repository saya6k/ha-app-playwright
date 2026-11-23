"""Phase 0 PoC orchestrator — runs inside an alpine:3.23 container (see run.sh)."""

import base64
import glob
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import mcp  # noqa: E402

SITE = "http://127.0.0.1:8000"
PROFILE = "/data/profile"
OUT = "/share/playwright"
RESULTS = []
PROCS = {}
ENV = {k: v for k, v in os.environ.items() if k != "SUPERVISOR_TOKEN"} | {"DISPLAY": ":99"}


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL' if ok is False else 'INFO'}] {name}: {detail}", flush=True)


def wait_port(port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def start(name, argv, cwd=None):
    log = open(f"/tmp/{name}.log", "ab")
    PROCS[name] = subprocess.Popen(argv, env=ENV, cwd=cwd, stdout=log, stderr=log, start_new_session=True)


def stop(name, sig=signal.SIGTERM):
    p = PROCS.pop(name, None)
    if p and p.poll() is None:
        os.killpg(p.pid, sig)
        try:
            p.wait(15)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()


CHROME = ["chromium-browser", "--no-sandbox", "--disable-dev-shm-usage", "--no-first-run",
          "--no-default-browser-check", f"--user-data-dir={PROFILE}", "--remote-debugging-address=127.0.0.1",
          "--remote-debugging-port=9222", "--window-position=0,0", "--window-size=1280,800", "about:blank"]


def start_chrome():
    start("chromium", CHROME)
    ok = wait_port(9222)
    time.sleep(1)
    return ok


def start_mcp():
    start("mcp", ["node", "/pw/node_modules/@playwright/mcp/cli.js", "--port", "8099", "--host", "127.0.0.1",
                  "--allowed-hosts", "*", "--cdp-endpoint", "http://127.0.0.1:9222", "--shared-browser-context",
                  "--image-responses", "omit", "--output-dir", OUT, "--codegen", "none",
                  "--timeout-navigation", "20000"], cwd="/share")
    return wait_port(8099)


def evaluate(fn):
    r = mcp.call("browser_evaluate", {"function": fn})
    return r, mcp.text(r)


def pss_by_name():
    out = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            name = open(f"{d}/comm").read().strip()
            for line in open(f"{d}/smaps_rollup"):
                if line.startswith("Pss:"):
                    key = "chromium" if name.startswith("chrom") else name
                    out[key] = out.get(key, 0) + int(line.split()[1])
        except OSError:
            continue
    return {k: round(v / 1024) for k, v in sorted(out.items(), key=lambda x: -x[1]) if v > 2048}


def ws_rfb_check():
    """WebSocket handshake to websockify, then read the RFB greeting from x11vnc."""
    s = socket.create_connection(("127.0.0.1", 8098), 5)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET /websockify HTTP/1.1\r\nHost: 127.0.0.1:8098\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
               f"Sec-WebSocket-Protocol: binary\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    head, rest = buf.split(b"\r\n\r\n", 1)
    while len(rest) < 2:
        rest += s.recv(4096)
    ln = rest[1] & 0x7F
    payload = rest[2:]
    while len(payload) < ln:
        payload += s.recv(4096)
    s.close()
    return head.split(b"\r\n")[0].decode(), payload[:ln].decode(errors="replace")


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs("/share/code-interpreter/abc", exist_ok=True)
    with open("/share/code-interpreter/abc/data.csv", "w") as f:
        f.write("a,b\n1,2\n")

    start("site", ["python3", "/smoke/site.py"])
    start("xvfb", ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"])
    time.sleep(1)
    record("chromium headful on Xvfb + CDP", start_chrome(), open("/tmp/chromium.log").read()[-200:].strip())
    record("playwright-mcp listening", start_mcp())
    wait_port(8000)

    # 1. Fresh MCP session per call (HA behaviour) keeps page state
    r1 = mcp.call("browser_navigate", {"url": f"{SITE}/form"})
    r2 = mcp.call("browser_type", {"target": "#q", "text": "hello", "submit": True})
    _, t = evaluate("() => location.pathname + '|' + document.body.innerText")
    record("state persists across per-call sessions", "RESULT:hello" in t,
           f"navigate ok={r1['ok']} type ok={r2['ok']} -> {t.strip()[-80:]!r}")

    # 2. User tab (panel) login visible to agent
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:9222/json/new?{SITE}/setcookie", method="PUT"))
    time.sleep(1.5)
    mcp.call("browser_navigate", {"url": f"{SITE}/whoami"})
    _, t = evaluate("() => document.body.innerText")
    record("user-tab cookie visible to agent", "session=alice" in t, t.strip()[-60:])
    r = mcp.call("browser_tabs", {"action": "list"})
    record("agent sees user's tabs", None, mcp.text(r).strip()[:300].replace("\n", " | "))

    # 3. Screenshot: image omitted from response, file saved under /share/playwright
    r = mcp.call("browser_take_screenshot", {})
    kinds = [c.get("type") for c in r["content"]]
    files = glob.glob(f"{OUT}/*.png")
    record("screenshot omits image content", r["ok"] and "image" not in kinds, f"content types={kinds}")
    record("screenshot file in /share/playwright", bool(files), ", ".join(files))
    record("screenshot response text", None, mcp.text(r).strip()[:200].replace("\n", " | "))

    # 4. Upload a sibling app's file from /share; reject outside /share
    mcp.call("browser_navigate", {"url": f"{SITE}/upload"})
    mcp.call("browser_click", {"target": "#f"})
    r = mcp.call("browser_file_upload", {"paths": ["/share/code-interpreter/abc/data.csv"]})
    _, t = evaluate("() => document.getElementById('out').textContent")
    record("upload from /share", "data.csv:8" in t, f"upload ok={r['ok']} -> {t.strip()[-40:]!r}")
    mcp.call("browser_click", {"target": "#f"})
    r = mcp.call("browser_file_upload", {"paths": ["/etc/hostname"]})
    _, t = evaluate("() => document.getElementById('out').textContent")
    record("upload outside /share refused", "hostname" not in t,
           f"ok={r['ok']} {mcp.text(r).strip()[:150]!r} / out={t.strip()[-40:]!r}")
    mcp.call("browser_file_upload", {})  # cancel any open chooser

    # 5. R4: where can explicit filenames write?
    for fn in ["code-interpreter/abc/evil.png", "../tmp/evil1.png", "/tmp/evil2.png", "/data/evil3.png"]:
        r = mcp.call("browser_take_screenshot", {"filename": fn})
        hits = [p for p in ["/share/code-interpreter/abc/evil.png", "/tmp/evil1.png", "/tmp/evil2.png",
                            "/data/evil3.png", f"{OUT}/code-interpreter/abc/evil.png"] if os.path.exists(p)]
        record(f"R4 filename={fn}", None, f"ok={r['ok']} files now={hits} msg={mcp.text(r).strip()[:120]!r}")

    # 6. R1: slow navigation under a 5 s read timeout (pre-#192414 HA)
    r = mcp.call("browser_navigate", {"url": f"{SITE}/slow"}, read_timeout=5)
    record("R1 slow(8s) nav with 5s read timeout", r["ok"],
           f"err={r['error']} notifications={len(r['notifications'])} elapsed={r['elapsed']:.1f}s")
    r = mcp.call("browser_navigate", {"url": f"{SITE}/slow"}, read_timeout=30)
    record("R1 slow(8s) nav with 30s read timeout", r["ok"],
           f"first_byte={r['first_byte']:.1f}s elapsed={r['elapsed']:.1f}s notifications={len(r['notifications'])}")

    # 7. Token cost of a real page
    r = mcp.call("browser_navigate", {"url": "https://en.wikipedia.org/wiki/Home_Assistant"})
    record("navigate response size (wikipedia)", None, f"{len(mcp.text(r))} chars ok={r['ok']}")
    r = mcp.call("browser_snapshot", {})
    record("snapshot response size (wikipedia)", None, f"{len(mcp.text(r))} chars")
    r = mcp.call("browser_snapshot", {"depth": 6})
    record("snapshot depth=6 size", None, f"{len(mcp.text(r))} chars")

    # 8. noVNC
    start("x11vnc", ["x11vnc", "-display", ":99", "-localhost", "-rfbport", "5900", "-shared", "-forever",
                     "-nopw", "-quiet"])
    wait_port(5900)
    web = "/usr/share/novnc" if os.path.isdir("/usr/share/novnc") else "/usr/share/webapps/novnc"
    start("websockify", ["websockify", "--web", web, "8098", "127.0.0.1:5900"])
    wait_port(8098)
    try:
        page = urllib.request.urlopen("http://127.0.0.1:8098/vnc_lite.html", timeout=5).status
        status, greeting = ws_rfb_check()
        record("noVNC page + websocket -> RFB", page == 200 and greeting.startswith("RFB"),
               f"page={page} ws={status!r} greeting={greeting.strip()!r} web={web}")
    except Exception as e:  # noqa: BLE001
        record("noVNC page + websocket -> RFB", False, repr(e))

    # 9. Memory
    record("memory PSS MB (wikipedia loaded)", None, json.dumps(pss_by_name()))

    # 10. Chromium restart: login persists, MCP reconnects
    stop("chromium")
    start_chrome()
    r = mcp.call("browser_navigate", {"url": f"{SITE}/whoami"})
    if not r["ok"]:
        record("MCP after chromium restart (1st call)", False, str(r["error"])[:200])
        r = mcp.call("browser_navigate", {"url": f"{SITE}/whoami"})
    record("MCP reconnects after chromium restart", r["ok"], str(r["error"])[:200] if not r["ok"] else "")
    if not r["ok"]:
        stop("mcp")
        start_mcp()
        r = mcp.call("browser_navigate", {"url": f"{SITE}/whoami"})
        record("MCP works after MCP restart", r["ok"], str(r["error"])[:200] if not r["ok"] else "")
    _, t = evaluate("() => document.body.innerText")
    record("cookie persists across chromium restart (SIGTERM)", "session=alice" in t, t.strip()[-60:])

    # 11. Drop llvm21-libs: render + screenshot still work?
    stop("chromium")
    before = subprocess.run(["du", "-sm", "/usr"], capture_output=True, text=True).stdout.split()[0]
    rdeps = subprocess.run(["apk", "info", "-r", "llvm21-libs"], capture_output=True, text=True).stdout
    for p in glob.glob("/usr/lib/libLLVM*"):
        os.remove(p)
    after = subprocess.run(["du", "-sm", "/usr"], capture_output=True, text=True).stdout.split()[0]
    record("llvm removal size", None, f"/usr {before}MB -> {after}MB; required by: "
           + " ".join(rdeps.split()[4:]))
    ok = start_chrome()
    r = mcp.call("browser_navigate", {"url": "https://en.wikipedia.org/wiki/Raspberry_Pi"})
    if not r["ok"]:
        r = mcp.call("browser_navigate", {"url": "https://en.wikipedia.org/wiki/Raspberry_Pi"})
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    s = mcp.call("browser_take_screenshot", {"fullPage": False})
    files = glob.glob(f"{OUT}/*.png")
    size = os.path.getsize(files[0]) if files else 0
    _, gl = evaluate("() => !!document.createElement('canvas').getContext('webgl')")
    log = open("/tmp/chromium.log").read()
    errs = [ln for ln in log.splitlines()[-400:] if "LLVM" in ln or "gallium" in ln.lower() or "dri" in ln.lower()]
    record("without llvm: chromium + nav + screenshot", ok and r["ok"] and s["ok"] and size > 20000,
           f"png={size}B webgl={gl.strip()[-20:]!r} llvm-log-lines={errs[:3]}")
    if files:
        shutil.copy(files[0], "/poc/out-nollvm.png")

    for name in list(PROCS):
        stop(name)
    print("\n=== SUMMARY ===")
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL' if ok is False else 'INFO':4} | {name} | {detail}")


if __name__ == "__main__":
    main()
