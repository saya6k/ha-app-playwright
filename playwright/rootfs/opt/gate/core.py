"""Gate logic between Home Assistant's per-call MCP sessions and one upstream session."""

import asyncio
import contextlib
import logging

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


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=True)


def _text(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))


class Gate:
    def __init__(self, upstream, *, max_chars: int = MAX_CHARS, heartbeat_s: float = HEARTBEAT_S):
        self.upstream = upstream
        self.max_chars = max_chars
        self.heartbeat_s = heartbeat_s
        self._lock = asyncio.Lock()

    async def list_tools(self) -> list[types.Tool]:
        tools = []
        for tool in await self.upstream.list_tools():
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
            try:
                if rewrite.needs_front(name):
                    await self._bring_current_tab_to_front()
                result = await self.upstream.call_tool(name, rewrite.rewrite_args(name, args))
            except UpstreamDied as e:
                log.warning("[gate] %s: upstream died (%s)", name, e)
                await self.upstream.restart()
                return _error(RESTARTED)
        return self._shape(result)

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
