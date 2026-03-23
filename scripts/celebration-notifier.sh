#!/bin/bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TENANTS_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}/celebrations/tenants"

send_tenant() {
  local tenant="$1"
  local env_file="$TENANTS_ROOT/$tenant/notifier.env"
  local message
  local nonempty_lines

  if [[ ! -f "$env_file" ]]; then
    echo "Missing tenant notifier config: $env_file" >&2
    return 1
  fi

  unset CHAT_ID BOT_TOKEN
  set -a
  . "$env_file"
  set +a

  : "${CHAT_ID:?Missing CHAT_ID in $env_file}"
  : "${BOT_TOKEN:?Missing BOT_TOKEN in $env_file}"

  message="$(python3 "$REPO_DIR/cli/celebrations.py" --tenant "$tenant")"
  nonempty_lines="$(printf '%s\n' "$message" | sed '/^[[:space:]]*$/d')"

  if [[ "$nonempty_lines" == "🎉 Today's Celebrations:" ]]; then
    return 0
  fi

  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '[%s]\n' "$tenant"
    printf '%s\n' "$message"
    return 0
  fi

  if [[ -n "$message" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=$CHAT_ID" \
      --data-urlencode "text=$message"
  fi
}

discover_tenants() {
  find "$TENANTS_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
}

if [[ $# -gt 0 ]]; then
  TENANTS=("$@")
else
  mapfile -t TENANTS < <(discover_tenants)
fi

if [[ ${#TENANTS[@]} -eq 0 ]]; then
  echo "No tenant directories found in $TENANTS_ROOT" >&2
  exit 1
fi

for tenant in "${TENANTS[@]}"; do
  send_tenant "$tenant"
done
