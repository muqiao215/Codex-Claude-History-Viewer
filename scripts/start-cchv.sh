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

resolve_repo_dir() {
  local candidates=()
  if [[ -n "${REPO_DIR:-}" ]]; then candidates+=("$REPO_DIR"); fi
  candidates+=(
    "/mnt/e/web/tools/Codex-Claude-History-Viewer"
    "$HOME/web/tools/Codex-Claude-History-Viewer"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    [[ -n "$candidate" ]] || continue
    if [[ -f "$candidate/app.py" && -d "$candidate/static" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo "CCHV repo not found. Set REPO_DIR or CCHV_REPO_DIR." >&2
  return 1
}

REPO_DIR="$(resolve_repo_dir)"

mkdir -p "$DATA_DIR"
cd "$REPO_DIR"

exec "$PYTHON_BIN" ./app.py \
  --codex-dir "$CODEX_DIR" \
  --claude-dir "$CLAUDE_DIR" \
  --openclaw-dir "$OPENCLAW_DIR" \
  --data-dir "$DATA_DIR" \
  --host "$BIND_HOST" \
  --port "$PORT"
