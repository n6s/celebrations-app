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
  local first_line
  local nonempty_lines
  local nonempty_count
  local today_header="🎉 Today's Celebrations:"
  local tenant_header="🎉 Today's Celebrations ($tenant):"

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
  if [[ "$message" == "$today_header"* ]]; then
    message="${tenant_header}${message#"$today_header"}"
  fi
  nonempty_lines="$(printf '%s\n' "$message" | sed '/^[[:space:]]*$/d')"
  first_line="$(printf '%s\n' "$nonempty_lines" | sed -n '1p')"
  nonempty_count="$(printf '%s\n' "$nonempty_lines" | wc -l)"

  if [[ "$nonempty_count" -eq 1 && "$first_line" == "🎉 Today's Celebrations"* ]]; then
    message="$first_line

No events today."
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
