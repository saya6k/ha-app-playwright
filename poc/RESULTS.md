# Phase 0 PoC results (2026-11-23, linux-test, alpine:3.23 aarch64)

Scripts: `poc.py` (round 1), `poc2.py` (bg tab, llvm), `poc3.py` (isolated variables), `poc4.py` (per-call vs persistent session).

## Confirmed

| Item | Result |
|---|---|
| Xvfb + headful Chromium + Playwright MCP `--cdp-endpoint` | works |
| User-tab cookie (panel login) visible to agent | yes |
| Cookie persists across Chromium restart (SIGTERM, /data/profile) | yes |
| MCP reconnects after Chromium restart | yes |
| `--image-responses omit` | no image content in the response |
| noVNC page + websockify → x11vnc RFB | works (`novnc` pulls `websockify`) |
| File roots | cwd=/share → roots `/share/playwright`, `/share`; `/tmp`, `/data` refused. **R4: can write into other apps' dirs under /share** |
| R1: 8 s navigation with 5 s read timeout | **fails**: no progress notifications, first byte only at completion |
| Snapshot size (Wikipedia) | full 225,894 chars; `depth=6` 10,188 chars; navigate response 328 chars |
| Memory PSS | chromium 580 MB, node 112, Xvfb 33, websockify 27, x11vnc 7 |
| `llvm21-libs` removal | **not possible**: Xvfb (and TigerVNC Xvnc) link libGL→libgallium→libLLVM at load time. Chromium alone does not need it |
| Background-tab screenshot | default GL: 5.8 KB blank image; **`--disable-gpu`: OK** |

## Key finding: per-call MCP sessions break Playwright MCP

HA opens a new MCP session per tool call. Playwright MCP keeps current tab, modal state (file chooser) and snapshot refs per session.

| | per-call (HA) | one persistent session |
|---|---|---|
| click + file_upload | FAIL (no modal state) | PASS |
| snapshot ref in next call | FAIL ("Ref e3 not found") | PASS (`f1e3`) |
| current tab after user opens a tab | switches to the user's tab | stays on the agent's tab |
| click in background tab | FAIL | FAIL, **PASS after `browser_tabs select`** |

→ A gate is **required**: hold one persistent upstream session (stdio child is enough), expose streamable HTTP to HA, select (bring to front) the agent's tab before actions, heartbeat for R1, cap snapshot depth (R7), normalize `filename` (R4).

Run: `container machine run --root -n linux-test -- sh poc/run.sh poc4.py`. Gate design → SPEC rev 2 §4.9.
