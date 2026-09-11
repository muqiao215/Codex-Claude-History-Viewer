# Project

## Why

Codex CLI, Claude Code, OpenClaw, OpenCode, and Hermes leave useful local session history, but raw transcripts are slow to search and poor at answering what an Agent actually delivered. This project turns those records into a fast local history inbox and an evidence-backed engineering ledger.

## User Intent

- Find past Agent sessions, commands, patches, decisions, and discussions quickly.
- Resume a selected native provider session directly when available; native conversation context and verified SpecMesh project files are complementary layers. TaskHub adoption is not a prerequisite for native continuation.
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

The stable `v1.1.0` release supports five history sources, existing search/audit/handoff features, usage/briefing/plan views and native OpenCode resume commands. It separates parsers/indexers into `history_core`, exposes an explicit headless CLI, and adds a human work overview. Native source databases remain read-only; Hermes keeps its existing limited audit evidence.

Release verification passed 191 Python tests, six Node test files and synthetic HTTP/browser checks. The local service runs v1.1.0. The earlier independent-user M3 trial remains historical unfinished work; the current acceptance priority is real Agent handoff, not that trial. CM owns supervised native adoption and task state. Future multi-device/resident-service gates remain planned; see [implementation boundaries](docs/CODEKIT-INTEGRATION.md).

## Current Priority

Agent-to-Agent handoff is the primary workflow acceptance target. Keep machine retrieval independent of Web; show people progress, evidence and unresolved decisions before configuration controls. Validate native provider continuation against current repository facts. A synthetic handoff or previous independent-user M3 plan does not establish that acceptance. Next work: [Agent handoff service](plans/agent-handoff-service/task_plan.md).

## Knowledge Map

- Release alignment → [plans/release-alignment/](plans/release-alignment/)
- Current product validation → [plans/history-viewer-product-validation/](plans/history-viewer-product-validation/)

- How the system works → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Why durable choices were made → [docs/DECISIONS.md](docs/DECISIONS.md)
- Completed SpecMesh adoption → [plans/specmesh-adoption/](plans/specmesh-adoption/)
- First stable release record → [plans/release-v1.0.0/](plans/release-v1.0.0/)
- Feature delivery history → [docs/session-plans/](docs/session-plans/)

- Plan status index → [plans/README.md](plans/README.md)

## Approved next direction

The primary coordinating Agent owns cross-project delivery. Repository-owned execution details and current status: [agent-handoff-service](plans/agent-handoff-service/task_plan.md). These future milestones remain planned; current released behavior retains its existing authority.
