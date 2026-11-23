# ha-app-playwright

Source repo for the **Browser** Home Assistant app — a Chromium browser
driven by Playwright MCP, supplied to Assist conversation agents over MCP
(streamable HTTP), with an Ingress panel for logging in to sites.

Install it from the [saya6k/ha-apps](https://github.com/saya6k/ha-apps)
catalog. This repo carries the source, Dockerfile, and CI; the catalog carries
the metadata.

- App docs: [playwright/DOCS.md](playwright/DOCS.md)
- Design probes behind the gate: [poc/RESULTS.md](poc/RESULTS.md)

## Release flow

1. Merge to `main` — release-drafter updates the draft.
2. Publish the draft → `build.yml` pushes `ghcr.io/saya6k/app-playwright:{ver}`.
3. The build dispatches to ha-apps, which opens a version-bump PR.

## Trademarks

"Playwright" is a trademark of Microsoft. This app is an independent
community project and is not affiliated with or endorsed by Microsoft.
