#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="$ROOT_DIR/deploy/cloudflare"

load_env_file() {
  local file="$1"
  local line key value current_value

  if [[ ! -f "$file" ]]; then
    return
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ -z "$line" || "$line" == \#* ]]; then
      continue
    fi

    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    if [[ -z "$line" || "$line" == \#* ]]; then
      continue
    fi

    if [[ "${line%%=*}" == "$line" ]]; then
      continue
    fi

  key="${line%%=*}"
  value="${line#*=}"
  key="${key#"${key%%[![:space:]]*}"}"
  key="${key%"${key##*[![:space:]]}"}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  current_value="${!key-}"

  if [[ "$value" == \"*\" && ${#value} -ge 2 && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && ${#value} -ge 2 && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi

  if [[ -z "${!key+x}" || "$current_value" == "__REPLACE_ME__" ]]; then
    export "$key=$value"
  fi
  done < "$file"
}

load_env_file "$ROOT_DIR/.env"
load_env_file "$WORKER_DIR/.env"
load_env_file "$WORKER_DIR/.env.cloudflare"
load_env_file "$ROOT_DIR/.env.cloudflare"
load_env_file "$ROOT_DIR/scripts/.env"
load_env_file "$ROOT_DIR/scripts/.env.cloudflare"

is_configured_value() {
  local value="$1"
  [[ -n "$value" && "$value" != "__REPLACE_ME__" ]]
}

WORKER_URL="${PARTYMATH_WORKER_URL:-https://partymath.rogerpbrown.workers.dev}"
ADMIN_TOKEN="${PARTYMATH_ADMIN_TOKEN:-}"
WEBHOOK_SECRET="${TELEGRAM_WEBHOOK_SECRET:-}"
DATABASE="${PARTYMATH_D1_DATABASE_NAME:-partymath-cloudflare}"
CHAT_ID="${PARTYMATH_TEST_CHAT_ID:-579044008}"
UPDATE_ID="${PARTYMATH_TEST_UPDATE_ID:-}"
DO_DEPLOY="${PARTYMATH_DEPLOY_WORKER:-0}"
DO_WEBHOOK_SMOKE="${PARTYMATH_WEBHOOK_SMOKE:-0}"
DO_D1_CHECKS="${PARTYMATH_D1_CHECKS:-1}"
WRANGLER_CONFIG="$WORKER_DIR/wrangler.jsonc"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command '$1' not found" >&2
    exit 1
  }
}

require_cmd python3

echo "[1/6] Local static checks"
(cd "$ROOT_DIR" && python3 -m py_compile deploy/cloudflare/src/index.py)
echo "  - py_compile: ok"

echo "[2/6] CLI regression smoke"
(cd "$ROOT_DIR" && python3 cli/celebrations.py --test)
echo "  - cli --test: ok"

if command -v pylint >/dev/null 2>&1; then
  echo "[3/6] Lint"
  set +e
  (cd "$ROOT_DIR" && python3 -m pylint cli/celebrations.py celebrations_core.py utils.py)
  pylint_rc=$?
  set -e
  if [[ $pylint_rc -ne 0 ]]; then
    echo "  - pylint: completed with warnings (non-blocking in this script)"
  else
    echo "  - pylint: ok"
  fi
else
  echo "[3/6] Lint skipped (pylint missing)"
fi

if [[ "$DO_DEPLOY" == "1" ]]; then
  echo "[4/6] Deploy Cloudflare worker"
  npx wrangler --config "$WRANGLER_CONFIG" deploy
  echo "  - wrangler deploy: ok"
else
  echo "[4/6] Deploy skipped (PARTYMATH_DEPLOY_WORKER=0)"
fi

echo "[5/6] Worker health endpoints"
curl -fsS "$WORKER_URL/health"
if is_configured_value "$ADMIN_TOKEN"; then
  curl -fsS -H "authorization: Bearer $ADMIN_TOKEN" "$WORKER_URL/admin/tenant-state" | cat
else
  echo "  - /admin/tenant-state skipped (PARTYMATH_ADMIN_TOKEN missing)"
fi

if [[ "$DO_WEBHOOK_SMOKE" == "1" ]]; then
  if is_configured_value "$WEBHOOK_SECRET"; then
    echo "[6/6] Webhook smoke ping (non-command update)"
    if [[ -z "$UPDATE_ID" ]]; then
      UPDATE_ID="$(date +%s)"
    fi

    payload="$(cat <<JSON
{
  "update_id": ${UPDATE_ID},
  "message": {
    "message_id": 1,
    "date": $(date +%s),
    "chat": {
      "id": ${CHAT_ID},
      "type": "private"
    },
    "text": "smoke-check-no-command"
  }
}
JSON
)"
    response="$(curl -sS -H "x-telegram-bot-api-secret-token: $WEBHOOK_SECRET" \
      -H 'content-type: application/json' \
      -d "$payload" \
      "$WORKER_URL/telegram/webhook")"
    echo "$response"
  else
    echo "[6/6] Webhook smoke skipped (TELEGRAM_WEBHOOK_SECRET missing)"
  fi
else
  echo "[6/6] Webhook smoke skipped (PARTYMATH_WEBHOOK_SMOKE=0)"
fi

if [[ "$DO_D1_CHECKS" == "1" ]]; then
echo "[7/7] D1 quick checks"
  npx wrangler --config "$WRANGLER_CONFIG" d1 execute "$DATABASE" --remote --command "SELECT name FROM sqlite_master WHERE type='table';"
else
  echo "[7/7] D1 checks skipped (PARTYMATH_D1_CHECKS=0)"
fi

echo "verify: complete"
