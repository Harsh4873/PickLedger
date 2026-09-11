# PickLedger refresh and production upcheck

Run the production refresh against `Harsh4873/pickledger`, branch `main`.

## Schedule and execution

The `daily-refresh.yml` coordinator starts every day at **6:30 a.m. and 1 p.m. America/Chicago**, including daylight saving changes. It runs the model, player-prop, and external-feed workflows sequentially, then requests Pages deployment. These are refresh start times; deployment follows generation and readiness checks. GitHub schedules can arrive late.

Use `gh workflow run daily-refresh.yml --ref main` for a full manual refresh. Individual writers remain manually dispatchable for focused repairs. Do not restore separate overlapping schedules on the three writers: they share `pick-cache-writer`, whose pending slot can be replaced by another pending writer.

The freshness guard and the local backup clock check the same two Central windows. Check both Daily Refresh and Model Cache Refresh runs before recovering a missing window. Wait for an active coordinator instead of dispatching competing writers. A missed window recovers the full coordinator; a current window with specific failed core models retries those models only. Retain the 20-minute cooldown and three-attempt limit per window.

## Preflight

- Locate the checkout by its `Harsh4873/pickledger` origin; read its `AGENTS.md`. Use the repository root for commands.
- Compute `TARGET_DATE` once with `TZ=America/Chicago date +%F`.
- Fetch and fast-forward `main` safely. Preserve unrelated changes; use an isolated checkout if needed.
- Verify `gh api user --jq .login` returns `Harsh4873` and verify the matching Git identity before a commit or local publisher.
- Review source, committed JSON, tests, and Actions. Never open production, a browser preview, or rendered output to verify. Scrapers may use their internal headless transports.
- Capture exact workflow run IDs and inspect their jobs. Wait for an active heavy writer instead of creating duplicates.

## Football picks and research feeds

Both `nfl` and `cfb` are required in-house models. They must be current and `ok`, including official off-days. Their serving buckets and picks use `shadow_mode=false`. Keep in-house **BET, LEAN, and PASS** picks public, with the same decision filters in rankings. PASS rows carry zero stake; do not hide them or promote them into bets to satisfy a count.

A resolved empty slate is a valid off-day. CFB can also have zero model rows when opponents are unsupported, such as an FBS–FCS matchup; report the coverage reason. Missing market prices must never be fabricated.

Validate these eight football feed buckets separately:

- `sportytrader_cfb`, `sportytrader_nfl`
- `sportsgambler_cfb`, `sportsgambler_nfl`
- `scores24_cfb`, `scores24_nfl`
- `forebet_cfb`, `forebet_nfl`

All scraped provider picks remain **research-only: PASS, zero units**, visible in Research and source health. Preserve source attribution and the original source decision. Provider forecasts need not exist for every official game. Distinguish a resolved empty slate, no published prediction, an unmatched prediction, a transport failure, and a stale bucket.

The external-feed workflow defaults include SportyTrader, SportsGambler, Forebet MLS/MLB/WNBA/CFB/NFL, and TennisTonic; its sports include CFB and NFL. Do not narrow the defaults to only one provider. SportsGambler football uses full team names in article URLs when card names are shortened. Forebet requires official matchup and kickoff matching; analytics scripts alone are not evidence of a blocked page.

## Local publishers

Scores24 still needs the existing local publisher; GitHub-hosted Actions cannot reliably fetch it. From a local checkout, run:

```sh
scripts/scrapers/scores24_publish_local.sh --date "$TARGET_DATE"
scripts/scrapers/forebet_publish_local.sh --date "$TARGET_DATE"
scripts/scrapers/tennis_publish_local.sh --date "$TARGET_DATE"
```

Safely sync `main` after each publisher. Scores24 defaults include MLB/WNBA plus optional CFB/NFL. Forebet defaults include MLB/WNBA/MLS/CFB/NFL. Tennis retains TennisTonic/Scores24Tennis. A failed optional football or tennis feed must not block other published picks. Preserve the most recent successful same-day rows after a failed retry and expose the failure in source health.

Scores24 CFB/NFL are scraped after the MLB+WNBA completeness gate. They stay off `REQUIRED_SCORES24_FEED_KEYS` (soft-fail, like tennis). Morning and afternoon local publishes behave as follows:

- **Required MLB+WNBA:** still use the full-slate gate and the longer block-retry budget. Incomplete MLB or WNBA still refuses the commit.
- **Optional CFB/NFL success:** today's matched editorial picks publish with `ok` / `refreshStatus=ok` and today's date. A resolved empty official slate is a dated off-day `ok` bucket.
- **Optional timeout or hang:** each optional feed has a hard timeout (default 180s via `SCORES24_OPTIONAL_FEED_TIMEOUT_SECONDS`) that kills the Camoufox process group. That wait cannot stall MLB+WNBA publish beyond the timeout. If `SCORES24_CHECKPOINT_DIR` already holds today's matched CFB/NFL picks, those rows publish as today's incomplete bucket (`ok=false`, `refreshStatus=error`, `lastAttemptDate=today`). If there is no same-day checkpoint, yesterday's snapshot keeps yesterday's date; only `lastAttemptDate` / `lastError` move to today. Never stamp yesterday's one-pick CFB bucket as today.
- **Afternoon rerun:** the same checkpoint is the resume point, so a morning timeout can still finish the slate later without refetching already-matched games.

For each provider, report the bucket date, latest attempt status, official matchup count, published count, and missing/unpublished reasons where available. Scores24/Forebet external failures remain non-blocking for Pages when required in-house data is ready. Never classify a missing external feed as proof that no games exist.

## Other models, props, and derived boards

Use the required model and player-prop sets in `scripts/site_upcheck.py`; do not maintain a conflicting copy of those sets here. Keep per-market source labels and existing ranking history epochs. Retired `covers_*` feeds stay excluded.

Keep player props isolated from team picks. Preserve the current ML probability/market-price schema, quality gates, and maximum publication counts. A zero-pick bucket must have a documented off-day, unavailable market, or quality abstention; do not synthesize picks. Report provider blockers separately from internal quality abstentions.

Rebuild parlay cards and Profit Desk after cache changes. Scraped research and model PASS rows must not become staked parlay legs through the refresh.

## Verify and publish

- Run focused smoke tests for changes, frontend tests/typecheck, and `npm run upcheck`.
- If current data is missing, run the matching refresh and inspect exact results. Allow a second attempt only after a relevant fix; do not loop indefinitely.
- Commit and push source fixes and generated data according to `AGENTS.md`.
- Verify the Pages run for the final published commit. A green workflow with a skipped `deploy` job is deferred, not deployed. Confirm that the `deploy` job itself succeeded.
- Report the final commit, deployment result, football feed counts, BET/LEAN/PASS preservation, and any remaining provider blocker. Never claim every source posted a pick when a source has no current forecast.
