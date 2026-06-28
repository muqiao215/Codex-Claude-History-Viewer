# Session Plans Index

Tracking documents for major feature work on Codex-Claude-History-Viewer.
Each plan is a self-contained spec: goal, scope, milestones, acceptance criteria, and a status header that points to the delivering commit.

## Active Plans

| # | Plan | Status | Updated | Commit |
|---|---|---|---|---|
| 001 | [Agent Value Audit](./001-agent-value-audit.md) | **M1–M3 DONE** · M4–M6 pending | 2026-06-27 | `4462cfb` |
| 002 | [Detail Panel, Tool Collapse, AI Audit](./002-detail-panel-and-ai-audit.md) | **M4 DONE** · M5, M6 pending | 2026-06-28 | `4db9d2b` |

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

### Phase 2 — M4 Detail-page Audit Panel (delivered)

M4 of plan 002 shipped on 2026-06-28:

- New endpoint `GET /api/{system}/{source}/sessions/{id}/audit` re-extracts the full `AuditPayload` (evidence, prompts, errors included) via `Indexer.build_session_audit`; gracefully returns 404 for sources without a backing JSONL.
- New sidebar filter `?file=/path` narrows the session list to those that touched a given path (SQL LIKE coarse + Python exact match refinement, SQL-LIKE metacharacters escaped).
- `#auditPanel` in the session header renders six sections in spec order: **Intent** (expandable) · **Outcome** (badge + reply) · **Deliverables** (Local/Remote/Inferred groups, click filters sidebar) · **Command Intents** (sorted histogram) · **Friction** (score + first 3 error samples) · **Value** (badge + tier label + one-line interpretation).
- Click an evidence-id row → transcript lazy-loads the window if needed, scrolls the target message into view, and flashes the `.audit-flash` highlight (1.6 s).
- New CSS classes reuse existing theme CSS vars and the existing `.audit-badge` / `.badge-*` chip variants — no new color palette introduced.
- 9 new backend tests in `tests/test_audit_endpoint.py`; 15 new frontend tests in `tests/test_audit_panel.js`. Full suite: 52/52 python green; 27/27 JS green.

## Conventions

- File names: `NNN-kebab-title.md`, zero-padded, monotonic.
- Each plan opens with a `> **Status**` blockquote carrying: status word, prereqs, last-updated date, delivering commit.
- When a plan is fully delivered, leave the file in place — do not delete. Mark the status `DONE` and add the delivering commit hash.
- Link new plans from the table above in the same edit that creates the file.
