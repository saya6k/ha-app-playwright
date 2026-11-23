"""Deterministic local test site for the PoC and the image smoke test (stdlib only)."""

import http.server
import time
import urllib.parse

PAGES = {
    "/form": '<title>Form</title><form action="/result"><input id="q" name="q"><button>Go</button></form>',
    "/upload": (
        '<title>Upload</title><input type="file" id="f">'
        '<p id="out">none</p><script>document.getElementById("f").onchange=e=>{'
        'const f=e.target.files[0];document.getElementById("out").textContent=f.name+":"+f.size}</script>'
    ),
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, headers=()):
        data = f"<!doctype html><meta charset=utf-8>{body}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in PAGES:
            return self._send(PAGES[url.path])
        if url.path == "/result":
            q = urllib.parse.parse_qs(url.query).get("q", [""])[0]
            return self._send(f"<title>Result</title><p id=r>RESULT:{q}</p>")
        if url.path == "/ko":
            return self._send('<title>한글</title><h1 style="font-family:sans-serif">한글 렌더링 확인</h1>'
                              '<p style="font-family:sans-serif;font-size:24px">다람쥐 헌 쳇바퀴에 타고파 — <b>굵게</b></p>')
        if url.path == "/big":
            items = "".join(f'<li><a href="/item/{i}">Item number {i}</a></li>' for i in range(3000))
            return self._send(f"<title>Big</title><ul>{items}</ul>")
        if url.path == "/slow":
            time.sleep(8)
            return self._send("<title>Slow</title><p>SLOW-DONE</p>")
        if url.path == "/setcookie":
            return self._send(
                "<title>Login</title><p>logged in</p>",
                [("Set-Cookie", "session=alice; Max-Age=86400; Path=/")],
            )
        if url.path == "/whoami":
            return self._send(f"<title>Who</title><p id=c>COOKIE:{self.headers.get('Cookie', '')}</p>")
        self.send_error(404)


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
