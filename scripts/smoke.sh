#!/usr/bin/env bash
# Smoke test the built app image: starts it like the Supervisor would (no
# Supervisor, so discovery skips), serves a local test site inside the
# container, and runs smoke_client.py there with HA-style per-call sessions.
set -euo pipefail

IMAGE="${1:?usage: smoke.sh <image-tag>}"
NAME=playwright-smoke
HERE="$(cd "$(dirname "$0")" && pwd)"

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "--- container logs (tail) ---"
    docker logs "$NAME" 2>&1 | tail -60 || true
  fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" \
  -v "${HERE}/ci-options.json:/data/options.json:ro" \
  -v "${HERE}:/smoke:ro" "$IMAGE" >/dev/null

echo "waiting for the gate …"
for _ in $(seq 1 60); do
  if docker exec "$NAME" curl -sf -m 2 -o /dev/null -X POST http://127.0.0.1:8099/mcp \
       -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
       -d '{"jsonrpc":"2.0","id":0,"method":"ping"}' 2>/dev/null; then
    break
  fi
  sleep 2
done

docker exec -d "$NAME" python3 /smoke/site.py
sleep 1
docker exec "$NAME" python3 /smoke/smoke_client.py
if [ -n "${SMOKE_OUT:-}" ]; then
  docker cp "$NAME:/share/playwright/ko.png" "${SMOKE_OUT}/ko.png" >/dev/null && echo "copied ko.png to ${SMOKE_OUT}"
fi

echo "image size: $(docker image inspect "$IMAGE" --format '{{.Size}}' | awk '{printf "%.0f MB", $1/1000000}')"
