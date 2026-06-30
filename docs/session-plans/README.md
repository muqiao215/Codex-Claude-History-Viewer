# Session Plans Index

Tracking documents for major feature work on Codex-Claude-History-Viewer.
Each plan is a self-contained spec: goal, scope, milestones, acceptance criteria, and a status header that points to the delivering commit.

## Active Plans

| # | Plan | Status | Updated | Commit |
|---|---|---|---|---|
| 001 | [Agent Value Audit](./001-agent-value-audit.md) | **M1–M3 DONE** · M4–M6 pending | 2026-06-27 | `4462cfb` |
| 002 | [Detail Panel, Tool Collapse, AI Audit](./002-detail-panel-and-ai-audit.md) | **M4, M5 DONE** · M6 pending | 2026-06-30 | `90e5f09` · M5 `03e6ba0` |

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

### Phase 2 — M5 Tool Call Collapse Timeline (delivered)

M5 of plan 002 shipped on 2026-06-30:

- Backend attaches a `tool_summary` dict to every `tool_use` / `tool_result` message across all three parsers (codex `function_call`/`function_call_output`, claude `tool_use`/`tool_result` content blocks, openclaw). Summary carries: `name`, `category` (shell/edit/read/search/deploy/other), `headline` (≤80 chars, whitespace-collapsed), `file_path`, `change_kind`, `lines_added`/`lines_removed`, `exit_status` (ok/error/None), `exit_code`, `output_preview` (200 chars), `is_error`. Persisted in a new `tool_summary_json` SQLite column on the codex `messages` table.
- Frontend renders tool messages **collapsed by default**: a one-line summary bar (chevron + category icon + tool name + headline + file path + diff counts + status badge) replaces the verbose body. Char-collapse controls are suppressed while tool-collapsed; search matches auto-expand.
- **Expand all / Collapse all** buttons appear in the session header when tool messages are present. URL `?expand_tools=1` flips the default to expanded. Per-block click toggles individual state.
- Tool results truncate to 20 lines with a "Show all N lines" affordance; stderr-tinted left border on errored results; status badge (✓/✕/·) visible without expanding.
- **Timeline rail** (aggressive Phase 9 add): a 24px-wide strip left of the transcript renders one colored dot per tool message — green (ok), red (error), muted (unknown / pre-result). Dot vertical position is proportional to message index; click jumps to that message.
- New CSS classes (`.msg.tool-use`, `.msg.tool-result`, `.msg-tool-summary`, `.msg-tool-status.{ok,error,unknown}`, `.msg-tool-output-truncated`, `.tool-timeline`, `.tool-timeline-dot`) reuse existing theme CSS vars and badge color classes.
- 42 new backend tests in `tests/test_tool_summary.py` (classification, truncation, diff counting, each summarize function, parser integration); 18 new frontend tests in `tests/test_tool_collapse.js` (summary HTML, toggle, expand/collapse all, truncation). Full suite: 94/94 python green; 45/45 JS green.
- Demo data: `demo/codex/sessions/2026/02/12/rollout-...-demo-dense-0001.jsonl` — 248 lines, 247 messages, 117 tool calls (16 errors, 101 successes). Exercises the collapse/timeline at spec scale (200+ msgs, 80+ tools).

## Conventions

- File names: `NNN-kebab-title.md`, zero-padded, monotonic.
- Each plan opens with a `> **Status**` blockquote carrying: status word, prereqs, last-updated date, delivering commit.
- When a plan is fully delivered, leave the file in place — do not delete. Mark the status `DONE` and add the delivering commit hash.
- Link new plans from the table above in the same edit that creates the file.
