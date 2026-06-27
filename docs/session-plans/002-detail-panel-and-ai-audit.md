# 002 — Detail Audit Panel, Tool Collapse, AI Audit

> **Status**: Not started.
> **Prereqs**: [001 M1–M3](./001-agent-value-audit.md) (delivered in `4462cfb`).
> **Last Updated**: 2026-06-27.

## Goal

The sidebar now exposes deterministic audit signals (files, tools, commands, outcome, value score). Phase 2 makes those signals **actionable inside the detail view** and adds an **optional LLM audit** layer for high-value sessions.

Three milestones. They can be executed independently; recommended order is M4 → M5 → M6.

---

## M4 — Detail-page Audit Panel (spec §17, §19 M4)

**Goal**: open a session and immediately see a structured action footprint, not just a chat scroll.

### Tasks

1. Add an **Agent Value Audit** panel to the right side of the session detail view (collapsible).
2. Sections in this order:
   - **Intent** — first user prompt (truncated, expandable).
   - **Outcome** — `outcome_signal` + last assistant reply summary.
   - **Deliverables** — `files_touched.local` + `files_touched.remote`, grouped; each row shows edit/write counts + confidence.
   - **Command Intents** — `command_intents` as a labeled histogram (TEST / BUILD / DEPLOY / REMOTE / DEBUG / …).
   - **Friction** — `friction_score` + error samples (first 3).
   - **Value** — `value_score` (0–100) with a one-line interpretation hint.
3. Each row carries an **evidence id** of the form `{session_id}:kind:seg` (spec §8). Clicking scrolls to and highlights the corresponding message/tool block in the transcript.
4. Clicking a file path filters the sidebar to sessions that touched the same path (cross-session drill-down).

### Acceptance Criteria

```text
Open any session → answer without scrolling the transcript:
  - What did the user actually ask for?
  - Which files did the agent touch?
  - Which remote commands ran?
  - Did tests run?
  - Did it converge?
Click any audit row → transcript jumps to the evidence.
```

### Data Already Available (no backend changes needed)

`GET /api/sessions/{id}` response carries `files_touched`, `tools_used`, `command_intents`, `remote_context`, `outcome_signal`, `value_score`, `friction_score`, `action_density` (delivered in `4462cfb`). `audit/extractor.py` already emits evidence ids on every `Evidence` and `FileFootprint`; surface them via a new `/api/sessions/{id}/audit` endpoint or extend the existing response.

### Estimated Effort

Frontend-heavy. ~1 day if evidence-jump is MVP; ~2 days with cross-session file drill-down.

---

## M5 — Tool Call Collapse Timeline (spec §17, §19 M5)

**Goal**: long sessions are currently drowned in tool output. Compress the transcript into a scannable action timeline.

### Tasks

1. Tool blocks render **collapsed** by default. A collapsed block shows a one-line summary:
   - `bash` → command (truncated to 80 chars) + exit status icon.
   - `edit` / `write` / `str_replace_editor` → file path + change kind (+/- lines if cheap).
   - other tools → tool name + first argument.
2. Tool result shows success/error badge; stderr highlighted; long stdout truncated to N lines with "show more".
3. User can expand any block inline; "expand all" / "collapse all" controls at the top.
4. Optional: a slim left-rail timeline strip showing tool blocks as dots colored by outcome, click to jump.

### Acceptance Criteria

```text
A 200-message session with 80 tool calls fits in ~1 screen of scanning.
User can expand any block to see full detail.
Errors are visible without expanding.
```

### Estimated Effort

~1.5 days. The existing transcript renderer already classifies messages by `kind`; this is mostly CSS + a default-collapsed state + summary extraction.

---

## M6 — AI Audit Layer (spec §18, §19 M6)

**Goal**: for high-value sessions, generate an LLM judgment of whether the user's intent was actually delivered. **Strictly opt-in; never runs without a user click.**

### Tasks

1. Define `audit_json` schema (spec §18):
   ```json
   {
     "user_intent": "...",
     "checklist": [{"item": "...", "status": "done|partial|skipped|failed", "evidence_ids": [...]}],
     "deliverables": [...],
     "gaps": [...],
     "next_action": "..."
   }
   ```
2. Add `audit_status` column: `none | pending | done | error`.
3. Add **Generate AI Audit** button on the detail panel (M4). Calls `/api/sessions/{id}/audit`.
4. Backend builds a compact prompt from `to_llm_audit_input(payload)` (already exposed in `audit/schema.py`) → sends to model → stores returned JSON in SQLite.
5. Frontend renders the checklist with per-item evidence chips; clicking a chip jumps to the evidence (reuses M4 jump logic).
6. **Regenerate** button replaces the stored audit; **delete** clears it.
7. Cost guard: refuse to audit sessions with `value_score < threshold` (default 20) — not worth the tokens.

### Acceptance Criteria

```text
Open a high-value session → click "Generate AI Audit" → receive:
  - User's real intent (1-2 sentences)
  - Checklist with per-item status + evidence links
  - Deliverables list
  - Gap analysis
  - Next action suggestion
Regenerate / delete both work.
Low-value sessions refuse with a clear message.
```

### Open Questions

- **Model provider**: local (ollama) vs. Anthropic vs. OpenAI? Configurable via CLI flag, default to whatever the user already has wired.
- **Key management**: read from env (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) — no key storage in the app.
- **Privacy**: AI audit sends the compacted payload (not the raw transcript) — already minimises data. Document this clearly in the UI.

### Estimated Effort

~2-3 days end-to-end. Schema + storage is half a day; provider integration + UI is the bulk.

---

## Cross-cutting Follow-ups

Collected during Phase 1; not blockers for M4-M6 but worth batching:

- **Backfill CLI**: `python3 app.py --backfill-audit` to re-extract audit fields for all sessions whose `audit_version < AUDIT_VERSION`. Currently re-indexing happens automatically on staleness, but an explicit one-shot is friendlier.
- **OpenCode audit depth**: OpenCode sessions currently emit neutral defaults (no JSONL). If OpenCode adds a JSONL export or we synthesize one from `opencode.db` parts, wire it through the extractor.
- **Test coverage for OpenCodeIndexer**: currently exercised only via the live HTTP smoke test. Add `tests/test_opencode_indexer.py` mirroring the Hermes tests in `test_session_previews.py`.
- **Demo data for OpenCode**: ship a synthetic `demo/opencode/opencode.db` so the demo path shows all five sources.
