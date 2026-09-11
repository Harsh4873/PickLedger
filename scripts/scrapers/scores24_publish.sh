#!/usr/bin/env bash
# Publish Scores24 MLB/WNBA (required) plus CFB/NFL (soft-fail optional) from a
# non-GitHub-Actions IP. FIFA and NBA Summer stay archived from the daily run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "python3 not found" >&2
  exit 1
fi

GH_BIN="$(command -v gh || true)"
if [[ -z "${GH_BIN}" ]]; then
  echo "gh CLI not found on PATH" >&2
  exit 1
fi

DATE_ISO="${SCORES24_DATE:-$(TZ=America/Chicago date +%F)}"
# MLB+WNBA remain the Scores24 publisher completeness gate (and can still
# promote latest.json when complete). They are not a hard site_upcheck / Pages
# deploy requirement: in-house team models alone are enough to publish.
# CFB and NFL ride the same weekday morning/afternoon Scores24 run as soft-fail
# optional feeds: scrape when the slate exists, but incomplete/blocked/hung
# CFB or NFL must not prevent publishing a complete MLB+WNBA slate, and must
# not gate latestUpdated. Optional feeds get a hard timeout (default 180s) and
# no block-retry sleep budget so a Camoufox hang cannot delay MLB+WNBA publish
# for 900s. Afternoon reruns resume from SCORES24_CHECKPOINT_DIR.
PUBLISH_FEEDS="${SCORES24_PUBLISH_FEEDS:-scores24_mlb,scores24_wnba}"
OPTIONAL_FEEDS="${SCORES24_OPTIONAL_FEEDS:-scores24_cfb,scores24_nfl}"
PUBLISH_SPORTS="${SCORES24_PUBLISH_SPORTS:-mlb,wnba,cfb,nfl}"
OPTIONAL_FEED_TIMEOUT="${SCORES24_OPTIONAL_FEED_TIMEOUT_SECONDS:-180}"
REQUEST_INTERVAL="${SCORES24_REQUEST_INTERVAL_SECONDS:-12}"
REQUEST_ATTEMPTS="${SCORES24_REQUEST_ATTEMPTS:-1}"
ATTEMPT_RETRY_DELAY="${SCORES24_ATTEMPT_RETRY_DELAY_SECONDS:-0}"
BLOCK_RETRY_DELAY="${SCORES24_BLOCK_RETRY_DELAY_SECONDS:-90}"
BLOCK_RETRY_ROUNDS="${SCORES24_BLOCK_RETRY_ROUNDS:-4}"
OPTIONAL_BLOCK_RETRY_ROUNDS="${SCORES24_OPTIONAL_BLOCK_RETRY_ROUNDS:-0}"
OPTIONAL_CHALLENGE_WAITS="${SCORES24_OPTIONAL_CAMOUFOX_CHALLENGE_WAITS:-4}"
HOST_BLOCK_COOLDOWN="${SCORES24_HOST_BLOCK_COOLDOWN_SECONDS:-90}"
CURL_SESSION_MAX_REQUESTS="${SCORES24_CURL_SESSION_MAX_REQUESTS:-1}"
FEED_COOLDOWN="${SCORES24_PUBLISH_FEED_COOLDOWN_SECONDS:-90}"
# Same-day resume state: verified picks checkpoint + persistent browser
# profile so reruns only fight for still-missing matchups instead of
# re-requesting the whole slate from zero after every block.
SCORES24_STATE_ROOT="${SCORES24_STATE_ROOT:-${HOME}/.cache/pickledger-scores24}"
export SCORES24_CHECKPOINT_DIR="${SCORES24_CHECKPOINT_DIR:-${SCORES24_STATE_ROOT}}"
export SCORES24_CAMOUFOX_PROFILE_DIR="${SCORES24_CAMOUFOX_PROFILE_DIR:-${SCORES24_STATE_ROOT}/camoufox-profile}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      if [[ $# -lt 2 ]]; then
        echo "--date requires a YYYY-MM-DD value" >&2
        exit 2
      fi
      DATE_ISO="$2"
      shift 2
      ;;
    --date=*)
      DATE_ISO="${1#--date=}"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--date YYYY-MM-DD]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--date YYYY-MM-DD]" >&2
      exit 2
      ;;
  esac
done
if [[ ! "${DATE_ISO}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "Scores24 publish date must be YYYY-MM-DD; got ${DATE_ISO}" >&2
  exit 2
fi
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/pickledger-scores24.XXXXXX")"
TEMP_REPO="${TEMP_ROOT}/repo"
GENERATED_CACHE="${TEMP_ROOT}/scores24-latest.json"

cleanup() {
  rm -rf "${TEMP_ROOT}"
}
trap cleanup EXIT

REMOTE_URL="$(git -C "${REPO_ROOT}" remote get-url origin)"
GIT_NAME="$(git -C "${REPO_ROOT}" config user.name)"
GIT_EMAIL="$(git -C "${REPO_ROOT}" config user.email)"

git clone --quiet --depth 1 "${REMOTE_URL}" "${TEMP_REPO}"
git -C "${TEMP_REPO}" config user.name "${GIT_NAME}"
git -C "${TEMP_REPO}" config user.email "${GIT_EMAIL}"

# The local publisher supplies an independent trigger when GitHub cron is late.
# Recovery must not prevent publishing the editorial feeds if Actions is down.
"${PYTHON_BIN}" "${TEMP_REPO}/scripts/automation/ensure_model_refresh.py" \
  --remote --dispatch --date "${DATE_ISO}" \
  || echo "Model recovery check failed; continuing Scores24 publish." >&2

"${PYTHON_BIN}" - <<'PY'
import os
os.environ.setdefault("SCORES24_CAMOUFOX_FALLBACK", "true")
if os.environ.get("SCORES24_CAMOUFOX_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}:
    try:
        from camoufox.sync_api import Camoufox

        with Camoufox(headless=True, humanize=True) as browser:
            page = browser.new_page()
            page.goto("about:blank", timeout=15000)
            page.close()
        print("Scores24 Camoufox warmup complete.")
    except Exception as exc:
        print(f"Scores24 Camoufox warmup skipped: {exc}")
PY

IFS=',' read -r -a FEED_KEYS <<< "${PUBLISH_FEEDS}"
feed_index=0
for raw_feed_key in "${FEED_KEYS[@]}"; do
  feed_key="$(printf '%s' "${raw_feed_key}" | tr -d '[:space:]')"
  if [[ -z "${feed_key}" ]]; then
    continue
  fi
  if [[ "${feed_index}" -gt 0 ]]; then
    sleep "${FEED_COOLDOWN}"
  fi
  echo "Refreshing ${feed_key} for ${DATE_ISO}."
  SCORES24_BROWSER_FALLBACK=true \
  SCORES24_CAMOUFOX_FALLBACK=true \
  SCORES24_REQUEST_INTERVAL_SECONDS="${REQUEST_INTERVAL}" \
  SCORES24_REQUEST_ATTEMPTS="${REQUEST_ATTEMPTS}" \
  SCORES24_ATTEMPT_RETRY_DELAY_SECONDS="${ATTEMPT_RETRY_DELAY}" \
  SCORES24_BLOCK_RETRY_DELAY_SECONDS="${BLOCK_RETRY_DELAY}" \
  SCORES24_BLOCK_RETRY_ROUNDS="${BLOCK_RETRY_ROUNDS}" \
  SCORES24_HOST_BLOCK_COOLDOWN_SECONDS="${HOST_BLOCK_COOLDOWN}" \
  SCORES24_CURL_SESSION_MAX_REQUESTS="${CURL_SESSION_MAX_REQUESTS}" \
  "${PYTHON_BIN}" "${TEMP_REPO}/scripts/refresh_external_feeds.py" \
    --date "${DATE_ISO}" \
    --feeds "${feed_key}" \
    --sports "${PUBLISH_SPORTS}" \
    --skip-firestore
  feed_index=$((feed_index + 1))
done

if [[ "${feed_index}" -eq 0 ]]; then
  echo "No Scores24 feeds selected for publish." >&2
  exit 2
fi

SCORES24_CACHE_FILE="${TEMP_REPO}/data/model_cache/${DATE_ISO}.json"
if [[ ! -f "${SCORES24_CACHE_FILE}" ]]; then
  SCORES24_CACHE_FILE="${TEMP_REPO}/data/model_cache/latest.json"
fi

DATE_ISO="${DATE_ISO}" PUBLISH_FEEDS="${PUBLISH_FEEDS}" "${PYTHON_BIN}" - "${SCORES24_CACHE_FILE}" <<'PY'
import json
import os
import sys
from pathlib import Path

date_iso = os.environ["DATE_ISO"]
# Completeness gate is PUBLISH_FEEDS only (default MLB+WNBA). Optional feeds
# such as scores24_cfb and scores24_nfl are scraped after this check and must
# never fail it.
required = tuple(
    feed.strip()
    for feed in os.environ.get(
        "PUBLISH_FEEDS",
        "scores24_mlb,scores24_wnba",
    ).split(",")
    if feed.strip()
)
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
buckets = payload.get("external_feeds") if isinstance(payload.get("external_feeds"), dict) else {}
failures = []
for key in required:
    bucket = buckets.get(key) if isinstance(buckets.get(key), dict) else {}
    meta = bucket.get("meta") if isinstance(bucket.get("meta"), dict) else {}
    missing = meta.get("missingMatchups") if isinstance(meta.get("missingMatchups"), list) else []
    expected = meta.get("expectedMatchups")
    matched = meta.get("matchedPicks")
    bucket_date = str(bucket.get("date") or meta.get("date") or "").strip()
    if bucket.get("ok") is not True or missing or expected != matched:
        reason = bucket.get("error") or f"matched {matched!r} of {expected!r}; missing={missing!r}"
        failures.append(f"{key}: {reason}")
    elif bucket_date != date_iso:
        failures.append(f"{key}: bucket date {bucket_date!r}, expected {date_iso!r}")
if failures:
    raise SystemExit("Scores24 refresh incomplete; refusing to publish:\n- " + "\n- ".join(failures))
PY

# MLB+WNBA are complete. CFB/NFL (and any other OPTIONAL_FEEDS) are best-effort:
# a hang, Cloudflare block, or incomplete football slate must not prevent
# publishing the required feeds. A hard timeout kills the Camoufox process
# group and promotes any same-day checkpoint; yesterday's rows are never
# redatestamped as today.
IFS=',' read -r -a OPTIONAL_KEYS <<< "${OPTIONAL_FEEDS}"
required_csv=",$(printf '%s' "${PUBLISH_FEEDS}" | tr -d '[:space:]'),"
for raw_feed_key in "${OPTIONAL_KEYS[@]}"; do
  feed_key="$(printf '%s' "${raw_feed_key}" | tr -d '[:space:]')"
  if [[ -z "${feed_key}" ]]; then
    continue
  fi
  if [[ "${required_csv}" == *",${feed_key},"* ]]; then
    continue
  fi
  if [[ "${feed_index}" -gt 0 ]]; then
    sleep "${FEED_COOLDOWN}"
  fi
  echo "Refreshing optional ${feed_key} for ${DATE_ISO} (soft-fail; will not block MLB+WNBA publish)."
  set +e
  SCORES24_BROWSER_FALLBACK=true \
  SCORES24_CAMOUFOX_FALLBACK=true \
  SCORES24_REQUEST_INTERVAL_SECONDS="${REQUEST_INTERVAL}" \
  SCORES24_REQUEST_ATTEMPTS="${REQUEST_ATTEMPTS}" \
  SCORES24_ATTEMPT_RETRY_DELAY_SECONDS="${ATTEMPT_RETRY_DELAY}" \
  SCORES24_BLOCK_RETRY_DELAY_SECONDS="${BLOCK_RETRY_DELAY}" \
  SCORES24_BLOCK_RETRY_ROUNDS="${OPTIONAL_BLOCK_RETRY_ROUNDS}" \
  SCORES24_CAMOUFOX_CHALLENGE_WAITS="${OPTIONAL_CHALLENGE_WAITS}" \
  SCORES24_HOST_BLOCK_COOLDOWN_SECONDS="${HOST_BLOCK_COOLDOWN}" \
  SCORES24_CURL_SESSION_MAX_REQUESTS="${CURL_SESSION_MAX_REQUESTS}" \
  OPTIONAL_FEED_KEY="${feed_key}" \
  OPTIONAL_FEED_TIMEOUT="${OPTIONAL_FEED_TIMEOUT}" \
  DATE_ISO="${DATE_ISO}" \
  PUBLISH_SPORTS="${PUBLISH_SPORTS}" \
  TEMP_REPO="${TEMP_REPO}" \
  PYTHON_BIN="${PYTHON_BIN}" \
  SCORES24_CACHE_FILE="${SCORES24_CACHE_FILE}" \
  SCORES24_CHECKPOINT_DIR="${SCORES24_CHECKPOINT_DIR}" \
  "${PYTHON_BIN}" "${REPO_ROOT}/scripts/scrapers/scores24_optional_publish.py"
  optional_rc=$?
  set -e
  if [[ "${optional_rc}" -ne 0 ]]; then
    echo "Optional ${feed_key} scrape failed (rc=${optional_rc}); continuing with MLB+WNBA publish."
  fi
  feed_index=$((feed_index + 1))
done

cp "${SCORES24_CACHE_FILE}" "${GENERATED_CACHE}"

for attempt in 1 2 3; do
  git -C "${TEMP_REPO}" fetch --quiet origin main
  git -C "${TEMP_REPO}" reset --hard --quiet origin/main
  MERGE_RESULT="$(
    cd "${TEMP_REPO}"
    "${PYTHON_BIN}" scripts/merge_external_feed_cache_payload.py "${GENERATED_CACHE}"
  )"
  echo "${MERGE_RESULT}"
  DEPLOYABLE="$("${PYTHON_BIN}" -c 'import json,sys; print(str(json.load(sys.stdin)["latestUpdated"]).lower())' <<< "${MERGE_RESULT}")"
  git -C "${TEMP_REPO}" add data/model_cache
  if git -C "${TEMP_REPO}" diff --cached --quiet; then
    echo "Scores24 cache already current for ${DATE_ISO}."
    exit 0
  fi
  if [[ "${DEPLOYABLE}" == "true" ]]; then
    (
      cd "${TEMP_REPO}"
      "${PYTHON_BIN}" scripts/build_parlay_cards.py --date "${DATE_ISO}"
    )
    git -C "${TEMP_REPO}" add data/parlay_cards
  fi
  git -C "${TEMP_REPO}" commit -m "chore(feeds): refresh Scores24 feeds for ${DATE_ISO}"
  if git -C "${TEMP_REPO}" push origin HEAD:main; then
    if [[ "${DEPLOYABLE}" == "true" ]]; then
      "${GH_BIN}" workflow run deploy-pages.yml --repo Harsh4873/pickledger --ref main
    else
      echo "Skipped Pages deploy until the full ${DATE_ISO} team-model cache is available."
    fi
    echo "Published Scores24 feeds for ${DATE_ISO}."
    exit 0
  fi
  echo "Scores24 push attempt ${attempt} failed; retrying from latest main."
done

echo "Unable to publish Scores24 feeds after three attempts." >&2
exit 1
