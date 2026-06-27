# Session Plans Index

Tracking documents for major feature work on Codex-Claude-History-Viewer.
Each plan is a self-contained spec: goal, scope, milestones, acceptance criteria, and a status header that points to the delivering commit.

## Active Plans

| # | Plan | Status | Updated | Commit |
|---|---|---|---|---|
| 001 | [Agent Value Audit](./001-agent-value-audit.md) | **M1–M3 DONE** · M4–M6 pending | 2026-06-27 | `4462cfb` |
| 002 | [Detail Panel, Tool Collapse, AI Audit](./002-detail-panel-and-ai-audit.md) | Not started | 2026-06-27 | — |

## Status Legend

- **DONE** — fully implemented, tested, verified.
- **M1–M3 DONE** — phase 1 complete (extractor + SQLite + badges); later milestones pending.
- **In progress** — actively being worked on.
- **Not started** — planned but not begun; prereqs may still apply.

## Progress Summary

### Phase 1 — Deterministic Audit (delivered)

Shipped in `4462cfb` on 2026-06-27:

- `audit/` package: `schema` · `command_classifier` · `scoring` · `extractor` · `__init__` (public API + idempotent DB migration).
- Per-session signals persisted in SQLite: `files_touched` (local / remote / inferred), `tools_used`, `command_intents`, `remote_context`, `outcome_signal`, `value_score`, `friction_score`, `action_density`.
- Sidebar renders compact audit badge chips with aria labels; sort dropdown gains a **Value signal** option.
- 20 new audit tests; full suite 43/43 green.
- Bonus: `OpenCodeIndexer` adds OpenCode as a 5th read-only source (auto-detected at `~/.local/share/opencode/opencode.db`).

### Phase 2 — Detail Surface + AI Layer (planned)

See [`002-detail-panel-and-ai-audit.md`](./002-detail-panel-and-ai-audit.md). Three independent milestones that consume the audit data already collected:

- **M4** — Detail-page audit panel (files / commands / errors / outcome / evidence jump).
- **M5** — Tool-call collapse timeline (compress long transcripts).
- **M6** — Optional AI audit layer (intent / checklist / deliverables / gap analysis).

## Conventions

- File names: `NNN-kebab-title.md`, zero-padded, monotonic.
- Each plan opens with a `> **Status**` blockquote carrying: status word, prereqs, last-updated date, delivering commit.
- When a plan is fully delivered, leave the file in place — do not delete. Mark the status `DONE` and add the delivering commit hash.
- Link new plans from the table above in the same edit that creates the file.
