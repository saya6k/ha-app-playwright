# BUILD_FROM is no longer injected by the Supervisor (>=2026.04.0) — default to
# the multi-arch HA base manifest, pinned to an Alpine version tag.
ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23

# ---- Playwright MCP (npm only in this stage) -------------------------------
FROM ${BUILD_FROM} AS mcp-build
RUN apk add --no-cache nodejs npm
WORKDIR /opt/playwright-mcp
COPY mcp/package.json mcp/package-lock.json ./
# Playwright's bundled browsers are glibc-only; the app uses Alpine's Chromium.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN npm ci --omit=dev --no-audit --no-fund

# ---- Gate venv (pip only in this stage) ------------------------------------
FROM ${BUILD_FROM} AS gate-build
RUN apk add --no-cache python3 py3-pip
COPY rootfs/opt/gate/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
 && /opt/venv/bin/pip uninstall -y pip

# ---- Panel assets (novnc only in this stage) -------------------------------
# Alpine's websockify depends on numpy, openblas, requests, redis and jwcrypto
# (~60 MB). The panel only proxies one websocket and serves files, which works
# without them (numpy just speeds up unmasking keyboard/mouse frames), so only
# the pure-Python package and noVNC's static files are copied.
FROM ${BUILD_FROM} AS panel-build
RUN apk add --no-cache novnc \
 && mkdir -p /out/vendor \
 && cp -r "$(python3 -c 'import websockify, os; print(os.path.dirname(websockify.__file__))')" /out/vendor/ \
 && cp -r /usr/share/novnc /out/novnc

# ---- App -------------------------------------------------------------------
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The base image is labeled io.hass.type=base; Supervisor's own value is "app".
LABEL io.hass.type="app"

# chromium pulls mesa → llvm21-libs (157 MB). It cannot be dropped: Xvfb links
# libGL → libgallium → libLLVM at load time (Phase 0 PoC).
RUN apk add --no-cache chromium nodejs python3 xvfb

# Ingress panel: x11vnc shares :99 over VNC on loopback.
RUN apk add --no-cache x11vnc

COPY --from=mcp-build /opt/playwright-mcp /opt/playwright-mcp
COPY --from=gate-build /opt/venv /opt/venv
COPY --from=panel-build /out/vendor /opt/panel/vendor
COPY --from=panel-build /out/novnc /opt/panel/web/novnc

COPY rootfs /
RUN rm -rf /opt/gate/tests /opt/gate/conftest.py /opt/panel/tests /opt/panel/conftest.py \
 && find /etc/s6-overlay/s6-rc.d -type f \( -name run -o -name finish -o -name up \) -exec chmod a+x {} \; \
 && find /etc/s6-overlay/s6-rc.d -type f -name type -exec chmod 644 {} \;

WORKDIR /
