import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import app  # noqa: E402
from audit.briefing import (  # noqa: E402
    BRIEFING_HIGHLIGHT_LIMIT,
    build_briefing,
    build_briefing_llm_messages,
    generate_heuristic_briefing_narrative,
    parse_briefing_llm_response,
    render_briefing_markdown,
)


def _session(session_id, cwd, *, value_score=50, outcome="completed", friction=0,
             files=None, title=None, tokens_total=0):
    local = [
        {"path": path, "edit_count": 1, "write_count": 0, "confidence": "high"}
        for path in (files or [])
    ]
    return {
        "id": session_id,
        "title": title or f"Session {session_id}",
        "cwd": cwd,
        "value_score": value_score,
        "outcome_signal": outcome,
        "friction_score": friction,
        "files_touched": {"local": local, "remote": [], "inferred": []},
        "tokens_total": tokens_total,
    }


class BuildBriefingTests(unittest.TestCase):
    def test_merges_near_duplicate_sessions_in_same_project(self):
        items = [
            _session("a", "/proj", value_score=80, files=["/proj/app.py", "/proj/util.py"]),
            _session("b", "/proj", value_score=40, files=["/proj/app.py", "/proj/util.py", "/proj/extra.py"]),
        ]
        briefing = build_briefing(items)
        self.assertEqual(briefing["overview"]["session_count"], 2)
        self.assertEqual(briefing["overview"]["merged_count"], 1)
        self.assertEqual(len(briefing["highlights"]), 1)
        self.assertEqual(briefing["highlights"][0]["session_id"], "a")
        self.assertEqual(briefing["highlights"][0]["merged_count"], 1)

    def test_keeps_distinct_projects_separate(self):
        items = [
            _session("a", "/proj-one", files=["/proj-one/app.py"]),
            _session("b", "/proj-two", files=["/proj-two/app.py"]),
        ]
        briefing = build_briefing(items)
        self.assertEqual(briefing["overview"]["merged_count"], 0)
        self.assertEqual(briefing["overview"]["project_count"], 2)

    def test_blocked_section_lists_errored_and_interrupted(self):
        items = [
            _session("ok", "/proj", outcome="completed"),
            _session("bad", "/proj", outcome="errored", friction=7),
            _session("stopped", "/proj", outcome="interrupted", friction=3),
        ]
        audits = {
            "bad": {"audit": {"errors": {"count": 2, "samples": ["Traceback (boom)"]}}, "ai_audit": {}},
        }
        briefing = build_briefing(items, audits=audits)
        blocked_ids = [item["session_id"] for item in briefing["blocked"]]
        self.assertEqual(blocked_ids, ["bad", "stopped"])
        self.assertEqual(briefing["blocked"][0]["error_sample"], "Traceback (boom)")

    def test_deliverables_union_with_counts(self):
        # File sets stay below the merge threshold so both sessions survive.
        items = [
            _session("a", "/proj", files=["/proj/app.py"]),
            _session("b", "/proj", files=["/proj/app.py", "/proj/new.py", "/proj/other.py"]),
        ]
        briefing = build_briefing(items)
        paths = {item["path"]: item for item in briefing["deliverables"]}
        self.assertEqual(paths["/proj/app.py"]["edit_count"], 2)
        self.assertEqual(paths["/proj/new.py"]["edit_count"], 1)

    def test_merge_keeps_blocked_and_unique_files_of_merged_session(self):
        # Review repro: high-value completed A merges with low-value failed B
        # (file Jaccard 2/3). B's failure and its unique file must survive.
        items = [
            _session("a", "/proj", value_score=80, outcome="completed",
                     files=["/proj/app.py", "/proj/util.py"]),
            _session("b", "/proj", value_score=40, outcome="errored", friction=5,
                     files=["/proj/app.py", "/proj/util.py", "/proj/new.py"]),
        ]
        briefing = build_briefing(items)
        self.assertEqual(briefing["overview"]["merged_count"], 1)
        self.assertEqual(briefing["overview"]["outcomes"].get("errored"), 1)
        blocked_ids = [item["session_id"] for item in briefing["blocked"]]
        self.assertIn("b", blocked_ids, "merged-away failed session must stay blocked")
        self.assertEqual(
            briefing["overview"]["outcomes"].get("completed"), 1)
        deliverable_paths = {item["path"] for item in briefing["deliverables"]}
        self.assertIn("/proj/new.py", deliverable_paths, "unique file of merged session must survive")

    def test_no_truncation_of_session_count(self):
        items = [
            _session(f"s{i}", f"/p{i % 3}", value_score=i % 7, tokens_total=100)
            for i in range(41)
        ]
        briefing = build_briefing(items)
        self.assertEqual(briefing["overview"]["session_count"], 41)
        self.assertEqual(briefing["overview"]["tokens_total"], 4100)
        self.assertLessEqual(len(briefing["highlights"]), BRIEFING_HIGHLIGHT_LIMIT)

    def test_highlights_capped_but_blocked_lists_all_failed(self):
        items = [_session(f"ok{i}", f"/p{i}", value_score=90) for i in range(8)]
        items += [_session(f"bad{i}", f"/q{i}", value_score=5, outcome="errored", friction=1)
                  for i in range(3)]
        briefing = build_briefing(items)
        self.assertEqual(len(briefing["highlights"]), BRIEFING_HIGHLIGHT_LIMIT)
        self.assertEqual(len(briefing["blocked"]), 3)

    def test_overview_counts_and_tokens(self):
        items = [
            _session("a", "/p1", outcome="completed", tokens_total=1200),
            _session("b", "/p2", outcome="errored", tokens_total=300),
        ]
        briefing = build_briefing(items)
        self.assertEqual(briefing["overview"]["outcomes"], {"completed": 1, "errored": 1})
        self.assertEqual(briefing["overview"]["tokens_total"], 1500)
        self.assertEqual(briefing["overview"]["friction_total"], 0)


class RenderBriefingMarkdownTests(unittest.TestCase):
    def test_markdown_contains_all_sections(self):
        items = [
            _session("a", "/proj", value_score=90, files=["/proj/app.py"], tokens_total=999,
                     title="Ship the feature"),
            _session("bad", "/proj", outcome="errored", friction=5),
        ]
        audits = {
            "a": {"audit": {"first_user_prompt": "Build the thing"}, "ai_audit": {"next_action": "Deploy it"}},
        }
        briefing = build_briefing(items, audits=audits, date_label="2026-09-06", source="codex")
        markdown = render_briefing_markdown(briefing)
        self.assertIn("# Agent work briefing — 2026-09-06 (codex)", markdown)
        self.assertIn("## Overview", markdown)
        self.assertIn("## Highlights", markdown)
        self.assertIn("Ship the feature", markdown)
        self.assertIn("goal: Build the thing", markdown)
        self.assertIn("next: Deploy it", markdown)
        self.assertIn("## Blocked", markdown)
        self.assertIn("## Deliverables", markdown)
        self.assertIn("/proj/app.py", markdown)

    def test_empty_day_renders_placeholder_sections(self):
        briefing = build_briefing([], date_label="2026-09-06", source="claude")
        markdown = render_briefing_markdown(briefing)
        self.assertIn("No sessions recorded for this period.", markdown)
        self.assertIn("Nothing blocked.", markdown)
        self.assertIn("No file changes observed.", markdown)


class BriefingLlmTests(unittest.TestCase):
    def test_llm_messages_carry_payload_and_schema(self):
        briefing = build_briefing([_session("a", "/proj")])
        messages = build_briefing_llm_messages(briefing)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("STRICT JSON", messages[0]["content"])
        self.assertIn('"session_count"', messages[1]["content"])

    def test_parse_accepts_fenced_json(self):
        raw = '```json\n{"narrative": "Work went fine.", "suggestions": ["Deploy"]}\n```'
        result = parse_briefing_llm_response(raw, model="test-model")
        self.assertEqual(result["narrative"], "Work went fine.")
        self.assertEqual(result["suggestions"], ["Deploy"])
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["source"], "llm")

    def test_parse_rejects_empty_and_missing_narrative(self):
        with self.assertRaises(ValueError):
            parse_briefing_llm_response("")
        with self.assertRaises(ValueError):
            parse_briefing_llm_response('{"suggestions": []}')

    def test_heuristic_narrative_reports_blockers(self):
        items = [
            _session("bad", "/proj", outcome="errored", friction=4, title="Broken build"),
        ]
        briefing = build_briefing(items)
        narrative = generate_heuristic_briefing_narrative(briefing)
        self.assertEqual(narrative["source"], "heuristic")
        self.assertIn("1 ended in errors", narrative["narrative"])
        self.assertTrue(any("Broken build" in s for s in narrative["suggestions"]))


class BriefingEndpointPaginationTests(unittest.TestCase):
    """Review fix: the briefing endpoint must aggregate every session in
    range — a single 50-row page silently undercounted the overview."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sessions_dir = self.root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.indexer = app.Indexer(
            sessions_dir=self.sessions_dir,
            data_dir=self.data_dir,
            source="codex",
            db_filename="index.sqlite",
            parse_file_fn=lambda _: None,
            parser_version=1,
            recall_db_path=None,
        )
        self.addCleanup(self.indexer.conn.close)

    def test_handler_aggregates_beyond_one_page(self):
        total = 210  # > DEFAULT_LIMIT (200), so aggregation must paginate
        start_base = app.parse_date_param("2026-09-06", end=False)
        with self.indexer.lock:
            for i in range(total):
                self.indexer.conn.execute(
                    """
                    INSERT INTO sessions
                    (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count,
                     mtime, search_blob, parser_version, pinned, tokens_total)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"bulk-{i}", str(self.root / f"none-{i}.jsonl"),
                     start_base + i * 60_000, start_base + i * 60_000 + 30_000,
                     f"/proj-{i % 2}", f"Bulk {i}", 1, 0.0, "", 1, 0, 100),
                )

        handler = object.__new__(app.Handler)
        backend = SimpleNamespace(indexer=self.indexer, source="codex")
        briefing, markdown, error = handler._build_briefing_for_range(backend, "2026-09-06", None)
        self.assertIsNone(error)
        self.assertEqual(briefing["overview"]["session_count"], total)
        self.assertEqual(briefing["overview"]["tokens_total"], total * 100)
        self.assertIn(f"Sessions: {total}", markdown)
        self.assertNotIn("truncated", briefing)

    def test_safety_cap_is_flagged_not_silent(self):
        # M1/A4: when the runaway cap stops pagination early, the response
        # and markdown must say so — silent undercounting is forbidden.
        total = 250
        start_base = app.parse_date_param("2026-09-06", end=False)
        with self.indexer.lock:
            for i in range(total):
                self.indexer.conn.execute(
                    """
                    INSERT INTO sessions
                    (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count,
                     mtime, search_blob, parser_version, pinned, tokens_total)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (f"cap-{i}", str(self.root / f"cap-{i}.jsonl"),
                     start_base + i * 60_000, start_base + i * 60_000 + 30_000,
                     f"/proj-{i % 2}", f"Cap {i}", 1, 0.0, "", 1, 0, 100),
                )

        handler = object.__new__(app.Handler)
        backend = SimpleNamespace(indexer=self.indexer, source="codex")
        from unittest.mock import patch
        with patch.object(app, "BRIEFING_MAX_SESSIONS", 100):
            briefing, markdown, error = handler._build_briefing_for_range(backend, "2026-09-06", None)
        self.assertIsNone(error)
        self.assertTrue(briefing.get("truncated"), "cap hit must set the truncated flag")
        self.assertEqual(briefing.get("session_limit"), 100)
        self.assertGreater(briefing["overview"]["session_count"], 100)
        self.assertLess(briefing["overview"]["session_count"], total)
        self.assertIn("safety cap", markdown)


if __name__ == "__main__":
    unittest.main()
