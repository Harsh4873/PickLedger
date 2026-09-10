# Refresh automation reference

Use **two scheduled cloud automations** on repo `Harsh4873/pickledger` / branch
`main`. Enable **GitHub** tool access and keep `gh` authenticated.

Schedule both at **6:30 a.m. and 1:00 p.m. America/Chicago** every day. GitHub
Actions `daily-refresh.yml` uses the same timezone-aware cron. Do not recreate
the former independent UTC writer schedules.

For Codex upkeep: never open the deployed website or a browser. Run source,
tests, and upcheck only. Follow the [current refresh runbook](automations/pickledgerpro-daily-upcheck.md)
for football feed coverage, BET/LEAN/PASS behavior, local publishers, and
deployment verification.

## Production refresh (6:30 a.m. and 1:00 p.m. America/Chicago)

**Instructions:**

```
Production refresh for PickLedger. Never open the deployed site or a browser.

Follow docs/automations/pickledgerpro-daily-upcheck.md.

Sync main. Dispatch gh workflow run daily-refresh.yml --ref main unless a Daily
Refresh coordinator is already queued or running; in that case wait for it.
Do not dispatch overlapping model-cache, player-props, or external-feed writers
while the coordinator owns pick-cache-writer.

After in-house models exist for today, run the local publishers from the repo
root (GitHub-hosted runners cannot scrape these hosts):
  scripts/scrapers/scores24_publish.sh
  scripts/scrapers/forebet_publish.sh
  scripts/scrapers/tennis_publish.sh
Use --date YYYY-MM-DD only when backfilling.

Keep NFL and CFB model picks public with shadow_mode=false and BET/LEAN/PASS
visible on picks and rankings. Scraped provider rows stay research-only at
zero stake. Do not hide PASS picks.

If today's cache is missing or a required model failed, wait for the
coordinator or dispatch it once, then inspect that exact run.

If code fixes are required: test, commit without AI/co-author taglines, push as
the logged-in GitHub user, and dispatch deploy-pages.yml. A green Pages run is
not a deploy unless the deploy job itself executed.

Summarize health, football feed counts, BET/LEAN/PASS preservation, workflow
IDs, and any provider blocker.
```

Scores24 CFB/NFL and Forebet CFB/NFL are in the publisher defaults. GitHub runs
the other available football feeds. All scraped picks stay research-only;
in-house NFL and CFB picks remain public without shadow mode.

## Local backup clock

`scripts/automation/daily_local_refresh.sh` remains the machine-local backup
when GitHub cron is late. It dispatches the Daily Refresh coordinator, then
runs the Cloudflare-blocked local publishers. The macOS freshness guard checks
the same 6:30 a.m. and 1:00 p.m. Central windows.
