#!/bin/sh
# Local build + smoke on the linux-test container machine (one machine run at a time):
#   container machine run --root -n linux-test -- sh /Users/saya6k/Projects/ha-app-playwright/scripts/linux-test.sh
set -e
cd /Users/saya6k/Projects/ha-app-playwright
docker build -t app-playwright:dev playwright
bash scripts/smoke.sh app-playwright:dev
