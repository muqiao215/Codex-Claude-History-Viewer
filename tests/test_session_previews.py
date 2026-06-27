import sys
import tempfile
import unittest
from pathlib import Path
import os
import sqlite3


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import app  # noqa: E402


class RuntimeDetectionTests(unittest.TestCase):
    def test_detect_runtime_system_windows(self):
        self.assertEqual(app.detect_runtime_system("nt"), "windows")

    def test_detect_runtime_system_linux(self):
        self.assertEqual(app.detect_runtime_system("posix"), "linux")


class SessionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.sessions_dir = root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = root / "data"
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
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.indexer.conn.close)
        self._seed_session()

    def tearDown(self):
        pass

    def _seed_session(self):
        long_text = (
            "A" * (app.MESSAGE_PREVIEW_CHARS + 200)
            + " NeedLe marker "
            + "A" * 200
            + " needle marker "
            + "A" * (app.MESSAGE_INLINE_FULL_THRESHOLD - app.MESSAGE_PREVIEW_CHARS)
        )
        with self.indexer.lock:
            self.indexer.conn.execute(
                """
                INSERT INTO sessions
                (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "session-1",
                    str(self.sessions_dir / "session-1.jsonl"),
                    1,
                    2,
                    str(self.sessions_dir),
                    "Preview test",
                    2,
                    0.0,
                    "",
                    1,
                    0,
                ),
            )
            self.indexer.conn.executemany(
                """
                INSERT INTO messages (session_id, ts_ms, role, kind, text)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("session-1", 1, "user", "message", "short text"),
                    ("session-1", 2, "assistant", "message", long_text),
                ],
            )
            self.indexer.conn.commit()

    def test_get_session_returns_preview_for_long_messages(self):
        data = self.indexer.get_session("session-1", include_messages=True)

        self.assertIsNotNone(data)
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["messages"][0]["text"], "short text")
        self.assertFalse(data["messages"][0]["is_truncated"])
        self.assertTrue(data["messages"][1]["is_truncated"])
        self.assertEqual(data["messages"][1]["message_index"], 1)
        self.assertGreater(data["messages"][1]["char_count"], app.MESSAGE_INLINE_FULL_THRESHOLD)
        self.assertLess(len(data["messages"][1]["text"]), data["messages"][1]["char_count"])

    def test_get_session_metadata_omits_messages_and_counts_actual_rows(self):
        data = self.indexer.get_session("session-1", include_messages=False)

        self.assertIsNotNone(data)
        self.assertNotIn("messages", data)
        self.assertEqual(data["session"]["message_total"], 2)

    def test_get_session_messages_page_returns_absolute_indexes(self):
        page = self.indexer.get_session_messages_page("session-1", offset=1, limit=1)

        self.assertIsNotNone(page)
        self.assertEqual(page["offset"], 1)
        self.assertEqual(page["limit"], 1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["messages"]), 1)
        self.assertEqual(page["messages"][0]["message_index"], 1)
        self.assertTrue(page["messages"][0]["is_truncated"])

    def test_get_session_message_returns_full_text_for_specific_index(self):
        message = self.indexer.get_session_message("session-1", 1)

        self.assertIsNotNone(message)
        self.assertEqual(message["message_index"], 1)
        self.assertFalse(message["is_truncated"])
        self.assertEqual(len(message["text"]), message["char_count"])

    def test_search_session_messages_finds_long_message_case_insensitively(self):
        result = self.indexer.search_session_messages("session-1", "needle")

        self.assertEqual(result["query"], "needle")
        self.assertEqual(result["message_match_count"], 1)
        self.assertEqual(result["match_count"], 2)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["message_index"], 1)
        self.assertTrue(result["matches"][0]["is_truncated"])
        self.assertGreater(result["matches"][0]["char_count"], app.MESSAGE_INLINE_FULL_THRESHOLD)
        self.assertIn("excerpt_text", result["matches"][0])
        self.assertIn("needle", result["matches"][0]["excerpt_text"].lower())
        self.assertLess(len(result["matches"][0]["excerpt_text"]), result["matches"][0]["char_count"])

    def test_search_session_messages_limit_keeps_total_counts(self):
        with self.indexer.lock:
            self.indexer.conn.execute(
                """
                INSERT INTO messages (session_id, ts_ms, role, kind, text)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("session-1", 3, "assistant", "message", "another needle message"),
            )
            self.indexer.conn.commit()

        result = self.indexer.search_session_messages("session-1", "needle", limit=1)

        self.assertEqual(result["query"], "needle")
        self.assertEqual(result["message_match_count"], 2)
        self.assertEqual(result["match_count"], 3)
        self.assertEqual(len(result["matches"]), 1)
        self.assertGreaterEqual(result["matches"][0]["excerpt_start"], 0)
        self.assertGreater(result["matches"][0]["excerpt_end"], result["matches"][0]["excerpt_start"])

    def test_search_session_messages_returns_empty_for_missing_term(self):
        result = self.indexer.search_session_messages("session-1", "absent")

        self.assertEqual(result["message_match_count"], 0)
        self.assertEqual(result["match_count"], 0)
        self.assertEqual(result["matches"], [])

    def test_codex_parser_keeps_unknown_payload_as_raw_json(self):
        path = self.sessions_dir / "unknown.jsonl"
        path.write_text(
            "\n".join([
                '{"timestamp":"2026-01-01T00:00:00Z","type":"session_meta","payload":{"id":"raw-1","cwd":"/tmp/demo"}}',
                '{"timestamp":"2026-01-01T00:00:01Z","type":"response_item","payload":{"type":"future_payload","value":{"x":1}}}',
            ]),
            encoding="utf-8",
        )

        parsed = app.parse_codex_session_file(path)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], "raw-1")
        self.assertEqual(len(parsed["messages"]), 1)
        self.assertEqual(parsed["messages"][0]["role"], "other")
        self.assertEqual(parsed["messages"][0]["kind"], "raw_json:response_item:future_payload")
        self.assertIn('"future_payload"', parsed["messages"][0]["text"])

    def test_large_session_message_paging_and_search_outside_loaded_window(self):
        with self.indexer.lock:
            self.indexer.conn.execute(
                """
                INSERT INTO sessions
                (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "large-session",
                    str(self.sessions_dir / "large-session.jsonl"),
                    1,
                    5000,
                    str(self.sessions_dir),
                    "Large session",
                    5000,
                    0.0,
                    "",
                    1,
                    0,
                ),
            )
            rows = [
                (
                    "large-session",
                    idx,
                    "assistant",
                    "tool_result" if idx == 123 else "message",
                    ("x" * 500_000) if idx == 123 else (f"message {idx} needle-outside-window" if idx == 42 else f"message {idx}"),
                )
                for idx in range(5000)
            ]
            self.indexer.conn.executemany(
                "INSERT INTO messages (session_id, ts_ms, role, kind, text) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self.indexer.conn.commit()

        page = self.indexer.get_session_messages_page("large-session", offset=4800, limit=200)
        self.assertEqual(page["total"], 5000)
        self.assertEqual(len(page["messages"]), 200)
        self.assertEqual(page["messages"][0]["message_index"], 4800)
        self.assertEqual(page["messages"][-1]["message_index"], 4999)

        huge = self.indexer.get_session_messages_page("large-session", offset=123, limit=1)["messages"][0]
        self.assertTrue(huge["is_truncated"])
        self.assertEqual(huge["char_count"], 500_000)
        self.assertLess(len(huge["text"]), huge["char_count"])

        result = self.indexer.search_session_messages("large-session", "needle-outside-window", limit=10)
        self.assertEqual(result["message_match_count"], 1)
        self.assertEqual(result["matches"][0]["message_index"], 42)


class ListPaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.sessions_dir = root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = root / "data"
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
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.indexer.conn.close)
        self._seed_sessions()

    def _seed_sessions(self):
        rows = []
        for idx in range(5):
            rows.append(
                (
                    f"session-{idx}",
                    str(self.sessions_dir / f"session-{idx}.jsonl"),
                    idx + 1,
                    idx + 10,
                    f"project-{idx % 2}",
                    f"Session {idx}",
                    1,
                    float(idx),
                    "",
                    1,
                    0,
                )
            )
        with self.indexer.lock:
            self.indexer.conn.executemany(
                """
                INSERT INTO sessions
                (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self.indexer.conn.commit()

    def test_list_sessions_page_returns_has_more_and_next_offset(self):
        page = self.indexer.list_sessions_page(limit=2, offset=0, sort="start")

        self.assertEqual([item["id"] for item in page["items"]], ["session-4", "session-3"])
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_offset"], 2)
        self.assertEqual(page["limit"], 2)
        self.assertEqual(page["offset"], 0)

    def test_list_sessions_page_uses_offset_for_followup_page(self):
        page = self.indexer.list_sessions_page(limit=2, offset=2, sort="start")

        self.assertEqual([item["id"] for item in page["items"]], ["session-2", "session-1"])
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_offset"], 4)

    def test_first_page_includes_all_pinned_without_counting_toward_page_limit(self):
        with self.indexer.lock:
            self.indexer.conn.execute("UPDATE sessions SET pinned = 1 WHERE id IN (?, ?, ?)", (
                "session-0",
                "session-2",
                "session-4",
            ))
            self.indexer.conn.commit()

        first = self.indexer.list_sessions_page(limit=1, offset=0, sort="start")
        second = self.indexer.list_sessions_page(limit=1, offset=1, sort="start")

        self.assertEqual([item["id"] for item in first["items"]], [
            "session-4",
            "session-2",
            "session-0",
            "session-3",
        ])
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_offset"], 1)
        self.assertEqual([item["id"] for item in second["items"]], ["session-1"])
        self.assertFalse(second["has_more"])

    def test_list_projects_page_groups_and_paginates(self):
        page = self.indexer.list_projects_page(limit=1, offset=0)

        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["project"], "project-0")
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_offset"], 1)


class PinSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.sessions_dir = root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.sessions_dir / "session-pin.jsonl"
        self.session_file.write_text("{}\n", encoding="utf-8")
        self.indexer = app.Indexer(
            sessions_dir=self.sessions_dir,
            data_dir=self.data_dir,
            source="codex",
            db_filename="index.sqlite",
            parse_file_fn=self._parse_session,
            parser_version=1,
            recall_db_path=None,
        )
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.indexer.conn.close)

    def _parse_session(self, path):
        return {
            "id": "session-pin",
            "file_path": str(path),
            "start_ts_ms": 1,
            "end_ts_ms": 2,
            "cwd": str(self.sessions_dir),
            "title": "Pinned session",
            "message_count": 1,
            "search_blob": "Pinned session",
            "messages": [
                {
                    "ts_ms": 1,
                    "role": "user",
                    "kind": "message",
                    "text": "hello",
                }
            ],
        }

    def test_pin_survives_reindex_after_file_change(self):
        self.indexer.scan_sessions()
        self.assertTrue(self.indexer.pin_session("session-pin", True))

        next_mtime = self.session_file.stat().st_mtime + 10
        os.utime(self.session_file, (next_mtime, next_mtime))
        self.indexer.scan_sessions()

        session = self.indexer.get_session("session-pin")["session"]
        self.assertEqual(session["pinned"], 1)


class HermesStateIndexerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.db_path = root / "state.db"
        self._seed_db()
        self.indexer = app.HermesStateIndexer(self.db_path)
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.indexer.conn.close)

    def _seed_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                source TEXT,
                user_id TEXT,
                model TEXT,
                model_config TEXT,
                system_prompt TEXT,
                parent_session_id TEXT,
                started_at REAL,
                ended_at REAL,
                end_reason TEXT,
                message_count INTEGER,
                tool_call_count INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_read_tokens INTEGER,
                cache_write_tokens INTEGER,
                reasoning_tokens INTEGER,
                billing_provider TEXT,
                billing_base_url TEXT,
                billing_mode TEXT,
                estimated_cost_usd REAL,
                actual_cost_usd REAL,
                cost_status TEXT,
                cost_source TEXT,
                pricing_version TEXT,
                title TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                tool_call_id TEXT,
                tool_calls TEXT,
                tool_name TEXT,
                timestamp REAL,
                token_count INTEGER,
                finish_reason TEXT,
                reasoning TEXT,
                reasoning_details TEXT,
                codex_reasoning_items TEXT
            )
            """
        )
        conn.execute("CREATE VIRTUAL TABLE messages_fts USING fts5(content)")
        conn.execute(
            """
            INSERT INTO sessions (
                id, source, user_id, model, started_at, ended_at, message_count, title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("sess-1", "telegram", None, "glm-5.1", 10.0, 20.0, 4, None),
        )
        conn.executemany(
            """
            INSERT INTO messages (
                session_id, role, content, tool_calls, tool_name, timestamp, reasoning
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("sess-1", "user", "Needle request", None, None, 10.0, None),
                (
                    "sess-1",
                    "assistant",
                    "",
                    '[{"function":{"name":"terminal","arguments":"{\\"command\\":\\"echo hi\\"}"}}]',
                    None,
                    11.0,
                    "Run a terminal command",
                ),
                ("sess-1", "tool", '{"output":"needle output"}', None, None, 12.0, None),
                ("sess-1", "assistant", "", None, None, 13.0, "Reasoning only"),
            ],
        )
        conn.executemany(
            "INSERT INTO messages_fts (content) VALUES (?)",
            [("Needle request",), ('{"output":"needle output"}',)],
        )
        conn.commit()
        conn.close()

    def test_list_sessions_page_maps_hermes_sessions(self):
        page = self.indexer.list_sessions_page(limit=10, offset=0, sort="start")

        self.assertEqual(len(page["items"]), 1)
        session = page["items"][0]
        self.assertEqual(session["id"], "sess-1")
        self.assertEqual(session["cwd"], "telegram")
        self.assertEqual(session["start_ts_ms"], 10000)
        self.assertEqual(session["end_ts_ms"], 20000)
        self.assertEqual(session["pinned"], 0)
        self.assertIn("glm-5.1", session["title"])

    def test_get_session_maps_tool_rows_and_reasoning_rows(self):
        data = self.indexer.get_session("sess-1", include_messages=True)

        self.assertIsNotNone(data)
        self.assertEqual(len(data["messages"]), 4)
        self.assertEqual(data["messages"][1]["kind"], "tool_use")
        self.assertIn("Tool use: terminal", data["messages"][1]["text"])
        self.assertIn("Description: Run a terminal command", data["messages"][1]["text"])
        self.assertEqual(data["messages"][2]["role"], "tool")
        self.assertEqual(data["messages"][2]["kind"], "tool_result")
        self.assertEqual(data["messages"][3]["kind"], "reasoning_summary")
        self.assertEqual(data["messages"][3]["text"], "Reasoning only")

    def test_hermes_session_messages_page_returns_absolute_indexes(self):
        page = self.indexer.get_session_messages_page("sess-1", offset=1, limit=2)

        self.assertIsNotNone(page)
        self.assertEqual(page["offset"], 1)
        self.assertEqual(page["total"], 4)
        self.assertEqual([item["message_index"] for item in page["messages"]], [1, 2])
        self.assertEqual(page["messages"][0]["kind"], "tool_use")

    def test_search_session_messages_matches_hermes_content(self):
        data = self.indexer.search_session_messages("sess-1", "needle")

        self.assertIsNotNone(data)
        self.assertEqual(data["query"], "needle")
        self.assertEqual(data["message_match_count"], 2)
        self.assertEqual(data["match_count"], 2)
        self.assertEqual([item["message_index"] for item in data["matches"]], [0, 2])


if __name__ == "__main__":
    unittest.main()
