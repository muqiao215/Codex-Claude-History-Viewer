import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import app  # noqa: E402
from audit.handoff import build_handoff_bundle  # noqa: E402


class OpenCodeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "opencode.db"
        self._seed_db()
        self.indexer = app.OpenCodeIndexer(self.db_path)
        self.addCleanup(self.indexer.conn.close)
        self.addCleanup(self.temp_dir.cleanup)

    def _seed_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE session (
                id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, slug TEXT,
                directory TEXT, title TEXT, version TEXT, share_url TEXT,
                summary_additions INTEGER, summary_deletions INTEGER,
                summary_files INTEGER, summary_diffs TEXT,
                time_created INTEGER, time_updated INTEGER, agent TEXT,
                model TEXT, cost REAL, tokens_input INTEGER,
                tokens_output INTEGER, tokens_reasoning INTEGER,
                tokens_cache_read INTEGER, tokens_cache_write INTEGER
            );
            CREATE TABLE message (
                id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
                data TEXT
            );
            CREATE TABLE part (
                id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                time_created INTEGER, data TEXT
            );
            CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT, name TEXT);
            """
        )
        conn.execute(
            "INSERT INTO session (id, project_id, directory, title, time_created, time_updated, agent, model) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ses-1", "project-1", "/workspace/demo", "Implement feature", 1000, 5000, "build", json.dumps({"id": "gpt-test"})),
        )
        messages = [
            ("msg-1", "user", 1000),
            ("msg-2", "assistant", 2000),
            ("msg-3", "assistant", 4000),
        ]
        conn.executemany(
            "INSERT INTO message (id, session_id, time_created, data) VALUES (?, 'ses-1', ?, ?)",
            [(message_id, ts, json.dumps({"role": role})) for message_id, role, ts in messages],
        )
        parts = [
            ("part-1", "msg-1", 1000, {"type": "text", "text": "Implement and test the feature."}),
            ("part-2", "msg-2", 2000, {"type": "tool", "tool": "write", "state": {"status": "completed", "input": {"file_path": "src/feature.py", "content": "ok"}, "output": "written"}}),
            ("part-3", "msg-2", 3000, {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": "python3 -m unittest"}, "output": "1 test passed", "metadata": {"exit": 0}}}),
            ("part-4", "msg-3", 4000, {"type": "text", "text": "Implemented and verified."}),
        ]
        conn.executemany(
            "INSERT INTO part (id, message_id, session_id, time_created, data) VALUES (?, ?, 'ses-1', ?, ?)",
            [(part_id, message_id, ts, json.dumps(data)) for part_id, message_id, ts, data in parts],
        )
        conn.commit()
        conn.close()

    def test_build_session_audit_from_read_only_database(self):
        audit = self.indexer.build_session_audit("ses-1")

        self.assertEqual(audit["source"], "opencode")
        self.assertEqual(audit["model"], "gpt-test")
        self.assertEqual(audit["first_user_prompt"], "Implement and test the feature.")
        self.assertTrue(audit["has_assistant_after_last_user"])
        self.assertEqual(audit["files_touched"]["local"][0]["path"], "src/feature.py")
        self.assertEqual(audit["commands"][0]["command"], "python3 -m unittest")
        self.assertEqual(audit["commands"][0]["status"], "pass")

    def test_handoff_is_available_for_opencode(self):
        audit = self.indexer.build_session_audit("ses-1")
        metadata = self.indexer.get_session_metadata("ses-1")
        bundle = build_handoff_bundle(audit, metadata=metadata)

        self.assertIn("session: opencode:ses-1", bundle["standard"])
        self.assertIn("src/feature.py", bundle["standard"])
        self.assertIn("python3 -m unittest -> pass, exit 0", bundle["standard"])


if __name__ == "__main__":
    unittest.main()
