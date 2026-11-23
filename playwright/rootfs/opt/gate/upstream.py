"""One long-lived stdio session to Playwright MCP.

Playwright MCP keeps the current tab, modal state (file chooser, dialogs) and
snapshot refs per MCP session, while Home Assistant opens a new session for
every tool call (Phase 0 PoC). Holding a single upstream session for the life
of the app keeps that state between calls.
"""

import asyncio
import contextlib
import logging
from datetime import timedelta

import anyio
from mcp import ClientSession, McpError, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger("gate")
CALL_TIMEOUT = timedelta(seconds=120)


class UpstreamDied(Exception):
    """The Playwright MCP child is gone; its tab and modal state are lost."""


class StdioUpstream:
    def __init__(self, params: StdioServerParameters):
        self.params = params
        self._session: ClientSession | None = None
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._own(ready, self._stop))
        await ready

    async def _own(self, ready: asyncio.Future, stop: asyncio.Event) -> None:
        # The stdio client's task group must be entered and exited in one task.
        try:
            async with stdio_client(self.params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                ready.set_result(None)
                log.info("[gate] playwright-mcp session ready")
                await stop.wait()
        except Exception as e:  # noqa: BLE001 — any failure means the child is unusable
            if not ready.done():
                ready.set_exception(e)
            else:
                log.warning("[gate] playwright-mcp session ended: %r", e)
        finally:
            self._session = None

    async def close(self) -> None:
        if self._stop:
            self._stop.set()
        if self._task:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, 10)
        self._task = None

    async def restart(self) -> None:
        log.warning("[gate] restarting playwright-mcp")
        await self.close()
        await self.start()

    def _live(self) -> ClientSession:
        if self._session is None or self._task is None or self._task.done():
            raise UpstreamDied("playwright-mcp is not running")
        return self._session

    async def list_tools(self):
        try:
            return (await self._live().list_tools()).tools
        except (McpError, anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream) as e:
            raise UpstreamDied(str(e)) from e

    async def call_tool(self, name: str, args: dict):
        session = self._live()
        try:
            return await session.call_tool(name, args, read_timeout_seconds=CALL_TIMEOUT)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream) as e:
            raise UpstreamDied(str(e)) from e
        except McpError as e:
            if self._session is None or (self._task and self._task.done()):
                raise UpstreamDied(str(e)) from e
            raise
