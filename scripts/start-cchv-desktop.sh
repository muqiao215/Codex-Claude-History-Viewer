#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT="${PORT:-8787}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
URL="http://${BIND_HOST}:${PORT}"

if (exec 3<>"/dev/tcp/${BIND_HOST}/${PORT}") >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
  exit 0
fi

(
  sleep 1.5
  xdg-open "$URL" >/dev/null 2>&1 || true
) &

exec "$SCRIPT_DIR/start-cchv.sh"
