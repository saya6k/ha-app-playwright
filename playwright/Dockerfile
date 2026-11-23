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

# ---- App -------------------------------------------------------------------
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The base image is labeled io.hass.type=base; Supervisor's own value is "app".
LABEL io.hass.type="app"

# chromium pulls mesa → llvm21-libs (157 MB). It cannot be dropped: Xvfb links
# libGL → libgallium → libLLVM at load time (Phase 0 PoC).
RUN apk add --no-cache chromium nodejs python3 xvfb

COPY --from=mcp-build /opt/playwright-mcp /opt/playwright-mcp
COPY --from=gate-build /opt/venv /opt/venv

COPY rootfs /
RUN rm -rf /opt/gate/tests /opt/gate/conftest.py \
 && find /etc/s6-overlay/s6-rc.d -type f \( -name run -o -name finish -o -name up \) -exec chmod a+x {} \; \
 && find /etc/s6-overlay/s6-rc.d -type f -name type -exec chmod 644 {} \;

WORKDIR /
