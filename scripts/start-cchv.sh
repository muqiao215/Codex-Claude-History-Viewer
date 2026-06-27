#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-${CCHV_REPO_DIR:-}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CODEX_DIR="${CODEX_DIR:-$HOME/.codex}"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw}"
DATA_DIR="${DATA_DIR:-$HOME/.cache/cchv}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
PORT="${PORT:-8787}"
RESOLVER="$SCRIPT_DIR/resolve_cchv_repo.py"
REPO_DIR="$("$PYTHON_BIN" "$RESOLVER" --hint "${REPO_DIR:-}" --script-dir "$SCRIPT_DIR" --cwd "$PWD")"

mkdir -p "$DATA_DIR"
cd "$REPO_DIR"

exec "$PYTHON_BIN" ./app.py \
  --codex-dir "$CODEX_DIR" \
  --claude-dir "$CLAUDE_DIR" \
  --openclaw-dir "$OPENCLAW_DIR" \
  --data-dir "$DATA_DIR" \
  --host "$BIND_HOST" \
  --port "$PORT"
