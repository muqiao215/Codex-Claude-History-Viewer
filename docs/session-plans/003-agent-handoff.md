# 003 — Agent Handoff Context Capsule

> **Status**: DONE
> **Scope**: Codex, Claude, OpenClaw, and OpenCode sessions. Hermes remains excluded because its current adapter does not expose deterministic audit evidence.
> **Released**: `v1.0.0` (2026-08-08).

## Goal

Turn a long session into a small, evidence-backed context capsule that another agent can continue from without receiving the full transcript.

## Contract

The handoff is separate from AI Audit and is generated deterministically. It contains:

- session id and working directory;
- original goal plus later user constraints and corrections;
- completion status;
- high-confidence local and remote file mutations;
- observed commands with explicit exit status when available;
- remaining work and next action, using stored AI Audit gaps only when one exists;
- message/evidence references and current Git commit/worktree state.

The UI offers `Compact` and `Standard` variants and copies the selected form as a `[HANDOFF]` block. Raw JSONL, system/developer prompts, reasoning, full tool output, and inferred file paths are excluded.

## Codex Compatibility

Current Codex sessions wrap tools in `custom_tool_call(name=exec)` JavaScript. The audit normalizer unwraps nested `exec_command` and `apply_patch` calls, treats injected environment messages as system context, and uses structured `exit_code` values before textual error heuristics.

## Acceptance

- A current Codex session reports the actual user request rather than `<environment_context>`.
- Nested commands, patch paths, and exit codes appear in the handoff.
- Successful output containing the word `error:` is not counted as a failed command when `exit_code` is zero.
- Compact output is no larger than standard output and both retain evidence locations.
- OpenCode tool parts produce deterministic audit evidence and handoff output without mutating its source database.
