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
