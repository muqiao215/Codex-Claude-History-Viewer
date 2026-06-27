#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-${CCHV_REPO_DIR:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$DESKTOP_DIR/codex-claude-history-viewer.desktop"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
RESOLVER="$SCRIPT_DIR/resolve_cchv_repo.py"
REPO_DIR="$("$PYTHON_BIN" "$RESOLVER" --hint "${REPO_DIR:-}" --script-dir "$SCRIPT_DIR" --cwd "$PWD")"

mkdir -p "$DESKTOP_DIR"

# Install the bundled icon (lives next to this script) into the user hicolor theme
# so file managers and the application menu pick it up via Icon=cchv.
ICON_SRC="$SCRIPT_DIR/cchv-icon.png"
if [[ -f "$ICON_SRC" ]]; then
  for sz in 48x48 64x64 128x128 256x256; do
    install -D -m 0644 "$ICON_SRC" "$ICON_DIR/$sz/apps/cchv.png"
  done
  install -D -m 0644 "$SCRIPT_DIR/cchv-icon.svg" "$ICON_DIR/scalable/apps/cchv.svg" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && gtk-update-icon-cache -f -t "$ICON_DIR" >/dev/null 2>&1 || true
fi

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=History Viewer
Comment=Browse Codex, Claude Code, and OpenClaw session history
Exec=bash -lc 'cd "$REPO_DIR" && REPO_DIR="$REPO_DIR" PYTHON_BIN="$PYTHON_BIN" "$REPO_DIR/scripts/start-cchv-desktop.sh"'
Icon=cchv
Terminal=false
Categories=Development;Utility;
StartupNotify=true
EOF

chmod +x "$REPO_DIR/scripts/start-cchv.sh"
chmod +x "$REPO_DIR/scripts/start-cchv-desktop.sh" 2>/dev/null || true
chmod 644 "$DESKTOP_FILE"

# Drop a copy on the user's Desktop so it can be double-clicked.
DESKTOP_SHORTCUT="$HOME/Desktop/History Viewer.desktop"
if [[ -d "$HOME/Desktop" ]]; then
  install -m 0755 "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"
elif [[ -d "$HOME/桌面" ]]; then
  install -m 0755 "$DESKTOP_FILE" "$HOME/桌面/History Viewer.desktop"
fi

echo "Installed desktop entry:"
echo "  $DESKTOP_FILE"
if [[ -f "${DESKTOP_SHORTCUT:-$HOME/桌面/History Viewer.desktop}" ]]; then
  echo "Shortcut on desktop:"
  echo "  ${DESKTOP_SHORTCUT:-$HOME/桌面/History Viewer.desktop}"
fi
