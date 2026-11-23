"""Browser app gate — streamable HTTP MCP server in front of Playwright MCP (stdio).

Home Assistant's MCP client opens a fresh session per tool call; this server
is stateless towards it and forwards every call to one long-lived upstream
session (see upstream.py and core.py).
"""

import contextlib
import logging
import os

import mcp.types as types
import uvicorn
from mcp import StdioServerParameters
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route

import options
from core import Gate
from upstream import StdioUpstream

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("gate")

opts = options.load()
upstream = StdioUpstream(StdioServerParameters(
    command="node", args=options.upstream_argv(opts), cwd="/share", env=options.child_env(dict(os.environ))))
gate = Gate(upstream)
server = Server("Browser")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return await gate.list_tools()


@server.call_tool(validate_input=False)  # Playwright MCP validates its own arguments
async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    ctx = server.request_context

    async def notify(message: str) -> None:
        await ctx.session.send_log_message("debug", message, logger="gate", related_request_id=ctx.request_id)

    return await gate.call(name, arguments or {}, notify)


manager = StreamableHTTPSessionManager(app=server, stateless=True)


@contextlib.asynccontextmanager
async def lifespan(_app):
    await upstream.start()
    log.info("[gate] listening on 0.0.0.0:8099 (/mcp)")
    async with manager.run():
        yield
    await upstream.close()


app = Starlette(routes=[Route("/mcp", endpoint=StreamableHTTPASGIApp(manager))], lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8099, log_level="warning")
