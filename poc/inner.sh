#!/bin/sh
# Runs inside alpine:3.23. Installs the candidate runtime and executes poc.py.
set -e
apk add --no-cache chromium nodejs npm python3 xvfb x11vnc novnc >/tmp/apk.log 2>&1 || { tail -5 /tmp/apk.log; exit 1; }
echo "chromium $(apk info -e -v chromium) | node $(node --version) | $(apk info -v novnc 2>/dev/null | tr '\n' ' ')"
mkdir -p /pw && cd /pw && npm i --silent --no-fund --no-audit @playwright/mcp@0.0.86 >/dev/null 2>&1
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
mkdir -p /data /share
python3 /poc/${POC_SCRIPT:-poc.py}
