# Architecture

## Overview

A dependency-free Python HTTP server indexes local Agent histories into per-source SQLite caches and serves a static browser UI. Deterministic audit code derives evidence and value signals; optional AI code interprets a compact audit payload only on demand.

## Repository Map

- `app.py` — transcript parsing, source indexers, API routing, static serving, CLI configuration, and runtime bootstrap.
- `audit/` — normalized audit schema, evidence extraction, command classification, scoring, optional AI audit, and deterministic handoff generation.
- `static/` — browser application, markup, and styling; no build pipeline.
- `tests/` — Python unit/integration tests and Node-based frontend behavior tests.
- `scripts/` — Linux/Windows launchers, desktop integration, and repository resolution.
- `demo/` — synthetic transcript fixtures safe for demonstration.
- `docs/session-plans/` — historical feature plans and delivery records.

## Entry Points

- `python3 app.py` starts the server, registers available source backends, begins indexing, and serves `static/` on port 8787 by default.
- `scripts/start-cchv.sh` and `scripts/start-cchv.ps1` resolve the repository and provide platform launch paths.
- `static/index.html` loads the browser UI implemented by `static/app.js` and `static/styles.css`.

## Components

### Transcript adapters and indexes

`app.py` parses Codex, Claude, and OpenClaw JSONL into a shared session/message shape. `Indexer` persists derived records in local SQLite caches. `OpenCodeIndexer` and `HermesStateIndexer` read their tools' existing SQLite state through source-specific adapters.

### Source routing and HTTP API

`SourceBackend` binds a runtime system and source to an indexer. `Handler` routes `/api/{system}/{source}/...` requests and serves the static application. The runtime exposes Windows/WSL or Linux according to the host rather than presenting unavailable systems.

### Audit layer

`audit/extractor.py` normalizes transcript events and produces evidence-backed `AuditPayload` objects. Classification and scoring remain deterministic. `audit/ai_audit.py` and `audit/llm_client.py` provide opt-in semantic interpretation from compact payloads; the raw transcript is not the default AI input.

### Handoff layer

`audit/handoff.py` builds compact or standard continuation capsules from deterministic audit data, selected user constraints, verification results, evidence locations, and current Git state. It intentionally excludes raw transcripts, hidden prompts, reasoning, and full tool output.

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
- Transcript formats differ by tool and evolve over time. Parser changes require fixtures for each affected source.
- SQLite schema migrations must remain idempotent for existing user caches.
- Evidence jumps depend on stable message/evidence identifiers across backend and frontend.
- Frontend tests use lightweight DOM shims, so browser-only APIs need explicit compatibility handling.

## Read Next

- Session parsing or index behavior → `app.py` and `tests/test_session_previews.py`
- Deterministic evidence or scoring → `audit/` and `tests/test_audit_extractor.py`
- AI audit behavior → `audit/ai_audit.py`, `audit/llm_client.py`, and `tests/test_ai_audit.py`
- Agent handoffs → `audit/handoff.py`, `tests/test_handoff.py`, and `docs/session-plans/003-agent-handoff.md`
- UI interactions → `static/app.js` and the matching `tests/*.js`
- Durable tradeoffs → `docs/DECISIONS.md`
