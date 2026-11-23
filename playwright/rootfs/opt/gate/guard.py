"""Refuse requests from web pages to the MCP endpoint.

The endpoint has no authentication. A page in the app's own Chromium could
reach it through DNS rebinding (same-origin, so CORS does not stop it).
Browsers send Origin on every POST, same-origin included; MCP clients such
as Home Assistant's do not.
"""

from starlette.responses import PlainTextResponse


class RejectBrowserOrigin:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and any(k == b"origin" for k, _ in scope["headers"]):
            await PlainTextResponse("requests from web pages are not allowed", 403)(scope, receive, send)
            return
        await self.app(scope, receive, send)
