"""Minimal streamable-HTTP MCP client that mimics Home Assistant's MCP integration.

HA opens a fresh MCP session for every tool call (initialize -> call -> close),
so each `call()` here does the same, including the closing DELETE.
"""

import http.client
import json
import time

HOST, PORT, PATH = "127.0.0.1", 8099, "/mcp"


class Session:
    def __init__(self, read_timeout):
        self.read_timeout = read_timeout
        self.sid = None
        self.n = 0
        self.first_byte = None

    def _post(self, msg):
        conn = http.client.HTTPConnection(HOST, PORT, timeout=self.read_timeout)
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            headers["mcp-session-id"] = self.sid
        t0 = time.monotonic()
        conn.request("POST", PATH, json.dumps(msg), headers)
        resp = conn.getresponse()
        self.sid = resp.getheader("mcp-session-id") or self.sid
        events = []
        while True:
            line = resp.fp.readline()
            if self.first_byte is None and line:
                self.first_byte = time.monotonic() - t0
            if not line:
                break
            line = line.decode().rstrip("\r\n")
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                events.append(ev)
                if "id" in ev and ev.get("id") == msg.get("id"):
                    break
            elif line.startswith("{"):
                events.append(json.loads(line))
                break
        conn.close()
        return events

    def rpc(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.n += 1
            msg["id"] = self.n
        return self._post(msg)

    def close(self):
        if not self.sid:
            return
        conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
        conn.request("DELETE", PATH, headers={"mcp-session-id": self.sid})
        conn.getresponse().read()
        conn.close()


def call(tool, args, read_timeout=30):
    """One HA-style tool call. Returns dict(ok, content, notifications, elapsed, first_byte, error)."""
    s = Session(read_timeout)
    t0 = time.monotonic()
    try:
        s.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "ha-mimic", "version": "0"}})
        s.rpc("notifications/initialized", notify=True)
        s.first_byte = None
        events = s.rpc("tools/call", {"name": tool, "arguments": args})
        final = [e for e in events if "result" in e or "error" in e]
        notes = [e for e in events if "method" in e]
        res = final[-1] if final else {}
        content = res.get("result", {}).get("content", [])
        return {"ok": "result" in res and not res["result"].get("isError"), "content": content,
                "notifications": notes, "elapsed": time.monotonic() - t0, "first_byte": s.first_byte,
                "error": res.get("error") or (res.get("result") if res.get("result", {}).get("isError") else None)}
    except Exception as e:  # noqa: BLE001 - PoC reports every failure mode
        return {"ok": False, "content": [], "notifications": [], "elapsed": time.monotonic() - t0,
                "first_byte": s.first_byte, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def text(r):
    return "\n".join(c.get("text", "") for c in r["content"] if c.get("type") == "text")
