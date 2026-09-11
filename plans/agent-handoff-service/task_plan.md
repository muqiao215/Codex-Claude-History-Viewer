# Agent handoff service and human work overview

## Status / owner

Status: in_progress after shared-core/headless-CLI implementation. Owner: Viewer maintainers; CM owns task execution and global coordination. Agent handoff is the primary workflow acceptance objective; independent-user trial does not replace it.

## Observed baseline

`history_core/sources.py` contains the existing real source parsers/indexers extracted from app.py. `history_core/service.py` offers search/handoff/workspace; `python -m history_core` works without Web. Native OpenCode/Hermes databases remain read-only. `/workspace` is historical overview, `/history` is secondary browsing/settings. CM already has verified native OpenCode adoption; this plan extends and revalidates its integration, not reinvents it.

## Product requirements

Human default view: project progress, evidence-backed results, blockers, decisions and next action. Role/theme/source/filter/cleanup controls belong to secondary interfaces. Historical estimates must be visibly distinct from authenticated current CM state. Empty, stale or inaccessible evidence is actionable information, not fabricated completion.

Machine interface: bounded explicit-source queries, deterministic schema-versioned results, selected context rather than whole transcript dumps, and headless operation independent of opening Web. No source mutation or implicit LLM use. A future resident service must be optional and resource-bounded; CLI remains usable alone.

## Phases

| ID | Work / actual seam | Acceptance | State |
|---|---|---|---|
| HV-H0 | Stabilize `history_core` capability boundary; separate legacy mutators from read service | Machine imports never start HTTP/background/model; deny source writes and path escape | planned |
| HV-H1 | Incremental index lifecycle, freshness/cursor and bounded daemon | Restart resumes cursor, source rotation/deletion handled, caps CPU/RAM/backlog, CLI works without daemon | planned |
| HV-H2 | Versioned candidate/handoff envelope consumed by CM headlessly | Full identity/revision, provenance, observed time, source evidence, repository binding, unknown state; contract fixtures in both repos | in_progress: native-reference v2 and independent CM revalidation implemented; broader handoff envelope remains |
| HV-H3 | Real Agent continuation acceptance with CM | Selected original provider session receives bounded task; context recalled and current repo checked; output accepted by task owner | in_progress: actual same-session recall/current-file canary passed; full matrix remains |
| HV-H4 | Human overview consumes authorized live task facts separately from history | Progress/result/blocker/decision/next-action navigation; no ambiguous completion or settings-heavy first screen | planned |
| HV-H5 | Packaging/platform and privacy acceptance | Linux and supported Windows/WSL paths, clean install, upgrade/cache migration, source DB unchanged, no unintended network requests | planned |

## Real continuation matrix (HV-H3)

1. Select a controlled repository and an existing native session with known earlier decisions; record explicit task scope, provider/model/version, store identity and source revision without committing private transcript text.
2. Retrieve a compact candidate through the headless interface. CM revalidates identity and current checkout, then resumes natively; exported text alone is not proof.
3. Verify session ID continuity, recalled relevant decisions, actual current-file checks, bounded output, and accepted evidence. Keep native provider memory and reviewed SpecMesh facts separate.
4. Repeat with stale revision, missing store, wrong project/device, unknown model/quota, cancel, and crash/restart. Reject mismatches; never silently create a fresh conversation.
5. Report unsupported cross-provider resume as unsupported. Cross-provider handoff may use explicit context export but must be labeled a new session.
6. Existing historical CM adoption evidence is a baseline; this gate validates the new interface/released versions, not a universal guarantee of lossless memory.

## Rollback / constraints

Keep source databases immutable. Derived indexes can be rebuilt; retain schema-version compatibility or explicitly invalidate cache. Fall back to CLI/secondary history interface if daemon or overview fails, preserving current unknown/error states. Do not restore old unsafe cleanup behavior as a rollback side effect. No requirement to expose private paths/transcripts remotely.

## Dependencies / next

CM execution and native identity authority: https://github.com/muqiao215/ControlMesh/blob/main/plans/runtime-convergence/task_plan.md
SpecMesh reviewed continuity gate: https://github.com/muqiao215/specmesh/blob/main/plans/independent-plugin-port/task_plan.md
Next: integrate [native-reference v2](../../docs/native-session-contract.md) with bounded service/index lifecycle and the broader handoff envelope. Extend the real continuation matrix without creating a competing TaskHub.
