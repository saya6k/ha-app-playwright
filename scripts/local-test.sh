#!/bin/sh
# Local build + smoke with the Mac's docker (socktainer on Apple container):
#   sh /Users/saya6k/Projects/ha-app-playwright/scripts/local-test.sh
# The image store is shared with other projects: only the previous app-playwright:dev
# image is removed, by its exact ID — never prune or dangling filters.
cd /Users/saya6k/Projects/ha-app-playwright || exit 1
OLD=$(docker image inspect app-playwright:dev -f '{{.Id}}' 2>/dev/null)
docker build -t app-playwright:dev playwright && bash scripts/smoke.sh app-playwright:dev
rc=$?
NEW=$(docker image inspect app-playwright:dev -f '{{.Id}}' 2>/dev/null)
if [ -n "$OLD" ] && [ "$OLD" != "$NEW" ]; then
  docker rmi "$OLD" >/dev/null && echo "removed previous app-playwright image ${OLD#sha256:}"
fi
exit $rc
