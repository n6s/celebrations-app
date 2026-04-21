#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_MODE="${1:-symlink}"
USER_BIN_DIR="${HOME}/bin"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

install_file() {
  local source_path="$1"
  local target_path="$2"

  mkdir -p "$(dirname "$target_path")"

  case "$INSTALL_MODE" in
    symlink)
      ln -sfn "$source_path" "$target_path"
      ;;
    copy)
      cp "$source_path" "$target_path"
      ;;
    *)
      echo "Unknown install mode: $INSTALL_MODE" >&2
      echo "Use 'symlink' or 'copy'." >&2
      exit 1
      ;;
  esac

  echo "$INSTALL_MODE $source_path -> $target_path"
}

install_file \
  "$REPO_DIR/scripts/celebration-notifier.sh" \
  "$USER_BIN_DIR/celebration-notifier.sh"

install_file \
  "$REPO_DIR/scripts/monthly-budget-notifier.sh" \
  "$USER_BIN_DIR/monthly-budget-notifier.sh"

install_file \
  "$REPO_DIR/deploy/systemd/celebration-notifier.service" \
  "$SYSTEMD_USER_DIR/celebration-notifier.service"

install_file \
  "$REPO_DIR/deploy/systemd/celebration-notifier.timer" \
  "$SYSTEMD_USER_DIR/celebration-notifier.timer"

install_file \
  "$REPO_DIR/deploy/systemd/celebration-budget-notifier.service" \
  "$SYSTEMD_USER_DIR/celebration-budget-notifier.service"

install_file \
  "$REPO_DIR/deploy/systemd/celebration-budget-notifier.timer" \
  "$SYSTEMD_USER_DIR/celebration-budget-notifier.timer"

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload
  echo "Reloaded user systemd units."
fi
