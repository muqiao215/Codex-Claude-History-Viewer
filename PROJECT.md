# Project

## Why

Codex CLI, Claude Code, OpenClaw, OpenCode, and Hermes leave useful local session history, but raw transcripts are slow to search and poor at answering what an Agent actually delivered. This project turns those records into a fast local history inbox and an evidence-backed engineering ledger.

## User Intent

- Find past Agent sessions, commands, patches, decisions, and discussions quickly.
- Provide explicit resume commands for a selected native provider session when available. The user can execute them through their selected native CLI or choose CM for supervised adoption; TaskHub is not a prerequisite. Native conversation context and verified SpecMesh project files are complementary layers.
- See the practical value of a session: what changed, what was tested, where it failed, and whether the request converged.
- Continue work from compact, evidence-backed handoff context instead of replaying an entire transcript.
- Keep private development history on the user's machine by default.
- Deliver history retrieval, evidence and explicit resume commands independently of CM. History does not execute provider sessions; the user-selected native CLI or optional CM owns execution, and live CM facts are an optional adapter.

## Non-goals

- An enterprise observability or multi-tenant analytics platform.
- A real-time Agent gateway, MCP interceptor, or event-sourcing system.
- Mandatory vector search, embeddings, or bulk LLM analysis of historical sessions.
- Treating AI interpretation as authoritative evidence.
- Uploading transcripts or credentials by default.

## Success

A user can locate and inspect a relevant session quickly, understand its intent, actions, deliverables, friction, and outcome without reading the full transcript, trace claims back to evidence, and copy enough context for another Agent to continue safely.

## Constraints

- Python 3.11+ standard library only for the application runtime.
- Modern browser frontend without a build step.
- Local-first storage and processing; network AI audit is optional and explicit.
- Must tolerate evolving and partially malformed transcript formats.
- Platform-aware behavior for Linux, Windows, and WSL sources.
- Source databases owned by other tools, such as OpenCode and Hermes, are read-only inputs.

## Current State

The stable `v1.1.0` release supports five history sources, existing search/audit/handoff features, usage/briefing/plan views and native OpenCode resume commands. It separates parsers/indexers into `history_core`, exposes an explicit headless CLI, and adds a human work overview. Native source databases remain read-only; Hermes keeps its existing limited audit evidence.

The v1.1.0 release record reports 191 Python tests, six Node test files and synthetic HTTP/browser checks; these are dated evidence. The current main checkout also includes later OpenCode/Claude/Codex native-reference work. A version string alone does not prove release, installation and running-process alignment. Local runtime state is not continuously verified; see the dated [baseline and limits](plans/bounded-delivery/findings.md). The earlier independent-user M3 trial remains historical unfinished work. CM owns supervised adoption, execution and task state when selected; direct native CLI execution remains available. CM's real continuation matrix does not block History's independent delivery.

## Current Priority

当前排队优先级：独立 SpecMesh 第一，History 第二，CM 第三。History 采用[独立、有界交付计划](plans/bounded-delivery/task_plan.md)：复用 headless 检索，隔离机器只读能力，验证增量可靠性与规模，再收口带来源交接、人的结果优先界面和独立发布。保留显式 resume command，执行由用户选定原生 CLI 或可选 CM 承担；受监督接管矩阵由 CM 验收。当前 CM 事实可选，未连接时明确 unknown。机器只读与增量性能子卡已验收，完整交付收口中。用户现已授权一次性完成 Linux 为主的完整交付；不使用 Goal 或定时续跑。

## Knowledge Map

- Current delivery plan (queued) → [plans/bounded-delivery/](plans/bounded-delivery/)
- Earlier Agent handoff implementation and partial evidence → [plans/agent-handoff-service/](plans/agent-handoff-service/)
- Dated release alignment → [plans/release-alignment/](plans/release-alignment/)
- Historical product validation / unfinished M3 → [plans/history-viewer-product-validation/](plans/history-viewer-product-validation/)

- How the system works → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Why durable choices were made → [docs/DECISIONS.md](docs/DECISIONS.md)
- Completed SpecMesh adoption → [plans/specmesh-adoption/](plans/specmesh-adoption/)
- First stable release record → [plans/release-v1.0.0/](plans/release-v1.0.0/)
- Feature delivery history → [docs/session-plans/](docs/session-plans/)

- Plan status index → [plans/README.md](plans/README.md)

## Approved next direction

本项目自行验收和发布；执行细节与冻结分母以 [bounded-delivery](plans/bounded-delivery/task_plan.md) 为准。用户于 2026-09-14 明确开始独立交付；HV-H0.1 与 HV-H1.2 已完成工作树验收，五阶段仍 0/5；增量/合成性能结果及后续阶段缺口见当前计划。既有主工作区和直接 push 授权保留，不强制另建 worktree/PR。
