# Automation Scripts

The active production automation uses GitHub Actions plus local Codex morning and afternoon upchecks, and writes committed JSON for the static GitHub Pages viewer.

| Script | Purpose |
| --- | --- |
| `refresh_model_cache.py` | Runs selected model directories, including NBA Summer League during the summer slate, and writes dated model-cache JSON. |
| `refresh_external_feeds.py` | Refreshes sport-specific SportyTrader, SportsGambler, Scores24NBASummer, Scores24WNBA, Scores24MLB, Scores24FIFAWorldCup, and Scores24CFB cache buckets. |
| `merge_model_cache_payload.py` | Merges model output while preserving other buckets and grades. |
| `merge_external_feed_cache_payload.py` | Merges feed output while preserving model buckets and grades. |
| `build_player_prop_market_history.py` | Backfills immutable posted player-prop markets and final outcomes for season training (MLB, WNBA, NFL, CFB). |
| `build_player_prop_outcome_history.py` | Builds compact roster-aware MLB/WNBA/NFL/CFB game outcomes and workload features. |
| `train_player_prop_consensus_ml.py` | Trains the four season/history models and requires at least 70% on chronological validation and holdout before publication. |
| `archive_player_prop_snapshot.py` | Freezes every published prop slate so later refreshes cannot rewrite its measured record. |
| `auto_grade_picks.py` | Grades completed games through ESPN and rebuilds the universal outcome ledger. |
| `rebuild_pick_outcome_ledger.py` | Deduplicates all model and player-prop picks into `data/calibration/outcome_ledger.json`. |
| `train_pick_calibration.py` | Evaluates a shrinkage-based probability calibrator against the active champion. |
| `pick_calibration.py` | Preserves immutable pregame snapshots and applies the promoted calibrator to refresh payloads. |
| `cache_manifest.py` | Maintains `data/model_cache/index.json` for the static frontend. |
| `scrapers/scores24_publish_local.sh` | Mac wrapper for `scrapers/scores24_publish.sh` (Scores24 blocks GitHub-hosted runner IPs). |
| `scrapers/scores24_publish.sh` | Portable Scores24 publisher for local Mac or Cursor Cloud automations. |

Production refresh workflows pass `--skip-firestore`; committed JSON is the source of truth.

Useful local checks:

```bash
python3 scripts/auto_grade_picks.py
python3 scripts/rebuild_pick_outcome_ledger.py
python3 scripts/train_pick_calibration.py
python3 -m pytest tests/smoke/test_static_viewer.py -q
```
