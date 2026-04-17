#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-${CCHV_REPO_DIR:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/codex-claude-history-viewer.desktop"
ICON_PATH="${ICON_PATH:-}"
RESOLVER="$SCRIPT_DIR/resolve_cchv_repo.py"
REPO_DIR="$("$PYTHON_BIN" "$RESOLVER" --hint "${REPO_DIR:-}" --script-dir "$SCRIPT_DIR" --cwd "$PWD")"

mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=History Viewer
Comment=Browse Codex, Claude Code, and OpenClaw session history
Exec=bash -lc 'cd "$REPO_DIR" && REPO_DIR="$REPO_DIR" PYTHON_BIN="$PYTHON_BIN" "$REPO_DIR/scripts/start-cchv.sh"'
Terminal=false
Categories=Development;Utility;
StartupNotify=true
EOF

if [[ -n "$ICON_PATH" ]]; then
  printf 'Icon=%s\n' "$ICON_PATH" >> "$DESKTOP_FILE"
fi

chmod +x "$REPO_DIR/scripts/start-cchv.sh"
chmod 644 "$DESKTOP_FILE"

echo "Installed desktop entry:"
echo "  $DESKTOP_FILE"
