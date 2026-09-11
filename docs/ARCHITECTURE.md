# Architecture

## Overview

A dependency-free Python HTTP server indexes local Agent histories into per-source SQLite caches and serves a static browser UI. Deterministic audit code derives evidence and value signals; optional AI code interprets a compact audit payload only on demand.

## Repository Map

- `history_core/` — existing transcript parsers, source indexers, machine service functions and explicit headless CLI.
- `app.py` — compatibility reexports, API routes, platform source bootstrap and HTTP/static serving.
- `audit/` — normalized audit schema, evidence extraction, command classification, scoring, optional AI audit, deterministic handoff generation, and daily-briefing aggregation (`briefing.py`).
- `static/` — browser application, markup, and styling; no build pipeline. The session header hosts the audit panel plus the `.insight-panel` family (usage / briefing / plans / handoff preview).
- `tests/` — Python unit/integration tests and Node-based frontend behavior tests.
- `scripts/` — Linux/Windows launchers, desktop integration, and repository resolution.
- `demo/` — synthetic transcript fixtures safe for demonstration.
- `docs/session-plans/` — historical feature plans and delivery records.
- `DESIGN.md` — visual-system contract (tokens, components, rules) for agent-driven UI changes.

## Entry Points

- `python3 app.py` starts the server, registers available source backends, begins indexing, and serves `static/` on port 8787 by default.
- `scripts/start-cchv.sh` and `scripts/start-cchv.ps1` resolve the repository and provide platform launch paths.
- `static/index.html` loads the browser UI implemented by `static/app.js` and `static/styles.css`.

## Components

### Transcript adapters and indexes

`history_core/sources.py` parses Codex, Claude, and OpenClaw JSONL into a shared session/message shape. `Indexer` persists derived records in local SQLite caches. `OpenCodeIndexer` and `HermesStateIndexer` read their tools' existing SQLite state through source-specific adapters.

### Source routing and HTTP API

`SourceBackend` binds a runtime system and source to an indexer. `Handler` routes `/api/{system}/{source}/...` requests and serves the static application. The runtime exposes Windows/WSL or Linux according to the host rather than presenting unavailable systems.

### Audit layer

`audit/extractor.py` normalizes transcript events and produces evidence-backed `AuditPayload` objects. Classification and scoring remain deterministic. `audit/ai_audit.py` and `audit/llm_client.py` provide opt-in semantic interpretation from compact payloads; the raw transcript is not the default AI input.

### Handoff layer

`audit/handoff.py` builds compact or standard continuation capsules from deterministic audit data, selected user constraints, verification results, evidence locations, and current Git state. It intentionally excludes raw transcripts, hidden prompts, reasoning, and full tool output. The frontend renders the selected capsule as themed markdown (`.handoff-theme-*`), copies it as rich text, and exports `.md` / standalone themed `.html`.

### Usage aggregation

Codex parsers fold cumulative `token_count` telemetry into per-session `tokens_*` columns (kept in the `sessions` table alongside audit scores); Claude sums per-message `message.usage`. OpenCode aggregates its own native token columns; Hermes reports zeros. `query_usage` on each indexer powers `GET /api/{system}/{source}/usage` with totals, per-day (viewer-local timezone), per-project, and top-session views. No currency costs are computed.

### Briefing layer

`audit/briefing.py` aggregates one day of session summaries into a deterministic briefing: near-duplicate sessions (same cwd, touched-file Jaccard ≥ 0.5) merge into the higher-value one; highlights, blocked sessions, and deliverables are enriched from at most 12 deterministic audits and any stored AI audits. `GET /briefing` returns the payload plus `render_briefing_markdown` output; `POST /briefing` adds a narrative — LLM (strict JSON) when a provider is configured, a composed heuristic fallback otherwise. The raw transcript is never an input.

### Plan-aware scanning

`scan_plan_files(cwd)` is a stateless, read-only filesystem scan of planning artifacts (`task_plan.md` / `progress.md` / `findings.md` at the root and under `plans/*`, plus `docs/session-plans/*.md`), capped at 80 files / 120 KB bodies, excerpting only well-known `## ` sections. `/plans?project=` and `/session/{id}/plans` (mtime window ±7 days around the session) serve it; nothing is persisted and nothing is written.

### Browser UI

`static/app.js` manages source/session navigation, pagination, search, transcript rendering, audit panels, evidence jumps, tool collapsing, and handoff copy actions. State that improves continuity across reloads is stored in browser local storage.

## Data Flow

```text
local JSONL or source SQLite
        ↓
source parser / adapter
        ↓
normalized sessions and messages
        ↓
local SQLite cache + deterministic audit evidence
        ↓
HTTP JSON API
        ↓
static browser UI
        ↓ optional explicit action
compact AI audit input or deterministic handoff
```

## Important Invariants

- Transcript facts come from deterministic parsing; AI output may explain facts but cannot replace evidence.
- Evidence identifiers must remain traceable to transcript locations.
- Local transcripts and caches stay local unless the user explicitly invokes configured network AI auditing.
- OpenCode and Hermes source databases are treated as read-only.
- Parsers tolerate unknown or malformed records and surface recoverable raw content instead of crashing the whole session.
- Static assets work without a frontend build or package installation.

## External Dependencies

- Python 3.8+ standard library and a modern browser are the only required runtime dependencies.
- Optional AI audit can use an OpenAI-compatible endpoint or a reachable local Ollama service.
- Agent history formats and OpenCode/Hermes schemas are external contracts that may evolve.

## Fragile Areas

- `app.py` combines several responsibilities; broad edits can affect unrelated sources or API behavior.
- Transcript formats differ by tool and evolve over time. Parser changes require fixtures for each affected source. Usage extraction bumps parser versions, forcing a one-time full re-parse.
- SQLite schema migrations must remain idempotent for existing user caches (usage columns included).
- Evidence jumps depend on stable message/evidence identifiers across backend and frontend.
- Frontend tests use lightweight DOM shims, so browser-only APIs need explicit compatibility handling.
- `scan_plan_files` reads the filesystem on request; its caps (file count, body size, blank-cwd rejection) must not be relaxed, or a request could scan an unintended directory.

## Read Next

- Session parsing or index behavior → `app.py` and `tests/test_session_previews.py`
- Deterministic evidence or scoring → `audit/` and `tests/test_audit_extractor.py`
- AI audit behavior → `audit/ai_audit.py`, `audit/llm_client.py`, and `tests/test_ai_audit.py`
- Agent handoffs → `audit/handoff.py`, `tests/test_handoff.py`, and `docs/session-plans/003-agent-handoff.md`
- Token usage → `parse_codex_session_file` / `parse_claude_session_file` in `app.py`, `query_usage` on the indexers, and `tests/test_usage.py`
- Daily briefings → `audit/briefing.py`, `tests/test_briefing.py`, and `docs/session-plans/004-usage-briefing-plans.md`
- Plan-aware scanning → `scan_plan_files` / `extract_plan_sections` in `app.py` and `tests/test_plan_aware.py`
- UI interactions → `static/app.js` and the matching `tests/*.js` (insight panels: `tests/test_insight_panels.js`)
- Durable tradeoffs → `docs/DECISIONS.md`

## Native session continuation

The existing resume header generates native commands for Codex, Claude and OpenCode. OpenCode uses `opencode --session <id>` with the selected source cwd and validates the native ID before emitting a shell command. The viewer only displays/copies the command; OpenCode owns session loading and mutation. TaskHub adoption is optional orchestration above this path. Native conversation continuity and evidence-based handoff/SpecMesh files serve distinct purposes.

## Workflow boundary (v1.1.0)

See [machine interface and human workspace](CODEKIT-INTEGRATION.md). `/` is now the workspace overview; `/history` retains the full history interface.
