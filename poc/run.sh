#!/bin/sh
# Host entry (linux-test): container machine run --root -n linux-test -- sh /Users/saya6k/Projects/ha-app-playwright/poc/run.sh [poc.py|poc2.py|poc3.py|poc4.py]
docker run --rm -e POC_SCRIPT=${1:-poc.py} -v /Users/saya6k/Projects/ha-app-playwright/poc:/poc -v /Users/saya6k/Projects/ha-app-playwright/scripts:/smoke:ro alpine:3.23 sh /poc/inner.sh
