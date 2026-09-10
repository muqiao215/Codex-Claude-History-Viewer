# Session Plan 004 — Usage Dashboard, Daily Briefing, Handoff Rendering, Plan-Aware History

> **Status**: DONE (delivered in working tree — pin commit hash at commit time)
> **Prereqs**: plan 002 (audit payloads), plan 003 (handoff)
> **Updated**: 2026-09-06
> **Scope note**: four upgrades derived from the Star-borrowing review (cpa-usage-keeper, Horizon, doocs/md, planning-with-files), implemented in one pass without breaking any project invariant (zero dependencies, idempotent migrations, deterministic audit, local-first privacy).

## Goal

Turn the viewer from a passive transcript browser into an insight surface:
show what agent work cost (tokens), what it produced (daily briefing), where
it is going (rendered handoffs), and how it connects to project planning
artifacts — all from local data, with optional LLM narrative reusing the
existing AI-audit provider configuration.

## Non-goals

- No cost estimates in currency (model prices change; tokens are the honest unit).
- No persistence for briefings (regenerate on demand).
- No new data sources (pi adapter deliberately deferred until a spike proves its session format).
- No writes to source directories or upstream databases.

## Delivered

### M1 — Token usage extraction + dashboard

- `parse_codex_session_file` aggregates cumulative `event_msg/token_count →
  info.total_token_usage` (keeps the max total seen). `token_count` events are
  now treated as telemetry and no longer surface as raw JSON messages.
- `parse_claude_session_file` sums per-message `message.usage`
  (`input_tokens`, `output_tokens`, `cache_creation/read_input_tokens` →
  `cached`) **deduplicated by `message.id`**: Claude Code splits one assistant
  message across several JSONL records that all re-carry the same usage, so
  per-id the largest variant is kept; id-less legacy records fall back to
  plain summation. Naive summation inflated a real sample 3.1× (4.03M vs the
  correct 1.28M).
- `sessions` table gains `tokens_input/output/cached/reasoning/total` columns
  via idempotent `ALTER TABLE`. Parser versions bumped (codex 4→5, claude
  3→5 across Windows/WSL/Linux, including a registration-consistency test) so
  existing caches re-parse and backfill on first start.
- `Indexer.query_usage` / `OpenCodeIndexer.query_usage` (native token columns)
  / `HermesStateIndexer.query_usage` (graceful zeros) aggregate totals, by
  day (local timezone), by project, and top-10 sessions.
- `GET /api/{system}/{source}/usage?start=&end=&project=`.
- UI: **⚡ Usage** toggle in the new *Insights* row; range selector
  (7d/30d/all), totals chips, per-day and per-project bars, clickable top
  sessions that open in the transcript pane.

### M2 — Daily work briefing

- `audit/briefing.py`: deterministic aggregation of day-filtered session
  summaries. The endpoint pages through **every** session in range (no silent
  40-session truncation; 2000-session runaway cap). Near-duplicate sessions
  (same cwd, touched-file Jaccard ≥ 0.5) merge **only for the highlights**
  section — blocked sessions and deliverables are built from the full list so
  a failed or unique-file session never disappears inside a higher-value
  duplicate. Sections: overview (sessions/projects/outcomes/friction/tokens),
  highlights (top 5 by value, enriched from up to 12 deterministic audits +
  stored AI audits), blocked (errored/interrupted with error samples),
  deliverables (unioned file ops, capped 15).
- `render_briefing_markdown` produces a scannable Markdown report.
- `GET /api/{system}/{source}/briefing?date=YYYY-MM-DD` (default: today,
  local). `POST /briefing` adds a narrative: LLM path (`build_briefing_llm_messages`
  + `parse_briefing_llm_response`, strict JSON `{narrative, suggestions}`) when
  a provider is configured; `generate_heuristic_briefing_narrative` fallback.
  POST bypasses the read-only gate because it writes nothing.
- UI: **📰 Briefing** toggle with date input (debounced refresh), rendered
  sections (click a highlight/blocked row or deliverable path to jump), 🤖
  Narrative button, 📋 Copy MD.

### M3 — Handoff preview, themes, export

- **👁 Preview** renders the current compact/standard handoff through the
  existing markdown pipeline into `#handoffPanel` (respects the handoff-detail
  select live).
- Themes: `plain` / `card` / `feishu` via `.handoff-theme-*` classes,
  persisted in localStorage.
- **📋 Rich** copies `text/html` + `text/plain` via `ClipboardItem` with
  plain-text fallback. **⬇ .md** / **⬇ .html** download via Blob;
  `buildHandoffHtmlDoc` produces a standalone themed HTML document.

### M4 — Plan-aware history

- `scan_plan_files(cwd)` read-only scans `task_plan.md` / `progress.md` /
  `findings.md` at the project root and under `plans/*`, plus
  `docs/session-plans/*.md` (caps: 80 files, 120 KB body). Empty/blank cwd is
  rejected (avoids scanning the process CWD).
- `extract_plan_sections` excerpts only well-known `## ` headings (task,
  goal, plan, status, next step, next action) at 700 chars each.
- `GET /api/{system}/{source}/plans?project=<cwd>`; `GET …/session/{id}/plans`
  filters entries to mtimes within ±7 days of the session window.
- UI: **🗒 Plans** toggle renders a collapsible timeline of planning files
  near the session. Stateless by design — no new tables.

### M5 — Design system

- `DESIGN.md` at repo root documents tokens, components, and rules for
  agent-driven UI changes (all six code themes must keep working).

## Tests

- `tests/test_usage.py` (12): cumulative extraction, transcript-noise fix,
  Claude per-message-id dedup (identical repeats, largest-variant, id-less
  fallback), registration-version consistency across all systems, persistence
  across reopen, aggregation filters.
- `tests/test_briefing.py` (15): merge/dedupe, **merge keeps blocked sessions
  and unique files**, **no session-count truncation**, markdown sections, LLM
  message/parse contract, heuristic narrative, **endpoint pagination beyond
  one page (210 sessions)**.
- `tests/test_plan_aware.py` (11): section extraction, scan conventions,
  **enumeration cap**, **bounded read (marker beyond the size cap never
  reaches sections)**, window filtering, session-metadata integration.
- `tests/test_insight_panels.js` (14): usage/briefing/plan HTML builders,
  handoff doc/theme/filename, preview rendering, **audit fetch refreshes a
  visible handoff preview on session switch**, **open Plans panel follows the
  new session**, **stale narrative cleared on date change / dropped on
  mid-flight date move**.
- Full suite at delivery: 182 python green, all 5 JS suites green.

## Verified against real data

- Codex: 67 sessions → 823,604,162 total tokens (765M cached); day buckets
  match sidebar dates.
- Claude: 4 sessions → **2,805,430 tokens after per-message-id dedup** (the
  naive sum had inflated this to 8,588,428); the 2026-08-07 bucket equals the
  single-file cross-check value 1,283,304. OpenCode: 96 sessions → 11,598,467
  tokens from its native columns.
- Single-file cross-check: parsed session usage (1,528,268) equals the
  briefing highlight token count for the same session.
- Plan scan on this repo surfaces the in-flight `plans/specmesh-r001-validation/`
  documents with goal/plan/status/next_step excerpts.
