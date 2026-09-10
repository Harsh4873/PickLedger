#!/usr/bin/env bash
# Unattended production refresh backup, run from cron on the owner's machine.
# GitHub Actions starts the same coordinator at 6:30 a.m. and 1:00 p.m.
# America/Chicago; this job waits for that run when it is already active.
#
# WHY THIS RUNS LOCALLY AND NOT IN ACTIONS
# Scores24 and Forebet Cloudflare-403 every GitHub-hosted runner IP, which is
# why the runbook makes them local-only. A scheduled workflow — or any
# cloud-hosted trigger — cannot publish them no matter how it is invoked. Only a
# host with a non-datacenter IP and Camoufox can, so the scraper half of the
# daily refresh has to live on a box like this one.
#
# It also covers the failure this was actually built for: GitHub's `schedule:`
# triggers are best-effort and have been unreliable on this repo — 2026-07-25
# and 2026-07-28 saw no writer fire at all, and 2026-07-27's was cancelled on
# the shared concurrency group. Each time the site silently served the previous
# day because deploy readiness (correctly) refused to promote stale data.
#
# WHAT IT DOES NOT DO
# This automates the mechanical half of `/refresh`: publish, dispatch, deploy,
# verify. It cannot diagnose a novel defect the way the full runbook does — when
# it reports anything other than HEALTHY, run `/refresh` and read the log.
#
# Usage:
#   daily_local_refresh.sh              # full run
#   daily_local_refresh.sh --dry-run    # verify wiring, take no action
set -uo pipefail

REPO="${PICKLEDGER_CRON_REPO:-$HOME/pickledger-cron/repo}"
LOG_DIR="${PICKLEDGER_CRON_LOGS:-$HOME/pickledger-cron/logs}"
GH_REPO="${PICKLEDGER_GH_REPO:-Harsh4873/pickledger}"
LOCK="${PICKLEDGER_CRON_LOCK:-$HOME/pickledger-cron/.lock}"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

TARGET_DATE="$(TZ=America/Chicago date +%F)"
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/${TARGET_DATE}.log"

# Logs go to stderr, never stdout: `dispatch` is called inside command
# substitution to capture a run id, and a log line on stdout would be captured
# along with it — producing a "run id" of log text that every later
# `gh run view` silently fails on.
log() { printf '[%s] %s\n' "$(TZ=America/Chicago date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

# Never let two runs overlap: a publisher pushing while another rebases the
# same branch just burns retries.
exec 9>"$LOCK"
if ! flock -n 9; then
  log "another run holds the lock; exiting"
  exit 0
fi

log "=== daily refresh for ${TARGET_DATE} (dry_run=${DRY_RUN}) ==="

for tool in git gh flock; do
  command -v "$tool" >/dev/null 2>&1 || { log "FATAL: $tool not on PATH"; exit 1; }
done
if ! gh auth status >/dev/null 2>&1; then
  log "FATAL: gh is not authenticated; run 'gh auth login'"
  exit 1
fi
[[ -x "${REPO}/.venv/bin/python" ]] || log "WARN: ${REPO}/.venv missing; publishers will fall back to system python3"

sync_repo() {
  git -C "$REPO" fetch --quiet origin main || return 1
  # -f discards any local modification. This clone is a disposable mirror, never
  # the owner's working copy, so there is nothing here worth preserving — and a
  # plain checkout aborts on a dirty tree, which is worse than it sounds: the
  # run continues against a stale checkout and then "verifies" a deploy for an
  # old HEAD. That happened on 2026-07-29 and the job reported HEALTHY off a
  # commit that was no longer tip.
  git -C "$REPO" checkout -qf -B main origin/main || return 1
  git -C "$REPO" clean -qfd -e .venv || true
}

wait_for_run() {  # run_id, label, timeout_seconds
  local id="$1" label="$2" limit="${3:-3600}" waited=0 status
  while :; do
    status="$(gh run view "$id" --repo "$GH_REPO" --json status --jq .status 2>/dev/null || echo unknown)"
    [[ "$status" == "completed" ]] && break
    (( waited >= limit )) && { log "  ${label}: TIMEOUT after ${limit}s (still ${status})"; return 1; }
    sleep 30; waited=$((waited + 30))
  done
  local conclusion
  conclusion="$(gh run view "$id" --repo "$GH_REPO" --json conclusion --jq .conclusion 2>/dev/null || echo unknown)"
  log "  ${label}: ${conclusion} (run ${id})"
  [[ "$conclusion" == "success" ]]
}

dispatch() {  # workflow file, label
  local wf="$1" label="$2" id
  if $DRY_RUN; then log "  [dry-run] would dispatch ${wf}"; return 0; fi
  gh workflow run "$wf" --repo "$GH_REPO" --ref main >/dev/null 2>&1 || { log "  ${label}: dispatch FAILED"; return 1; }
  sleep 20
  id="$(gh run list --repo "$GH_REPO" --workflow "$wf" --limit 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null)"
  log "  ${label}: dispatched run ${id}"
  echo "$id"
}

publish() {  # publisher script, label
  local script="$1" label="$2"
  if $DRY_RUN; then
    [[ -f "${REPO}/scripts/scrapers/${script}" ]] && log "  [dry-run] ${label}: script present" || log "  [dry-run] ${label}: MISSING ${script}"
    return 0
  fi
  log "  ${label}: publishing…"
  if bash "${REPO}/scripts/scrapers/${script}" --date "$TARGET_DATE" >>"$LOG" 2>&1; then
    log "  ${label}: done"
  else
    # A publisher failing is a degraded feed, never a reason to abandon the
    # rest of the refresh — the team models and deploy still matter.
    log "  ${label}: FAILED (continuing)"
  fi
}

log "syncing ${REPO}"
sync_repo || { log "FATAL: could not sync repo"; exit 1; }
log "  at $(git -C "$REPO" rev-parse --short HEAD)"

# One coordinator owns pick-cache-writer. Dispatching models and props at the
# same time used to replace a pending writer. GitHub already starts this at
# 6:30 a.m. and 1:00 p.m. America/Chicago; wait for an active run instead of
# stacking another.
log "dispatching Daily Refresh coordinator"
ACTIVE_DAILY="$(gh run list --repo "$GH_REPO" --workflow daily-refresh.yml --branch main --limit 10 \
  --json databaseId,status --jq '[.[] | select(.status=="queued" or .status=="in_progress" or .status=="waiting" or .status=="pending" or .status=="requested")] | .[0].databaseId // empty' 2>/dev/null || true)"
if [[ -n "${ACTIVE_DAILY}" ]]; then
  log "  daily-refresh already ${ACTIVE_DAILY}; waiting instead of dispatching another"
  DAILY_RUN="$ACTIVE_DAILY"
else
  DAILY_RUN="$(dispatch daily-refresh.yml 'daily-refresh')"
fi
if ! $DRY_RUN; then
  [[ -n "${DAILY_RUN:-}" ]] && wait_for_run "$DAILY_RUN" "daily-refresh" 10000
fi

log "running local publishers (Cloudflare-blocked on Actions; this host clears them)"
sync_repo
publish scores24_publish.sh 'scores24'
sync_repo
publish forebet_publish.sh 'forebet'
sync_repo
publish tennis_publish.sh 'tennis'

# A green deploy-pages run is NOT a deploy: readiness can defer without failing
# and leave the deploy job skipped. Always confirm the job itself executed for
# the exact final HEAD.
log "verifying deploy"
sync_repo
HEAD_SHA="$(git -C "$REPO" rev-parse HEAD)"
log "  final HEAD ${HEAD_SHA:0:8}"

deploy_job_status() {  # sha -> conclusion of the deploy job, or empty
  gh run list --repo "$GH_REPO" --workflow deploy-pages.yml --limit 8 \
    --json databaseId,headSha --jq ".[] | select(.headSha==\"$1\") | .databaseId" 2>/dev/null |
  while read -r id; do
    gh run view "$id" --repo "$GH_REPO" --json jobs \
      --jq '[.jobs[]|select(.name=="deploy")|.conclusion]|join(",")' 2>/dev/null
  done | grep -m1 success
}

if $DRY_RUN; then
  log "  [dry-run] would verify/dispatch deploy for ${HEAD_SHA:0:8}"
  STATE=DRY_RUN
elif [[ -n "$(deploy_job_status "$HEAD_SHA")" ]]; then
  log "  deploy already executed for ${HEAD_SHA:0:8}"
  STATE=HEALTHY
else
  DEPLOY_RUN="$(dispatch deploy-pages.yml 'deploy')"
  if [[ -n "${DEPLOY_RUN:-}" ]] && wait_for_run "$DEPLOY_RUN" "deploy" 1800; then
    JOB="$(gh run view "$DEPLOY_RUN" --repo "$GH_REPO" --json jobs --jq '[.jobs[]|select(.name=="deploy")|.conclusion]|join(",")')"
    if [[ "$JOB" == "success" ]]; then
      log "  deploy job EXECUTED for ${HEAD_SHA:0:8}"
      STATE=HEALTHY
    else
      # The trap the runbook calls out: green run, deploy job skipped.
      log "  deploy job did NOT execute (job=${JOB:-none}) — readiness deferred; data is stale or incomplete"
      STATE=DEPLOY_DEFERRED
    fi
  else
    STATE=DEPLOY_FAILED
  fi
fi

log "=== ${STATE} — ${TARGET_DATE} — HEAD ${HEAD_SHA:0:8} ==="

# Record the outcome where a status check can read it without parsing logs.
# Written even on failure — "the run died early" has to be distinguishable from
# "the run never started", which is the failure mode cron actually has.
if ! $DRY_RUN; then
  printf '{"date":"%s","state":"%s","head":"%s","finished_at":"%s"}\n' \
    "$TARGET_DATE" "$STATE" "${HEAD_SHA:0:8}" "$(TZ=America/Chicago date -Iseconds)" \
    > "${PICKLEDGER_CRON_STATUS:-$HOME/pickledger-cron/last_run.json}"
fi

# Optional push alert on failure. Set PICKLEDGER_ALERT_WEBHOOK to any
# Discord-compatible webhook to be told rather than having to look; without it
# the run is silent and the status command is the only way to notice.
if [[ "$STATE" != "HEALTHY" && "$STATE" != "DRY_RUN" && -n "${PICKLEDGER_ALERT_WEBHOOK:-}" ]]; then
  curl -sS -m 20 -H 'Content-Type: application/json' \
    -d "{\"content\":\"PickLedger daily refresh ${STATE} for ${TARGET_DATE} (HEAD ${HEAD_SHA:0:8}). Log: ${LOG}\"}" \
    "$PICKLEDGER_ALERT_WEBHOOK" >/dev/null 2>&1 && log "alert sent" || log "alert delivery failed"
fi

[[ "$STATE" == "HEALTHY" || "$STATE" == "DRY_RUN" ]] && exit 0 || exit 1
