"""Gate logic between Home Assistant's per-call MCP sessions and one upstream session."""

import asyncio
import contextlib
import logging
import time

import mcp.types as types

import rewrite
from upstream import UpstreamDied

log = logging.getLogger("gate")
HEARTBEAT_S = 2.0
MAX_CHARS = 12000
SNAPSHOT_NOTE = (f" This add-on applies depth={rewrite.SNAPSHOT_DEFAULT_DEPTH} when depth is omitted; "
                 "pass a larger depth or a target ref to see deeper parts of the page.")
RESTARTED = ("browser_restarted: the browser automation process restarted and the tab state is lost. "
             "Call browser_navigate again before other browser tools.")
IDLE_RESET = ("The browser was idle, so the add-on closed the earlier tabs and blanked the first one "
              "before this call; refs and pages from before are gone.")


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=True)


def _text(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))


class Gate:
    def __init__(self, upstream, *, max_chars: int = MAX_CHARS, heartbeat_s: float = HEARTBEAT_S,
                 idle_reset_s: float | None = None, clock=time.monotonic):
        self.upstream = upstream
        self.max_chars = max_chars
        self.heartbeat_s = heartbeat_s
        # Home Assistant sends no conversation id, so a long pause stands in
        # for "a new conversation started": its sessions expire after 5 minutes.
        self.idle_reset_s = idle_reset_s
        self.clock = clock
        self._last_call: float | None = None
        self._lock = asyncio.Lock()

    async def list_tools(self) -> list[types.Tool]:
        try:
            upstream_tools = await self.upstream.list_tools()
        except UpstreamDied as e:
            # Home Assistant lists tools before calling one; without a restart
            # here a dead upstream would never get a call that restarts it.
            log.warning("[gate] tools/list: upstream died (%s)", e)
            async with self._lock:
                await self.upstream.restart()
            upstream_tools = await self.upstream.list_tools()
        tools = []
        for tool in upstream_tools:
            if tool.name == "browser_snapshot":
                desc = (tool.description or "").rstrip()
                if desc and desc[-1] not in ".!?":
                    desc += "."  # upstream ends this description without a period
                tool = tool.model_copy(update={"description": desc + SNAPSHOT_NOTE})
            tools.append(tool)
        return tools

    async def call(self, name: str, args: dict, notify) -> types.CallToolResult:
        """Run one tool call; `notify(msg)` keeps the client's stream alive while waiting."""
        task = asyncio.ensure_future(self._call_locked(name, args))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=self.heartbeat_s)
                if done:
                    return task.result()
                with contextlib.suppress(Exception):  # a heartbeat must never fail the call
                    await notify("still working")
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _call_locked(self, name: str, args: dict) -> types.CallToolResult:
        async with self._lock:
            reset = (self.idle_reset_s is not None and self._last_call is not None
                     and self.clock() - self._last_call >= self.idle_reset_s)
            try:
                if reset:
                    await self._reset_tabs()
                if rewrite.needs_front(name):
                    await self._bring_current_tab_to_front()
                result = await self.upstream.call_tool(name, rewrite.rewrite_args(name, args))
            except UpstreamDied as e:
                log.warning("[gate] %s: upstream died (%s)", name, e)
                await self.upstream.restart()
                return _error(RESTARTED)
            finally:
                self._last_call = self.clock()
        if reset:
            result = result.model_copy(update={
                "content": [types.TextContent(type="text", text=IDLE_RESET), *result.content]})
        return self._shape(result)

    async def _reset_tabs(self) -> None:
        # Best effort: a failed close or blank (e.g. a pending dialog) still lets the call run.
        log.info("[gate] idle for %ss: resetting tabs", self.idle_reset_s)
        listing = await self.upstream.call_tool("browser_tabs", {"action": "list"})
        _, count = rewrite.parse_tabs(_text(listing))
        for index in range(count - 1, 0, -1):
            await self.upstream.call_tool("browser_tabs", {"action": "close", "index": index})
        await self.upstream.call_tool("browser_navigate", {"url": "about:blank"})

    async def _bring_current_tab_to_front(self) -> None:
        listing = await self.upstream.call_tool("browser_tabs", {"action": "list"})
        current, count = rewrite.parse_tabs(_text(listing))
        if current is None:
            log.warning("[gate] could not read the current tab from browser_tabs output; not selecting")
        elif count > 1:
            await self.upstream.call_tool("browser_tabs", {"action": "select", "index": current})

    def _shape(self, result: types.CallToolResult) -> types.CallToolResult:
        # Home Assistant hands the whole result to the LLM as JSON text, so an
        # image part would arrive as base64 text. Upstream already omits images;
        # this is the backstop.
        parts = [c for c in result.content if isinstance(c, types.TextContent)]
        texts = rewrite.truncate_texts([c.text for c in parts], self.max_chars)
        content = [c.model_copy(update={"text": t}) for c, t in zip(parts, texts) if t]
        return result.model_copy(update={"content": content})
