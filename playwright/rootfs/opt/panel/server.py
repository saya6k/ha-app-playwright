"""Ingress panel: noVNC page + VNC websocket + status/reset API on :8098.

Built on websockify (vendored from Alpine's package in the image build) so the
panel needs no extra Python packages. Runs with the system python3.
"""

import json
import os
import subprocess
import sys
import warnings

HERE = os.path.dirname(__file__)
sys.path[:0] = [HERE, os.path.join(HERE, "vendor")]  # websockify is vendored without its heavy deps
warnings.filterwarnings("ignore", message="no 'numpy' module")

from websockify.websocketproxy import ProxyRequestHandler, WebSocketProxy  # noqa: E402

import logic  # noqa: E402

WEB_ROOT = "/opt/panel/web"
S6_SVC = "/command/s6-svc"
CHROMIUM_SERVICE = "/run/service/chromium"


class PanelHandler(ProxyRequestHandler):
    def handle(self):
        # VNC has no password: refuse anyone but the Ingress gateway before
        # reading a single request line.
        if not logic.client_allowed(self.client_address[0]):
            try:
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.request.close()
            return
        super().handle()

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/status":
            return self._json(200, logic.status())
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/reset-profile":
            return self._json(404, {"error": "not_found"})
        if not logic.csrf_ok(self.headers):
            return self._json(403, {"error": "missing X-Requested-With header"})
        user = self.headers.get("X-Remote-User-Name", "unknown")
        self.log_message("reset-profile requested by %s", user)
        subprocess.run([S6_SVC, "-wD", "-T", "15000", "-d", CHROMIUM_SERVICE], check=False)
        removed = logic.wipe_profile()
        subprocess.run([S6_SVC, "-u", CHROMIUM_SERVICE], check=False)
        return self._json(200, {"reset": True, "removed": removed})

    def log_message(self, fmt, *args):
        sys.stderr.write("[panel] " + (fmt % args) + "\n")


if __name__ == "__main__":
    WebSocketProxy(
        RequestHandlerClass=PanelHandler,
        listen_host="0.0.0.0",
        listen_port=8098,
        target_host="127.0.0.1",
        target_port=5900,
        web=WEB_ROOT,
        file_only=True,
    ).start_server()
