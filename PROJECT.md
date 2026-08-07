# Project

## Why

Codex CLI, Claude Code, OpenClaw, OpenCode, and Hermes leave useful local session history, but raw transcripts are slow to search and poor at answering what an Agent actually delivered. This project turns those records into a fast local history inbox and an evidence-backed engineering ledger.

## User Intent

- Find past Agent sessions, commands, patches, decisions, and discussions quickly.
- See the practical value of a session: what changed, what was tested, where it failed, and whether the request converged.
- Continue work from compact, evidence-backed handoff context instead of replaying an entire transcript.
- Keep private development history on the user's machine by default.

## Non-goals

- An enterprise observability or multi-tenant analytics platform.
- A real-time Agent gateway, MCP interceptor, or event-sourcing system.
- Mandatory vector search, embeddings, or bulk LLM analysis of historical sessions.
- Treating AI interpretation as authoritative evidence.
- Uploading transcripts or credentials by default.

## Success

A user can locate and inspect a relevant session quickly, understand its intent, actions, deliverables, friction, and outcome without reading the full transcript, trace claims back to evidence, and copy enough context for another Agent to continue safely.

## Constraints

- Python 3.8+ standard library only for the application runtime.
- Modern browser frontend without a build step.
- Local-first storage and processing; network AI audit is optional and explicit.
- Must tolerate evolving and partially malformed transcript formats.
- Platform-aware behavior for Linux, Windows, and WSL sources.
- Source databases owned by other tools, such as OpenCode and Hermes, are read-only inputs.

## Current State

The `v1.0.0` release supports five sources, search and filtering, session/project browsing, compact tool timelines, deterministic value auditing, evidence navigation, optional heuristic or LLM audit, platform-aware launchers, and compact or standard evidence-backed Agent handoffs. OpenCode audit and handoff data are derived from its database without mutating it; Hermes remains browse-only with neutral audit signals.

The main structural limitation is that the Python backend remains concentrated in `app.py`; source parsing, indexing, routing, and server bootstrap share one large module.

## Current Priority

Collect real-world feedback on the first stable release while preserving local-first privacy and evidence traceability. Prioritize source-format compatibility and correctness before expanding process or infrastructure.

## Knowledge Map

- How the system works → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Why durable choices were made → [docs/DECISIONS.md](docs/DECISIONS.md)
- Current SpecMesh adoption work → [plans/specmesh-adoption/](plans/specmesh-adoption/)
- First stable release record → [plans/release-v1.0.0/](plans/release-v1.0.0/)
- Feature delivery history → [docs/session-plans/](docs/session-plans/)
