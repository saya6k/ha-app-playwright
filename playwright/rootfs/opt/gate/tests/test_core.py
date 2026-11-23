import asyncio

import mcp.types as types
import pytest

from core import Gate
from upstream import UpstreamDied


def text_result(text, is_error=False):
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=is_error)


class FakeUpstream:
    def __init__(self, tabs="### Result\n- 0: (current) [A](http://a/)\n", delay=0.0):
        self.calls = []
        self.tabs = tabs
        self.delay = delay
        self.die_next = False
        self.restarts = 0

    async def list_tools(self):
        return [
            types.Tool(name="browser_snapshot", description="Capture snapshot.", inputSchema={"type": "object"}),
            types.Tool(name="browser_click", description="Click.", inputSchema={"type": "object"}),
        ]

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if self.die_next:
            self.die_next = False
            raise UpstreamDied("child exited")
        if name == "browser_tabs" and args.get("action") == "list":
            return text_result(self.tabs)
        await asyncio.sleep(self.delay)
        return text_result(f"ran {name}")

    async def restart(self):
        self.restarts += 1


def run(coro):
    return asyncio.run(coro)


async def no_notify(_msg):
    pass


def test_list_tools_passthrough_and_snapshot_note():
    tools = run(Gate(FakeUpstream()).list_tools())
    assert [t.name for t in tools] == ["browser_snapshot", "browser_click"]
    snap = tools[0]
    assert snap.description.startswith("Capture snapshot.")
    assert "depth" in snap.description


def test_single_tab_skips_select():
    up = FakeUpstream()
    run(Gate(up).call("browser_click", {"target": "e1"}, no_notify))
    assert up.calls == [("browser_tabs", {"action": "list"}), ("browser_click", {"target": "e1"})]


def test_multiple_tabs_selects_current_before_action():
    up = FakeUpstream(tabs="### Result\n- 0: [U](http://u/)\n- 1: (current) [A](http://a/)\n")
    run(Gate(up).call("browser_click", {"target": "e1"}, no_notify))
    assert up.calls == [
        ("browser_tabs", {"action": "list"}),
        ("browser_tabs", {"action": "select", "index": 1}),
        ("browser_click", {"target": "e1"}),
    ]


def test_unparseable_tabs_still_runs_action():
    up = FakeUpstream(tabs="something else")
    res = run(Gate(up).call("browser_click", {"target": "e1"}, no_notify))
    assert up.calls[-1] == ("browser_click", {"target": "e1"})
    assert not res.isError


def test_navigation_does_not_touch_tabs():
    up = FakeUpstream()
    run(Gate(up).call("browser_navigate", {"url": "http://x/"}, no_notify))
    assert up.calls == [("browser_navigate", {"url": "http://x/"})]


def test_args_are_rewritten():
    up = FakeUpstream()
    run(Gate(up).call("browser_snapshot", {"filename": "../../etc/x.yml"}, no_notify))
    assert up.calls == [("browser_snapshot", {"filename": "playwright/x.yml", "depth": 6})]


def test_long_text_truncated():
    up = FakeUpstream()

    async def big(name, args):
        return text_result("x" * 50)

    up.call_tool = big
    res = run(Gate(up, max_chars=20).call("browser_navigate", {}, no_notify))
    assert res.content[0].text.startswith("x" * 20)
    assert "20 of 50" in res.content[0].text


def test_image_content_dropped_from_result():
    up = FakeUpstream()

    async def with_image(name, args):
        return types.CallToolResult(content=[
            types.TextContent(type="text", text="saved"),
            types.ImageContent(type="image", data="AAAA", mimeType="image/png"),
        ])

    up.call_tool = with_image
    res = run(Gate(up).call("browser_navigate", {}, no_notify))
    assert [c.type for c in res.content] == ["text"]


def test_heartbeat_while_waiting():
    up = FakeUpstream(delay=0.35)
    beats = []

    async def notify(msg):
        beats.append(msg)

    run(Gate(up, heartbeat_s=0.1).call("browser_navigate", {"url": "http://x/"}, notify))
    assert len(beats) >= 2


def test_heartbeat_failure_does_not_fail_call():
    async def broken(_msg):
        raise RuntimeError("stream gone")

    res = run(Gate(FakeUpstream(delay=0.25), heartbeat_s=0.05).call("browser_navigate", {}, broken))
    assert not res.isError


def test_calls_are_serialised():
    up = FakeUpstream(delay=0.05)
    order = []
    orig = up.call_tool

    async def tracked(name, args):
        order.append(("start", args.get("n")))
        res = await orig(name, args)
        order.append(("end", args.get("n")))
        return res

    up.call_tool = tracked
    gate = Gate(up)

    async def both():
        await asyncio.gather(gate.call("browser_navigate", {"n": 1}, no_notify),
                             gate.call("browser_navigate", {"n": 2}, no_notify))

    run(both())
    assert order in ([("start", 1), ("end", 1), ("start", 2), ("end", 2)],
                     [("start", 2), ("end", 2), ("start", 1), ("end", 1)])


def test_dead_upstream_restarts_and_reports_lost_state():
    up = FakeUpstream()
    up.die_next = True
    gate = Gate(up)
    res = run(gate.call("browser_navigate", {"url": "http://x/"}, no_notify))
    assert res.isError
    assert "browser_restarted" in res.content[0].text
    assert up.restarts == 1
    res2 = run(gate.call("browser_navigate", {"url": "http://x/"}, no_notify))
    assert not res2.isError


@pytest.mark.parametrize("tool", ["browser_click", "browser_navigate"])
def test_upstream_error_result_passes_through(tool):
    up = FakeUpstream()

    async def err(name, args):
        if name == "browser_tabs":
            return text_result(up.tabs)
        return text_result("### Error\nboom", is_error=True)

    up.call_tool = err
    res = run(Gate(up).call(tool, {}, no_notify))
    assert res.isError and "boom" in res.content[0].text
