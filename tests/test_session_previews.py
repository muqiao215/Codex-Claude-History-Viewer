import sys
import tempfile
import unittest
from pathlib import Path


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
        data = self.indexer.get_session("session-1")

        self.assertIsNotNone(data)
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["messages"][0]["text"], "short text")
        self.assertFalse(data["messages"][0]["is_truncated"])
        self.assertTrue(data["messages"][1]["is_truncated"])
        self.assertEqual(data["messages"][1]["message_index"], 1)
        self.assertGreater(data["messages"][1]["char_count"], app.MESSAGE_INLINE_FULL_THRESHOLD)
        self.assertLess(len(data["messages"][1]["text"]), data["messages"][1]["char_count"])

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
        self.assertGreaterEqual(result["matches"][0]["excerpt_start"], 0)
        self.assertGreater(result["matches"][0]["excerpt_end"], result["matches"][0]["excerpt_start"])

    def test_search_session_messages_returns_empty_for_missing_term(self):
        result = self.indexer.search_session_messages("session-1", "absent")

        self.assertEqual(result["message_match_count"], 0)
        self.assertEqual(result["match_count"], 0)
        self.assertEqual(result["matches"], [])


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

    def test_list_projects_page_groups_and_paginates(self):
        page = self.indexer.list_projects_page(limit=1, offset=0)

        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["project"], "project-0")
        self.assertTrue(page["has_more"])
        self.assertEqual(page["next_offset"], 1)


if __name__ == "__main__":
    unittest.main()
