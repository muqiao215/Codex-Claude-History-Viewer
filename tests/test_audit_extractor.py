import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from audit import (  # noqa: E402
    AUDIT_VERSION,
    build_audit_for_file,
    deserialize_audit_summary,
    patch_db_for_audit,
    serialize_audit_fields,
)
from audit.command_classifier import classify_command  # noqa: E402
from audit.extractor import extract_session_audit  # noqa: E402
from audit.scoring import compute_value_score  # noqa: E402


def _codex_line(ts, payload_type, **kwargs):
    obj = {"timestamp": ts, "type": "response_item", "payload": {"type": payload_type, **kwargs}}
    return json.dumps(obj)


def _codex_meta(session_id, ts, cwd):
    return json.dumps({
        "timestamp": ts,
        "type": "session_meta",
        "payload": {"id": session_id, "timestamp": ts, "cwd": cwd},
    })


def _claude_line(ts, role, content):
    obj = {
        "sessionId": "test-claude-0001",
        "timestamp": ts,
        "cwd": "/home/test/project",
        "type": "message",
        "message": {"role": role, "content": content},
    }
    return json.dumps(obj)


class CodexExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "test-codex.jsonl"
        lines = [
            _codex_meta("test-codex-0001", "2026-01-01T10:00:00.000Z", "/home/test/project"),
            _codex_line("2026-01-01T10:00:05.000Z", "message", role="user",
                        content=[{"type": "input_text", "text": "Build a small CLI tool for parsing logs."}]),
            _codex_line("2026-01-01T10:00:12.000Z", "message", role="assistant",
                        content=[{"type": "output_text", "text": "I will create the parser and add tests."}]),
            _codex_line("2026-01-01T10:01:00.000Z", "function_call", name="shell",
                        call_id="call_1",
                        arguments=json.dumps({"command": ["pytest", "tests/"], "workdir": "/home/test/project"})),
            _codex_line("2026-01-01T10:01:02.000Z", "function_call_output", call_id="call_1",
                        output="Exit code: 0\n======\n3 passed"),
            _codex_line("2026-01-01T10:02:00.000Z", "function_call", name="edit",
                        call_id="call_2",
                        arguments=json.dumps({"file_path": "/home/test/project/parser.py", "old_string": "x", "new_string": "y"})),
            _codex_line("2026-01-01T10:02:01.000Z", "function_call_output", call_id="call_2",
                        output="The file has been edited."),
        ]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_extracts_session_id_and_tools(self):
        payload = extract_session_audit(self.path, "codex", session_id_hint="test-codex-0001")
        self.assertIsNotNone(payload)
        self.assertEqual(payload.session_id, "test-codex-0001")
        self.assertIn("shell", payload.tools_used)
        self.assertIn("edit", payload.tools_used)

    def test_extracts_files_touched(self):
        payload = extract_session_audit(self.path, "codex")
        self.assertIsNotNone(payload)
        local_paths = [f["path"] for f in payload.files_touched["local"]]
        self.assertIn("/home/test/project/parser.py", local_paths)

    def test_command_intents_include_test(self):
        payload = extract_session_audit(self.path, "codex")
        self.assertIsNotNone(payload)
        self.assertIn("TEST", payload.command_intents)

    def test_outcome_is_completed_for_successful_session(self):
        payload = extract_session_audit(self.path, "codex")
        self.assertIsNotNone(payload)
        self.assertIn(payload.outcome_signal, ("completed", "partially_completed"))

    def test_value_score_positive(self):
        payload = extract_session_audit(self.path, "codex")
        self.assertIsNotNone(payload)
        self.assertGreater(payload.value_score, 0)


class ClaudeExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "test-claude.jsonl"
        lines = [
            json.dumps({
                "sessionId": "test-claude-0001", "timestamp": "2026-01-01T10:00:00.000Z",
                "cwd": "/home/test/project", "type": "summary", "summary": "test session",
            }),
            _claude_line("2026-01-01T10:00:05.000Z", "user",
                         "Add error handling to the parser."),
            _claude_line("2026-01-01T10:00:12.000Z", "assistant",
                         [{"type": "text", "text": "I will update the parser."},
                          {"type": "tool_use", "id": "tu_1", "name": "bash",
                           "input": {"command": "npm run build"}}]),
            _claude_line("2026-01-01T10:00:20.000Z", "user",
                         [{"type": "tool_result", "tool_use_id": "tu_1",
                           "is_error": True, "content": "Error: Cannot find module"}]),
        ]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_extracts_tool_use(self):
        payload = extract_session_audit(self.path, "claude")
        self.assertIsNotNone(payload)
        self.assertIn("bash", payload.tools_used)

    def test_detects_error_in_tool_result(self):
        payload = extract_session_audit(self.path, "claude")
        self.assertIsNotNone(payload)
        self.assertGreaterEqual(payload.errors["count"], 1)

    def test_outcome_reflects_error_or_completion(self):
        payload = extract_session_audit(self.path, "claude")
        self.assertIsNotNone(payload)
        self.assertIn(payload.outcome_signal, ("errored", "completed", "partially_completed", "unknown"))


class ToleranceTests(unittest.TestCase):
    def test_malformed_line_does_not_abort(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "malformed.jsonl"
            lines = [
                _codex_meta("m-0001", "2026-01-01T10:00:00.000Z", "/cwd"),
                "{ this is not valid json",
                _codex_line("2026-01-01T10:00:05.000Z", "message", role="user",
                            content=[{"type": "input_text", "text": "hello"}]),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            payload = extract_session_audit(path, "codex")
            self.assertIsNotNone(payload)
            self.assertGreaterEqual(payload.parse_errors, 1)
            self.assertEqual(payload.session_id, "m-0001")
        finally:
            tmp.cleanup()

    def test_large_line_is_skipped(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "large.jsonl"
            big_line = '{"filler":"' + ("x" * (2 * 1024 * 1024)) + '"}'
            lines = [
                _codex_meta("l-0001", "2026-01-01T10:00:00.000Z", "/cwd"),
                big_line,
                _codex_line("2026-01-01T10:00:05.000Z", "message", role="user",
                            content=[{"type": "input_text", "text": "hello after big line"}]),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            payload = extract_session_audit(path, "codex")
            self.assertIsNotNone(payload)
            self.assertEqual(payload.session_id, "l-0001")
        finally:
            tmp.cleanup()


class CommandClassifierTests(unittest.TestCase):
    def test_pytest_classified_as_test(self):
        self.assertIn("TEST", classify_command("pytest tests/ -v"))

    def test_ssh_classified_as_remote(self):
        self.assertIn("REMOTE", classify_command("ssh user@host 'cat /etc/hosts'"))

    def test_git_classified_as_git(self):
        self.assertIn("GIT", classify_command("git commit -m 'fix'"))

    def test_unknown_returns_unknown(self):
        self.assertEqual(classify_command("echo hello"), ["UNKNOWN"])


class ScoringTests(unittest.TestCase):
    def test_value_score_clamped_to_range(self):
        score = compute_value_score(
            weighted_local_files=0, weighted_remote_files=0, write_ops=0, edit_ops=0,
            successful_bash_count=0, command_intents={}, error_count=0, interrupted=False,
        )
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_value_score_grows_with_local_files(self):
        base = compute_value_score(
            weighted_local_files=0, weighted_remote_files=0, write_ops=0, edit_ops=0,
            successful_bash_count=0, command_intents={}, error_count=0, interrupted=False,
        )
        with_files = compute_value_score(
            weighted_local_files=3, weighted_remote_files=0, write_ops=1, edit_ops=2,
            successful_bash_count=0, command_intents={}, error_count=0, interrupted=False,
        )
        self.assertGreater(with_files, base)


class DbIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions_dir = self.root / "sessions"
        self.sessions_dir.mkdir()
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()

        path = self.sessions_dir / "integration.jsonl"
        lines = [
            _codex_meta("int-0001", "2026-01-01T10:00:00.000Z", "/home/test/project"),
            _codex_line("2026-01-01T10:00:05.000Z", "message", role="user",
                        content=[{"type": "input_text", "text": "Build the CLI."}]),
            _codex_line("2026-01-01T10:01:00.000Z", "function_call", name="edit",
                        call_id="c1",
                        arguments=json.dumps({"file_path": "/home/test/project/main.py", "old_string": "a", "new_string": "b"})),
            _codex_line("2026-01-01T10:01:01.000Z", "function_call_output", call_id="c1",
                        output="The file has been edited."),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_indexer_persists_audit_fields(self):
        import app
        idx = app.Indexer(
            sessions_dir=self.sessions_dir,
            data_dir=self.data_dir,
            source="codex",
            parse_file_fn=app.parse_codex_session_file,
            parser_version=1,
        )
        idx.scan_sessions()
        items = idx.list_sessions_page(limit=10, sort="value")["items"]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["id"], "int-0001")
        self.assertIn("files_touched", item)
        self.assertIn("tools_used", item)
        self.assertIn("command_intents", item)
        self.assertIn("outcome_signal", item)
        self.assertIn("value_score", item)
        self.assertIsInstance(item["files_touched"], dict)
        local_files = item["files_touched"].get("local", [])
        self.assertGreater(len(local_files), 0)

    def test_patch_db_for_audit_is_idempotent(self):
        import sqlite3
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
        patch_db_for_audit(conn)
        patch_db_for_audit(conn)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        self.assertIn("value_score", cols)
        self.assertIn("outcome_signal", cols)
        self.assertIn("audit_version", cols)

    def test_audit_version_constant_matches(self):
        self.assertEqual(AUDIT_VERSION, 1)

    def test_serialize_deserialize_roundtrip(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "rt.jsonl"
            lines = [
                _codex_meta("rt-0001", "2026-01-01T10:00:00.000Z", "/cwd"),
                _codex_line("2026-01-01T10:00:05.000Z", "message", role="user",
                            content=[{"type": "input_text", "text": "hi"}]),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            payload = build_audit_for_file(path, "codex")
            self.assertIsNotNone(payload)
            fields = serialize_audit_fields(payload)
            row = {k: v for k, v in fields.items()}
            row["outcome_signal"] = fields["outcome_signal"]
            row["value_score"] = fields["value_score"]
            row["friction_score"] = fields["friction_score"]
            row["action_density"] = fields["action_density"]
            summary = deserialize_audit_summary(row)
            self.assertEqual(summary["outcome_signal"], payload.outcome_signal)
            self.assertEqual(summary["value_score"], payload.value_score)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
