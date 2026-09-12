# Architecture

## Production Path

```text
model/feed Actions
      |
      v
committed JSON in data/
      |
      +--> scheduled ESPN auto-grader --> committed results
      |
      +--> Profit Desk builder --> dated live decision artifacts
      |
      v
Vite static build --> GitHub Pages
```

The production viewer is intentionally static. It does not load Firebase, authenticate users, or call the optional Python backend.

## Frontend Contract

- `src/data.ts` loads every dated file listed in `data/model_cache/index.json`.
- `src/data.ts` loads every dated file listed in `data/player_props_cache/index.json`.
  Public buckets are `mlb_player_props`, `nba_player_props`, `wnba_player_props`,
  `nfl_player_props`, and `cfb_player_props`. NFL/CFB boards may be empty
  (off-day or unpriced) without blocking MLB publication.
- `src/data.ts` loads the compact, precomputed files listed in
  `data/profit_desk/index.json`; the browser never invents a profit score from
  raw picks.
- Picks receive deterministic browser IDs so client-side ESPN grades can be stored locally.
- `src/main.ts` renders Home, Search, Rankings, Best Bets, Parlays, and the
  Profit Desk from the same pick collection plus the precomputed desk artifact.
- Rankings are calculated from committed results across all manifest dates.
- Best Bets is the heuristic daily shortlist. Profit Desk is its own tab after
  Parlays: it requires observed, fresh pricing, uses strictly prior evidence,
  applies shrinkage and an uncertainty penalty, and stakes only through its
  qualification lanes (EDGE 1.0u, VALUE 0.5u) — otherwise it publishes 0u and
  says so. See `docs/PROFIT_DESK.md`.
- The Refresh button checks ESPN for pending games and stores temporary local grades. The scheduled grader remains authoritative because it writes results into repository JSON.

## Writer Contract

The model-cache, player-prop, external-feed, and calibration workflows share
the `pick-cache-writer` concurrency group. The high-frequency auto-grade and
closing-line workflows have dedicated groups: GitHub retains only one pending
run per group, so putting them in the heavy-writer queue can silently evict a
pending daily refresh. Those dedicated writers resync `main`, recompute after a
rejected push, and retry; the cache mergers preserve committed grades and game
times when a heavy writer publishes concurrently.

Model and feed refreshes:

1. Generate JSON without Firestore writes.
2. Reset to the latest `main`.
3. Merge the generated payload.
4. Attach real pregame market prices (`scripts/market_odds.py`): both
   moneylines, total over/under prices, spreads, and MLB first-5-innings
   markets from the ESPN scoreboard/prop feeds. Scraped picks keep their own
   executable odds and gain a verifiable two-sided baseline; in-house model
   picks with assumed prices have them replaced by the real observed price
   for their exact market and line. Captured pregame prices are preserved by
   the merge layer once a game goes live.
4. Preserve existing `result`, `start_time`, and `game_start_time` fields for matching picks.
5. Commit and push as the triggering GitHub actor.

For the audited in-house team-model buckets (`mlb_new`, `mlb_first_five`,
`mlb_inning`, `fifa_world_cup`, and `nba_summer`), the model refresh also
stores an immutable first-publication/revision record in
`data/calibration/team_prop_pregame_ledger.json`. Certification requires a
trusted per-pick publication timestamp earlier than the scheduled start.
Legacy cache rows remain visible but are not promoted into certified evidence.

The certified ledger separates three concepts:

- forecast evaluation, which includes certified PASS/LEAN/BET outcomes;
- market/ROI evaluation, which additionally requires observed executable odds;
- calibration training, which additionally requires explicit eligibility and
  continues to exclude FIFA.

`scripts/team_prop_model_evaluator.py` reads only this ledger and reports
chronological metrics by model version and market, including Brier score, log
loss, calibration bins, verified-price ROI, market benchmarks, and retained
feature-contract coverage.

The universal probability calibrator has a versioned training contract. Rows
whose probabilities are owned by the player-prop ML policy remain available
for evaluation but are explicitly ineligible to train the separate shared
Platt layer. A training-contract change invalidates the prior mapping and
forces evaluation against a clean identity champion.

`scripts/cache_manifest.py` updates the dated-cache manifest whenever model or feed caches are written or merged.

## NFL/CFB player props

NFL player props use the ESPN posted-market consensus path. CFB uses the public
Action Network scoreboard, book registry and two-sided player markets, joined to
ESPN by both teams, kickoff and an unambiguous roster name. Public cache keys are
`nfl_player_props` and `cfb_player_props`. Covered markets:

- passing yards / TDs / completions, interceptions
- rushing yards / attempts / TDs
- receiving yards / receptions / TDs

There is no synthetic-line fallback and no basketball-artifact borrowing.
Until native NFL consensus joblibs exist, that board remains empty. CFB publishes
historical baseline projections as PASS with zero stake and explicit uncalibrated
status. They use up to 12 dated games from the current and prior season, weighted
by 0.85 per game of age, with at least four observations. A rolling historical MAE
is reported separately from betting calibration; it is not evidence of a betting
edge. Opponent strength, transfer role changes and participation probabilities
are not modeled. The board says so in each row. Zero catches and zero rushing
yards are retained; passing priors exclude games without a passing attempt.

CFB rejects ambiguous player/game joins, mismatched line/side/book pairs, opening
or consensus prices, live games, and undated or same-day/future outcomes. Rows
retain ESPN game/player IDs for grading and provider IDs plus retrieval time for
source inspection. The existing refresh, merge, immutable archive and grading
pipeline carries these rows; baseline PASS rows are not limited by staking caps.
The market-history job grades immutable pregame CFB snapshots against final ESPN
box scores, feeding the existing native training corpus without relying on the
missing ESPN `propBets` endpoint. Post-kickoff captures never enter that corpus.
Per-game diagnostics distinguish unavailable markets, unmatched players and
insufficient history. An outage is a soft-fail: other sports and Pages proceed.
Dates stamp `America/Chicago`. CFB scoreboards use ESPN FBS `groups=80`.

## Deployment Contract

`.github/workflows/deploy-pages.yml` runs on every push to `main`. It first checks that today's model and player-prop caches are complete. Incomplete daily refreshes defer deployment without failing; ready data is built, copied into `dist/`, and deployed to GitHub Pages.

## Verification

```bash
npm run build
npm run typecheck
python3 -m pytest tests/smoke/test_static_viewer.py -q
python3 scripts/auto_grade_picks.py
```

Visual browser inspection is intentionally left to the repository owner.
