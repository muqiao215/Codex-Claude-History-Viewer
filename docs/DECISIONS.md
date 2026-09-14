# Decisions

## 2026-02-10 — Keep the required runtime dependency-free

Decision:

Use the Python standard library and a static browser frontend without a build step.

Why:

The viewer should start directly against local logs with minimal setup on personal machines.

Rejected:

A framework-heavy backend or mandatory frontend toolchain.

Revisit when:

A required feature cannot be delivered safely or maintainably with the current runtime.

## 2026-06-27 — Separate deterministic evidence from AI interpretation

Decision:

Parse tools, files, commands, errors, remote activity, tests, and outcomes deterministically. AI may interpret a compact payload, but every completion claim must remain traceable to evidence.

Why:

Operational facts must be reproducible and inspectable; model output alone is not a trustworthy audit trail.

Rejected:

Letting an LLM read complete transcripts and infer the factual action record.

Revisit when:

Never for factual provenance; only the compact semantic interpretation layer may evolve.

## 2026-06-27 — Keep processing local and AI audit opt-in

Decision:

Index and analyze histories locally. Only send a compacted audit payload to a configured model after an explicit user action.

Why:

Development transcripts can contain secrets, private paths, proprietary code, and operational details.

Rejected:

Automatic uploads, background AI auditing, and bulk remote processing of history.

Revisit when:

The user explicitly chooses a different privacy model with clear controls.

## 2026-06-27 — Use per-source adapters behind one UI contract

Decision:

Normalize Codex, Claude, and OpenClaw JSONL while adapting OpenCode and Hermes SQLite sources into the same browsing API. Treat tool-owned databases as read-only.

Why:

The histories differ in storage and schema, but users need one coherent browsing experience without risking source data.

Rejected:

Mutating upstream databases or forcing all tools into one physical storage format.

Revisit when:

A source exposes a stable official API that is safer or richer than its current local representation.

## 2026-07-22 — Make handoff deterministic and separate from AI Audit

Decision:

Build Agent continuation capsules from normalized evidence, user corrections, verification, and Git state. Keep them independent from optional AI audit.

Why:

Continuation context must work offline, remain compact, and avoid invented completion claims.

Rejected:

Copying full transcripts or requiring an LLM to summarize every handoff.

Revisit when:

A new source lacks enough deterministic structure to produce a useful capsule.

## 2026-09-06 — Treat token_count telemetry as data, not transcript

Decision:

Fold cumulative `event_msg/token_count` payloads into per-session `tokens_*` columns during indexing and stop surfacing them as raw JSON messages; parse Claude's per-message `usage` the same way. Store usage denormalized on `sessions` so listing, briefing, and aggregation never re-parse transcripts.

Why:

Usage was already on disk but invisible, and the previous fallback flooded transcripts with one raw JSON block per token-count event (thousands per session).

Rejected:

Currency cost estimates (prices change; tokens are the honest unit) and a separate usage table (no query needs message-level granularity yet).

Revisit when:

A source exposes model-level pricing or per-turn cost data worth showing next to token counts.

## 2026-09-06 — Keep plan-aware scanning stateless and read-only

Decision:

`/plans` endpoints scan the session's working directory on request (capped: 80 files, 120 KB bodies, well-known sections only) instead of persisting plan files in the index. Briefing generation is likewise computed on demand with no storage, and its POST route is allowed for read-only sources because it writes nothing.

Why:

Plans change on disk constantly; a second copy in SQLite would go stale and add migration surface for near-zero query benefit. Read-only scanning respects the "upstream data is never mutated" invariant.

Rejected:

A `plan_files` SQLite table with mtime-sync, and indexing plan content into `search_blob` (would pollute keyword search across unrelated projects).

Revisit when:

Cross-project plan search or plan-history diffing becomes a real workflow.


## 2026-09-06 — Validate the existing product before expanding scope

历史优先级；当前执行方向由下方 2026-09-14 独立交付决定承接。M3 仍未完成，不再作为活动主线。

Decision:

Prioritize independent review of the insight-upgrade fixes, real browser acceptance,
and a first-time user completing search → evidence → handoff. Keep SpecMesh as lightweight
continuity documentation. The active plan is `plans/history-viewer-product-validation/`.

Why:

The user explicitly focused this next plan on History Viewer. The existing feature set
already supports a useful independent product; correctness and successful first use are
the next evidence needed. Green unit tests do not establish either on their own.

Rejected:

Parallel rewrites, new data sources, extra platform features, or expanding SpecMesh Map
before validating the current workflow.

Revisit when:

The current workflow has passed independent acceptance and a concrete user need justifies
an extension. Code cleanup needed to fix an observed defect remains within scope.

## 2026-09-11 — Integrate against existing repository authority

Reuse the existing storage/parsers and keep SpecMesh independently callable. Do not install a second TaskHub from a proposal or equate historical handoff with live completion. The human overview and headless retrieval have separate entry points. See [scope and remaining limits](CODEKIT-INTEGRATION.md). Status: implemented for v1.1.0; broader roadmap gates remain planned.

## 2026-09-14 — History 独立交付与可选原生续接

决定：复用现有 headless CLI/parser/indexer，将只读能力边界、增量可靠性、带来源的交接候选、人的结果优先界面和发布分别验收。机器检索不依赖 Web、CM 或模型；SpecMesh 文件仍保存审查后的项目事实。History 继续提供显式原生 resume command；实际执行由用户选定原生 CLI 或可选 CM 承担，History 不执行 provider 会话。经 CM 的受监督接管、授权和多设备协调归 CM，TaskHub 不成为直接续接或独立发布前置条件。CM 实时状态是可选适配，未连接时 unknown。

原因：用户明确选择三个独立项目和有限任务卡，SpecMesh 第一、History 第二、CM 第三。旧总交接附件的 9 月 11 日表格不是最新事实，已有接口和局部真实续接结果应复用，不能为重排范围全部重做，也不能将局部执行推广为全矩阵完成。

执行边界：本项目 [bounded-delivery](../plans/bounded-delivery/task_plan.md) 当前 queued，只详写 HV-H0.1；一实现者加按需一审查者，最多两轮修正，收口退出，不用 Goal/loop/自动续卡。保留本机主工作区；已授权直接 push 不因本决定增加 worktree/PR 门槛，同仓确需并行才隔离。本次仅规划，不提交/推送/发布。

拒绝：重写已有 parser、同时扩展多种传输/服务、把原生执行迁入 History、建立第二份项目决定库，以及未测量就承诺大日志性能。旧 M3 保留历史未完状态；旧 HV-H3 局部验收保留，但退出本项目五阶段独立分母。

重访条件：已选任务卡的实测证明显式 CLI/refresh 不足，或稳定接口有具体适配缺口时，另选范围明确的后续卡；不能以“将来可能需要”为由启动常驻调度或无限研究。


## 2026-09-15 — 显式刷新与原子缓存更新

机器热查返回缓存并标记 freshness unknown；整树可读性检查放在构造/refresh，交接只验证所选文件。逐文件解析写入一个事务，成功才清理消失路径，失败保留原索引。拒绝为了控制内存而分批提交半份结果，也不以后台刷新掩盖时效边界。固定合成基准证明当前方式达到门槛；若跨刷新分页或超大单文件出现明确需求，再单独建立修订/资源边界协议。
