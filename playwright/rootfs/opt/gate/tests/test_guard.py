import asyncio

from guard import RejectBrowserOrigin


async def inner(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def status_of(headers, scope_type="http"):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": scope_type, "method": "POST", "path": "/mcp", "headers": headers}
    asyncio.run(RejectBrowserOrigin(inner)(scope, receive, send))
    return sent[0]["status"]


def test_client_without_origin_passes():
    # Home Assistant's MCP client (httpx) sends no Origin header.
    assert status_of([(b"content-type", b"application/json")]) == 200


def test_browser_request_with_origin_refused():
    # Browsers send Origin on every POST, same-origin included, so a DNS
    # rebinding page that reaches 127.0.0.1:8099 is refused.
    assert status_of([(b"origin", b"http://evil.example")]) == 403
