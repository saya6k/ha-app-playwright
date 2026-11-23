"""Smoke test run inside the app container (stdlib only, Python 3.12).

Every tool call mimics Home Assistant's MCP client: a fresh session
(initialize → call → DELETE), so each check exercises the gate's
single upstream session.
"""

import glob
import http.client
import json
import os
import re
import signal
import sys
import time
import urllib.request

SITE = "http://127.0.0.1:8000"
CSV = "/share/smoke/data.csv"
FAILED = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail and not ok else ''}", flush=True)
    if not ok:
        FAILED.append(name)


class Session:
    def __init__(self, read_timeout=30, host="127.0.0.1:8099"):
        self.read_timeout, self.host, self.sid, self.n = read_timeout, host, None, 0

    def rpc(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            self.n += 1
            msg["id"] = self.n
        conn = http.client.HTTPConnection("127.0.0.1", 8099, timeout=self.read_timeout)
        headers = {"Host": self.host, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.sid:
            headers["mcp-session-id"] = self.sid
        conn.request("POST", "/mcp", json.dumps(msg), headers)
        resp = conn.getresponse()
        self.sid = resp.getheader("mcp-session-id") or self.sid
        events = []
        while line := resp.fp.readline():
            line = line.decode().strip()
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
                if events[-1].get("id") == msg.get("id") and not notify:
                    break
            elif line.startswith("{"):
                events.append(json.loads(line))
                break
        conn.close()
        return events

    def close(self):
        if self.sid:
            conn = http.client.HTTPConnection("127.0.0.1", 8099, timeout=10)
            conn.request("DELETE", "/mcp", headers={"mcp-session-id": self.sid})
            conn.getresponse().read()
            conn.close()


def ha_session(read_timeout=30, host="127.0.0.1:8099"):
    s = Session(read_timeout, host)
    s.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "smoke", "version": "0"}})
    s.rpc("notifications/initialized", notify=True)
    return s


def call(tool, args=None, read_timeout=30):
    """One HA-style call → (ok, text, content types, notification count, error)."""
    s = ha_session(read_timeout)
    try:
        events = s.rpc("tools/call", {"name": tool, "arguments": args or {}})
    except Exception as e:  # noqa: BLE001 — a timeout is a result here
        return False, "", [], 0, f"{type(e).__name__}: {e}"
    finally:
        try:
            s.close()
        except OSError:
            pass
    res = next((e for e in events if "result" in e or "error" in e), {})
    content = res.get("result", {}).get("content", [])
    text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
    notes = sum(1 for e in events if e.get("method") == "notifications/message")
    ok = "result" in res and not res["result"].get("isError")
    return ok, text, [c.get("type") for c in content], notes, res.get("error")


def evaluate(fn):
    return call("browser_evaluate", {"function": fn})[1]


def user_opens_tab(path):
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:9222/json/new?{SITE}{path}", method="PUT"))
    time.sleep(1.5)


def main():
    os.makedirs(os.path.dirname(CSV), exist_ok=True)
    with open(CSV, "w") as f:
        f.write("a,b\n1,2\n")

    s = ha_session(host="abcd1234-playwright:8099")
    tools = next(e for e in s.rpc("tools/list", {}) if "result" in e)["result"]["tools"]
    s.close()
    names = {t["name"] for t in tools}
    check("tools/list via a non-localhost Host header", {"browser_navigate", "browser_click",
                                                          "browser_file_upload"} <= names, str(sorted(names)))
    snap = next((t for t in tools if t["name"] == "browser_snapshot"), {})
    check("snapshot description mentions the default depth", "depth=6" in snap.get("description", ""))

    call("browser_navigate", {"url": f"{SITE}/upload"})
    call("browser_click", {"target": "#f"})
    ok, text, *_ = call("browser_file_upload", {"paths": [CSV]})
    check("file chooser survives across HA sessions", "data.csv:8" in evaluate(
        "() => document.getElementById('out').textContent"), text[:200])

    call("browser_navigate", {"url": f"{SITE}/form"})
    snapshot = call("browser_snapshot")[1]
    m = re.search(r"textbox[^\n]*\[ref=(\w+)\]", snapshot)
    ok, text, *_ = call("browser_type", {"target": m.group(1) if m else "missing", "element": "query",
                                          "text": "refs", "submit": True})
    check("snapshot ref survives across HA sessions", "RESULT:refs" in evaluate("() => document.body.innerText"),
          text[:200])

    call("browser_navigate", {"url": f"{SITE}/upload"})
    user_opens_tab("/setcookie")
    ok, text, *_ = call("browser_click", {"target": "#f"})
    call("browser_file_upload", {"paths": [CSV]})
    check("agent acts in its tab while a user tab is in front", ok and "data.csv:8" in evaluate(
        "() => document.getElementById('out').textContent"), text[:200])

    ok, text, _, notes, err = call("browser_navigate", {"url": f"{SITE}/slow"}, read_timeout=5)
    check("8 s navigation under a 5 s read timeout (heartbeat)", ok and notes >= 2, f"notes={notes} err={err}")

    ok, text, kinds, *_ = call("browser_take_screenshot", {"filename": "../code-interpreter/x/evil.png"})
    check("screenshot filename confined to /share/playwright",
          os.path.exists("/share/playwright/evil.png") and not glob.glob("/share/code-interpreter/x/*"), text[:200])
    check("no image content in results", ok and "image" not in kinds, str(kinds))
    check("screenshot is not blank", os.path.getsize("/share/playwright/evil.png") > 5000
          if os.path.exists("/share/playwright/evil.png") else False)

    call("browser_navigate", {"url": f"{SITE}/big"})
    ok, text, *_ = call("browser_snapshot", {"depth": 50})
    check("large result truncated with a hint", ok and len(text) < 12500 and "Truncated by the add-on" in text,
          f"len={len(text)}")

    for pid in [p.split("/")[2] for p in glob.glob("/proc/[0-9]*/comm")]:
        try:
            if open(f"/proc/{pid}/comm").read().strip() in ("chromium", "chromium-browser"):
                os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            pass
    time.sleep(5)
    results = [call("browser_navigate", {"url": f"{SITE}/whoami"}) for _ in range(3)]
    oks = [r[0] for r in results]
    check("recovers after Chromium restart", oks[-1], " / ".join(r[1][:120] for r in results))
    check("login cookie kept across Chromium restart", "session=alice" in evaluate("() => document.body.innerText"))

    print(f"\n{len(FAILED)} failed" if FAILED else "\nsmoke OK")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
