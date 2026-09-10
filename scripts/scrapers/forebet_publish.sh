#!/usr/bin/env bash
# Publish Forebet MLB/WNBA/MLS/CFB/NFL feeds from a non-GitHub-Actions IP.
# GitHub-hosted runners get Cloudflare-challenged on Forebet listings;
# local IPs usually do not — same pattern as Scores24.
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

DATE_ISO="${FOREBET_DATE:-$(TZ=America/Chicago date +%F)}"
PUBLISH_FEEDS="${FOREBET_PUBLISH_FEEDS:-forebet_mlb,forebet_wnba,forebet_mls,forebet_cfb,forebet_nfl}"
FEED_COOLDOWN="${FOREBET_PUBLISH_FEED_COOLDOWN_SECONDS:-5}"
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
  echo "Forebet publish date must be YYYY-MM-DD; got ${DATE_ISO}" >&2
  exit 2
fi

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/pickledger-forebet.XXXXXX")"
TEMP_REPO="${TEMP_ROOT}/repo"
GENERATED_CACHE="${TEMP_ROOT}/forebet-latest.json"

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
  if ! "${PYTHON_BIN}" "${TEMP_REPO}/scripts/refresh_external_feeds.py" \
    --date "${DATE_ISO}" \
    --feeds "${feed_key}" \
    --sports "mlb,wnba,mls,cfb,nfl" \
    --skip-firestore; then
    case "${feed_key}" in
      forebet_cfb|forebet_nfl)
        echo "Optional ${feed_key} failed; publishing diagnostics with the other feeds." >&2
        ;;
      *) exit 1 ;;
    esac
  fi
  feed_index=$((feed_index + 1))
done

if [[ "${feed_index}" -eq 0 ]]; then
  echo "No Forebet feeds selected for publish." >&2
  exit 2
fi

FOREBET_CACHE_FILE="${TEMP_REPO}/data/model_cache/${DATE_ISO}.json"
if [[ ! -f "${FOREBET_CACHE_FILE}" ]]; then
  FOREBET_CACHE_FILE="${TEMP_REPO}/data/model_cache/latest.json"
fi

DATE_ISO="${DATE_ISO}" PUBLISH_FEEDS="${PUBLISH_FEEDS}" "${PYTHON_BIN}" - "${FOREBET_CACHE_FILE}" <<'PY'
import json
import os
import sys
from pathlib import Path

date_iso = os.environ["DATE_ISO"]
required = tuple(
    feed.strip()
    for feed in os.environ.get(
        "PUBLISH_FEEDS",
        "forebet_mlb,forebet_wnba,forebet_mls,forebet_cfb,forebet_nfl",
    ).split(",")
    if feed.strip()
)
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
external = payload.get("external_feeds") if isinstance(payload.get("external_feeds"), dict) else {}
failures = []
for key in required:
    bucket = models.get(key) if isinstance(models.get(key), dict) else None
    if bucket is None:
        bucket = external.get(key) if isinstance(external.get(key), dict) else {}
    meta = bucket.get("meta") if isinstance(bucket.get("meta"), dict) else {}
    missing = meta.get("missingMatchups") if isinstance(meta.get("missingMatchups"), list) else []
    blocked = int(meta.get("blockedUrls") or 0)
    bucket_date = str(bucket.get("date") or meta.get("date") or "").strip()
    error = str(bucket.get("error") or "")
    if key in {"forebet_cfb", "forebet_nfl"} and bucket.get("ok") is not True:
        print(f"Optional {key}: {error or 'no successful refresh'}", file=sys.stderr)
        continue
    if bucket.get("ok") is not True:
        reason = error or f"missingMatchups={missing!r} blockedUrls={blocked}"
        failures.append(f"{key}: {reason}")
    elif blocked or "Cloudflare" in error:
        failures.append(f"{key}: Cloudflare block (blockedUrls={blocked})")
    elif missing:
        failures.append(f"{key}: missingMatchups={missing!r}")
    elif bucket_date != date_iso:
        failures.append(f"{key}: bucket date {bucket_date!r}, expected {date_iso!r}")
if failures:
    raise SystemExit("Forebet refresh incomplete; refusing to publish:\n- " + "\n- ".join(failures))
PY

cp "${FOREBET_CACHE_FILE}" "${GENERATED_CACHE}"

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
    echo "Forebet cache already current for ${DATE_ISO}."
    exit 0
  fi
  if [[ "${DEPLOYABLE}" == "true" ]]; then
    (
      cd "${TEMP_REPO}"
      "${PYTHON_BIN}" scripts/build_parlay_cards.py --date "${DATE_ISO}"
    )
    git -C "${TEMP_REPO}" add data/parlay_cards
  fi
  git -C "${TEMP_REPO}" commit -m "chore(feeds): refresh Forebet feeds for ${DATE_ISO}"
  if git -C "${TEMP_REPO}" push origin HEAD:main; then
    if [[ "${DEPLOYABLE}" == "true" ]]; then
      "${GH_BIN}" workflow run deploy-pages.yml --repo Harsh4873/pickledger --ref main
    else
      echo "Skipped Pages deploy until the full ${DATE_ISO} team-model cache is available."
    fi
    echo "Published Forebet feeds for ${DATE_ISO}."
    exit 0
  fi
  echo "Forebet push attempt ${attempt} failed; retrying from latest main."
done

echo "Unable to publish Forebet feeds after three attempts." >&2
exit 1
