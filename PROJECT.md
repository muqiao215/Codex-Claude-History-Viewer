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

The stable `v1.2.0` Linux release delivers the public read-only reader, revision-bound pagination, atomic incremental indexing, bounded source-aware handoff and the six-section human workspace. Weak-session cleanup is disabled and demo caches are isolated. Five sources have synthetic read-only coverage; Hermes ordinary audit remains explicitly unsupported.

Linux delivery is complete (5/5). Release source is `eb99792dadc46ca2b352be8b56ea16daa2138c6c`; the published archive, local launcher and actual test process identities were verified on 2026-09-15. The process is now stopped; this dated observation is not continuous runtime monitoring. See [release evidence](plans/bounded-delivery/progress.md). Windows/WSL and live model/CM execution are outside this release acceptance. The historical M3 independent-user trial remains unfinished and is not counted as passed.

## Current Priority

用户指定专注 History Viewer、以 Linux 为主。独立交付计划 HV-independent-linux-v2 已完成全部 5 个阶段并发布 v1.2.0；当前无待执行项，后续依据新的具体使用反馈另立任务。不使用 Goal 或定时续跑。

## Knowledge Map

- Completed Linux delivery plan → [plans/bounded-delivery/](plans/bounded-delivery/)
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

本项目已自行验收、发布并完成 Linux 本机安装；冻结分母与证据以 [bounded-delivery](plans/bounded-delivery/task_plan.md) 为准，5/5 complete。既有主工作区和直接 push 授权保留，不强制另建 worktree/PR。
