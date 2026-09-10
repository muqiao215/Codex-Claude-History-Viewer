import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import app  # noqa: E402


def _codex_meta(session_id, ts, cwd):
    return json.dumps({
        "timestamp": ts,
        "type": "session_meta",
        "payload": {"id": session_id, "timestamp": ts, "cwd": cwd},
    })


def _codex_token_count(ts, input_tokens, output_tokens, cached=0, reasoning=0):
    return json.dumps({
        "timestamp": ts,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": reasoning,
                    "total_tokens": input_tokens + output_tokens + cached,
                },
            },
        },
    })


def _codex_message(ts, role, text):
    content_type = "input_text" if role == "user" else "output_text"
    return json.dumps({
        "timestamp": ts,
        "type": "response_item",
        "payload": {"type": "message", "role": role, "content": [{"type": content_type, "text": text}]},
    })


def _claude_assistant(ts, text, usage, message_id=None):
    message = {"role": "assistant", "model": "claude-test", "content": [{"type": "text", "text": text}], "usage": usage}
    if message_id:
        message["id"] = message_id
    return json.dumps({
        "timestamp": ts,
        "sessionId": "claude-usage-1",
        "cwd": "/demo/claude",
        "type": "assistant",
        "message": message,
    })


def _claude_user(ts, text):
    return json.dumps({
        "timestamp": ts,
        "sessionId": "claude-usage-1",
        "cwd": "/demo/claude",
        "type": "user",
        "message": {"role": "user", "content": text},
    })


class CodexUsageParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_token_count_events_aggregate_cumulative_totals(self):
        path = self.root / "rollout.jsonl"
        lines = [
            _codex_meta("usage-1", "2026-03-01T10:00:00.000Z", "/demo"),
            _codex_message("2026-03-01T10:00:05.000Z", "user", "Do the work."),
            _codex_message("2026-03-01T10:00:08.000Z", "assistant", "On it."),
            _codex_token_count("2026-03-01T10:00:09.000Z", 0, 0),
            _codex_token_count("2026-03-01T10:01:00.000Z", 1000, 200, cached=50, reasoning=30),
            _codex_token_count("2026-03-01T10:02:00.000Z", 1800, 420, cached=80, reasoning=60),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = app.parse_codex_session_file(path)
        self.assertIsNotNone(session)
        self.assertEqual(session["usage"], {
            "input": 1800, "output": 420, "cached": 80, "reasoning": 60, "total": 2300,
        })

    def test_token_count_events_do_not_flood_transcript(self):
        path = self.root / "rollout.jsonl"
        lines = [
            _codex_meta("usage-quiet", "2026-03-01T10:00:00.000Z", "/demo"),
            _codex_message("2026-03-01T10:00:05.000Z", "user", "Do the work."),
            _codex_message("2026-03-01T10:00:08.000Z", "assistant", "On it."),
            _codex_token_count("2026-03-01T10:00:09.000Z", 100, 10),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = app.parse_codex_session_file(path)
        kinds = [m["kind"] for m in session["messages"]]
        self.assertNotIn("raw_json:event_msg:token_count", kinds)

    def test_no_usage_events_yield_none(self):
        path = self.root / "rollout.jsonl"
        lines = [
            _codex_meta("usage-none", "2026-03-01T10:00:00.000Z", "/demo"),
            _codex_message("2026-03-01T10:00:05.000Z", "user", "Hello."),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = app.parse_codex_session_file(path)
        self.assertIsNone(session["usage"])


class ClaudeUsageParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_usage_sums_across_assistant_messages(self):
        path = self.root / "session.jsonl"
        lines = [
            _claude_user("2026-03-01T10:00:00.000Z", "Please summarise."),
            _claude_assistant("2026-03-01T10:00:05.000Z", "Sure.", {
                "input_tokens": 1000,
                "output_tokens": 100,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 128,
            }, message_id="msg_a"),
            _claude_assistant("2026-03-01T10:01:00.000Z", "Done.", {
                "input_tokens": 500,
                "output_tokens": 60,
                "cache_creation_input_tokens": 40,
                "cache_read_input_tokens": 0,
            }, message_id="msg_b"),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = app.parse_claude_session_file(path)
        self.assertEqual(session["usage"], {
            "input": 1500, "output": 160, "cached": 168, "reasoning": 0, "total": 1828,
        })

    def test_same_message_id_records_counted_once(self):
        # Review repro: Claude splits one assistant message into several
        # records (text / tool_use blocks) that all carry the same usage.
        # Naive summation would multiply the session totals.
        path = self.root / "session.jsonl"
        usage = {
            "input_tokens": 1000,
            "output_tokens": 100,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 50,
        }
        lines = [
            _claude_user("2026-03-01T10:00:00.000Z", "Go."),
            _claude_assistant("2026-03-01T10:00:05.000Z", "Part one.", usage, message_id="msg_dup"),
            _claude_assistant("2026-03-01T10:00:06.000Z", "", usage, message_id="msg_dup"),
            _claude_assistant("2026-03-01T10:00:07.000Z", "", usage, message_id="msg_dup"),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = app.parse_claude_session_file(path)
        self.assertEqual(session["usage"]["input"], 1000)
        self.assertEqual(session["usage"]["output"], 100)
        self.assertEqual(session["usage"]["cached"], 50)
        self.assertEqual(session["usage"]["total"], 1150)

    def test_same_message_id_keeps_largest_variant(self):
        path = self.root / "session.jsonl"
        lines = [
            _claude_user("2026-03-01T10:00:00.000Z", "Go."),
            _claude_assistant("2026-03-01T10:00:05.000Z", "Draft.", {
                "input_tokens": 400, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            }, message_id="msg_grow"),
            _claude_assistant("2026-03-01T10:00:09.000Z", "", {
                "input_tokens": 900, "output_tokens": 80,
                "cache_creation_input_tokens": 10, "cache_read_input_tokens": 0,
            }, message_id="msg_grow"),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = app.parse_claude_session_file(path)
        self.assertEqual(session["usage"]["input"], 900)
        self.assertEqual(session["usage"]["output"], 80)
        self.assertEqual(session["usage"]["cached"], 10)
        self.assertEqual(session["usage"]["total"], 990)

    def test_records_without_message_id_still_accumulate(self):
        path = self.root / "session.jsonl"
        lines = [
            _claude_user("2026-03-01T10:00:00.000Z", "Go."),
            _claude_assistant("2026-03-01T10:00:05.000Z", "One.", {
                "input_tokens": 100, "output_tokens": 10,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            }),
            _claude_assistant("2026-03-01T10:00:06.000Z", "Two.", {
                "input_tokens": 200, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            }),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = app.parse_claude_session_file(path)
        self.assertEqual(session["usage"]["input"], 300)
        self.assertEqual(session["usage"]["total"], 330)

    def test_missing_usage_defaults_to_zero_totals(self):
        path = self.root / "session.jsonl"
        lines = [
            _claude_user("2026-03-01T10:00:00.000Z", "Hello."),
            json.dumps({
                "timestamp": "2026-03-01T10:00:05.000Z",
                "sessionId": "claude-usage-1",
                "cwd": "/demo/claude",
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi."}]},
            }),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = app.parse_claude_session_file(path)
        self.assertEqual(session["usage"]["total"], 0)


class ParserRegistrationVersionTests(unittest.TestCase):
    """Review fix: every active source registration must carry the current
    parser version, or old caches silently keep zero usage (the WSL Codex
    regression was exactly this)."""

    def test_all_active_registrations_use_current_versions(self):
        import re
        source = (REPO_DIR / "app.py").read_text(encoding="utf-8")
        codex_versions = []
        claude_versions = []
        for line in source.splitlines():
            if "indexer_factory" in line:
                continue  # placeholder parse fn; factory-backed sources never parse JSONL
            match = re.search(r"parse_codex_session_file,\s*(\d+)", line)
            if match:
                codex_versions.append(int(match.group(1)))
            match = re.search(r"parse_claude_session_file,\s*(\d+)", line)
            if match:
                claude_versions.append(int(match.group(1)))
        self.assertGreaterEqual(len(codex_versions), 3, codex_versions)
        self.assertGreaterEqual(len(claude_versions), 3, claude_versions)
        self.assertTrue(all(v == 5 for v in codex_versions), f"codex: {codex_versions}")
        self.assertTrue(all(v == 5 for v in claude_versions), f"claude: {claude_versions}")


class UsageIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sessions_dir = self.root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _make_indexer(self, db_filename="index.sqlite"):
        indexer = app.Indexer(
            sessions_dir=self.sessions_dir,
            data_dir=self.data_dir,
            source="codex",
            db_filename=db_filename,
            parse_file_fn=app.parse_codex_session_file,
            parser_version=5,
            recall_db_path=None,
        )
        self.addCleanup(indexer.conn.close)
        return indexer

    def test_scan_persists_usage_and_query_aggregates(self):
        path = self.sessions_dir / "rollout.jsonl"
        lines = [
            _codex_meta("usage-agg", "2026-03-01T10:00:00.000Z", "/demo/proj"),
            _codex_message("2026-03-01T10:00:05.000Z", "user", "Do the work."),
            _codex_token_count("2026-03-01T10:02:00.000Z", 1800, 420, cached=80, reasoning=60),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        indexer = self._make_indexer()
        indexer.scan_sessions()

        result = indexer.query_usage()
        self.assertTrue(result["has_usage_data"])
        self.assertEqual(result["totals"]["session_count"], 1)
        self.assertEqual(result["totals"]["input"], 1800)
        self.assertEqual(result["totals"]["output"], 420)
        self.assertEqual(result["totals"]["cached"], 80)
        self.assertEqual(result["totals"]["reasoning"], 60)
        self.assertEqual(result["totals"]["total"], 2300)
        self.assertEqual(len(result["by_day"]), 1)
        self.assertEqual(result["by_day"][0]["total"], 2300)
        self.assertEqual(result["by_project"][0]["project"], "/demo/proj")
        self.assertEqual(result["top_sessions"][0]["id"], "usage-agg")

        filtered = indexer.query_usage(cwd="/demo/other")
        self.assertFalse(filtered["has_usage_data"])

    def test_usage_columns_survive_reopen(self):
        path = self.sessions_dir / "rollout.jsonl"
        lines = [
            _codex_meta("usage-reopen", "2026-03-01T10:00:00.000Z", "/demo"),
            _codex_message("2026-03-01T10:00:05.000Z", "user", "Do the work."),
            _codex_token_count("2026-03-01T10:02:00.000Z", 500, 100),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        indexer = self._make_indexer()
        indexer.scan_sessions()
        indexer.conn.close()

        indexer2 = self._make_indexer()
        result = indexer2.query_usage()
        self.assertTrue(result["has_usage_data"])
        self.assertEqual(result["totals"]["input"], 500)

    def test_sessions_without_usage_report_zero(self):
        path = self.sessions_dir / "rollout.jsonl"
        lines = [
            _codex_meta("usage-zero", "2026-03-01T10:00:00.000Z", "/demo"),
            _codex_message("2026-03-01T10:00:05.000Z", "user", "Just chatting."),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        indexer = self._make_indexer()
        indexer.scan_sessions()
        result = indexer.query_usage()
        self.assertFalse(result["has_usage_data"])
        self.assertEqual(result["totals"]["total"], 0)
        self.assertEqual(result["totals"]["session_count"], 1)

    def test_old_parser_version_cache_backfills_usage(self):
        # M1/A5: an index built by parser v4 (pre-usage: version 4, zero
        # tokens) must be re-parsed and backfilled when reopened by the
        # current parser — not skipped because mtime is unchanged.
        path = self.sessions_dir / "rollout.jsonl"
        lines = [
            _codex_meta("usage-v4", "2026-03-01T10:00:00.000Z", "/demo"),
            _codex_message("2026-03-01T10:00:05.000Z", "user", "Do the work."),
            _codex_token_count("2026-03-01T10:02:00.000Z", 700, 300),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        indexer = self._make_indexer()
        with indexer.lock:
            indexer.conn.execute(
                """
                INSERT INTO sessions
                (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count,
                 mtime, search_blob, parser_version, pinned, tokens_total)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("usage-v4", str(path), 1, 2, "/demo", "Old cache row",
                 1, path.stat().st_mtime, "", 4, 0, 0),
            )
        indexer.scan_sessions()

        with indexer.lock:
            row = indexer.conn.execute(
                "SELECT parser_version, tokens_total FROM sessions WHERE id = 'usage-v4'"
            ).fetchone()
        self.assertEqual(row["parser_version"], 5)
        self.assertEqual(row["tokens_total"], 1000)


if __name__ == "__main__":
    unittest.main()
