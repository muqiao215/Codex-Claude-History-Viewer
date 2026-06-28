import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import app  # noqa: E402
from audit import patch_db_for_audit  # noqa: E402


def _codex_meta(session_id, ts, cwd):
    return json.dumps({
        "timestamp": ts,
        "type": "session_meta",
        "payload": {"id": session_id, "timestamp": ts, "cwd": cwd},
    })


def _codex_line(ts, payload_type, **kwargs):
    obj = {"timestamp": ts, "type": "response_item", "payload": {"type": payload_type, **kwargs}}
    return json.dumps(obj)


def _write_codex_jsonl(path, session_id, cwd, file_target):
    lines = [
        _codex_meta(session_id, "2026-01-01T10:00:00.000Z", cwd),
        _codex_line("2026-01-01T10:00:05.000Z", "message", role="user",
                    content=[{"type": "input_text", "text": f"Edit {file_target} and run tests."}]),
        _codex_line("2026-01-01T10:00:12.000Z", "message", role="assistant",
                    content=[{"type": "output_text", "text": "On it."}]),
        _codex_line("2026-01-01T10:01:00.000Z", "function_call", name="shell",
                    call_id="c1",
                    arguments=json.dumps({"command": ["pytest", "tests/"], "workdir": cwd})),
        _codex_line("2026-01-01T10:01:02.000Z", "function_call_output", call_id="c1",
                    output="Exit code: 0\n======\n2 passed"),
        _codex_line("2026-01-01T10:02:00.000Z", "function_call", name="edit",
                    call_id="c2",
                    arguments=json.dumps({"file_path": file_target, "old_string": "x", "new_string": "y"})),
        _codex_line("2026-01-01T10:02:01.000Z", "function_call_output", call_id="c2",
                    output="The file has been edited."),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_session_row(indexer, session_id, file_path, search_blob=""):
    with indexer.lock:
        indexer.conn.execute(
            """
            INSERT INTO sessions
            (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count,
             mtime, search_blob, parser_version, pinned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, str(file_path), 1, 2, "/demo", "demo", 6, 0.0, search_blob, 1, 0),
        )


class BuildSessionAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
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
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.indexer.conn.close)

        self.file_alpha = self.sessions_dir / "alpha.jsonl"
        _write_codex_jsonl(self.file_alpha, "alpha", "/demo", "/demo/parser.py")
        _seed_session_row(self.indexer, "alpha", self.file_alpha)

    def test_returns_full_payload_with_required_keys(self):
        audit = self.indexer.build_session_audit("alpha")
        self.assertIsNotNone(audit)
        for key in (
            "session_id", "first_user_prompt", "last_assistant_reply",
            "files_touched", "command_intents", "outcome_signal",
            "value_score", "friction_score", "evidence",
        ):
            self.assertIn(key, audit, f"missing key: {key}")
        self.assertEqual(audit["session_id"], "alpha")
        self.assertIn("TEST", audit["command_intents"])
        self.assertGreater(audit["value_score"], 0)
        self.assertIsInstance(audit["evidence"], list)
        self.assertGreater(len(audit["evidence"]), 0)

    def test_missing_session_returns_none(self):
        self.assertIsNone(self.indexer.build_session_audit("does-not-exist"))

    def test_missing_file_on_disk_returns_none(self):
        self.file_alpha.unlink()
        self.assertIsNone(self.indexer.build_session_audit("alpha"))


class FilePathFilterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
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
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.indexer.conn.close)

        self.file_a = self.sessions_dir / "alpha.jsonl"
        self.file_b = self.sessions_dir / "beta.jsonl"
        _write_codex_jsonl(self.file_a, "alpha", "/demo", "/demo/parser.py")
        _write_codex_jsonl(self.file_b, "beta", "/demo", "/demo/other_module.py")

        for sid, fpath in (("alpha", self.file_a), ("beta", self.file_b)):
            _seed_session_row(self.indexer, sid, fpath)

        # Replicate what scan_sessions does: compute audit + persist summary
        # columns so list_sessions_page can read files_touched_json.
        from audit import build_audit_for_file, serialize_audit_fields
        with self.indexer.lock:
            for sid, fpath in (("alpha", self.file_a), ("beta", self.file_b)):
                payload = build_audit_for_file(fpath, "codex", session_id_hint=sid)
                fields = serialize_audit_fields(payload)
                assignments = ", ".join(f"{k} = ?" for k in fields.keys())
                self.indexer.conn.execute(
                    f"UPDATE sessions SET {assignments} WHERE id = ?",
                    [*fields.values(), sid],
                )

    def test_list_sessions_page_filter_narrows(self):
        page_all = self.indexer.list_sessions_page(limit=10)
        ids_all = {s["id"] for s in page_all["items"]}
        self.assertEqual(ids_all, {"alpha", "beta"})

        page_filtered = self.indexer.list_sessions_page(limit=10, file_path="/demo/parser.py")
        ids_filtered = {s["id"] for s in page_filtered["items"]}
        self.assertEqual(ids_filtered, {"alpha"})

    def test_query_sessions_filter_narrows(self):
        all_ids = {s["id"] for s in self.indexer.query_sessions(limit=10)}
        self.assertEqual(all_ids, {"alpha", "beta"})

        filtered = {s["id"] for s in self.indexer.query_sessions(limit=10, file_path="/demo/other_module.py")}
        self.assertEqual(filtered, {"beta"})

    def test_sql_like_metacharacters_do_not_cause_false_positives(self):
        # "_" is a LIKE wildcard; ensure escape prevents beta (other_module.py)
        # from matching when filtering for a literal path containing "_".
        page = self.indexer.list_sessions_page(limit=10, file_path="/demo/parser_x.py")
        self.assertEqual({s["id"] for s in page["items"]}, set())

        items_q = self.indexer.query_sessions(limit=10, file_path="/demo/%")
        self.assertEqual({s["id"] for s in items_q}, set())


class ModuleHelpersTests(unittest.TestCase):
    def test_match_files_touched_exact_match(self):
        import json as _json
        js = _json.dumps({"local": [{"path": "/a/b.py"}], "remote": [], "inferred": []})
        self.assertTrue(app._match_files_touched(js, "/a/b.py"))
        self.assertFalse(app._match_files_touched(js, "/a/b_backup.py"))

    def test_match_files_touched_handles_invalid_json(self):
        self.assertFalse(app._match_files_touched("not json", "/a/b.py"))
        self.assertFalse(app._match_files_touched(None, "/a/b.py"))
        self.assertFalse(app._match_files_touched("{}", "/a/b.py"))

    def test_escape_sql_like(self):
        self.assertEqual(app._escape_sql_like("/a/b%"), "/a/b\\%")
        self.assertEqual(app._escape_sql_like("/a/b_"), "/a/b\\_")
        self.assertEqual(app._escape_sql_like("/a/b\\c"), "/a/b\\\\c")


if __name__ == "__main__":
    unittest.main()
