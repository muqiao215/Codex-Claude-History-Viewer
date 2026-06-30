import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

import app  # noqa: E402
from app import (  # noqa: E402
    _classify_tool_category,
    _truncate_str,
    _count_diff_lines,
    _codex_summarize_tool_use,
    _codex_summarize_tool_result,
    _claude_summarize_tool_use,
    _claude_summarize_tool_result,
    _openclaw_summarize_tool_use,
    _openclaw_summarize_tool_result,
    parse_codex_session_file,
    parse_claude_session_file,
)


def _codex_line(ts, payload_type, **kwargs):
    obj = {"timestamp": ts, "type": "response_item", "payload": {"type": payload_type, **kwargs}}
    return json.dumps(obj)


def _codex_meta(session_id, ts, cwd):
    return json.dumps({
        "timestamp": ts,
        "type": "session_meta",
        "payload": {"id": session_id, "timestamp": ts, "cwd": cwd},
    })


class ClassifyToolCategoryTests(unittest.TestCase):
    def test_known_categories(self):
        self.assertEqual(_classify_tool_category("shell_command"), "shell")
        self.assertEqual(_classify_tool_category("BASH"), "shell")
        self.assertEqual(_classify_tool_category("apply_patch"), "edit")
        self.assertEqual(_classify_tool_category("str_replace_editor"), "edit")
        self.assertEqual(_classify_tool_category("read_file"), "read")
        self.assertEqual(_classify_tool_category("grep"), "search")
        self.assertEqual(_classify_tool_category("webfetch"), "deploy")
        self.assertEqual(_classify_tool_category("update_plan"), "deploy")

    def test_text_editor_prefix(self):
        self.assertEqual(_classify_tool_category("text_editor_view"), "edit")
        self.assertEqual(_classify_tool_category("text_editor_replace"), "edit")

    def test_unknown_falls_back(self):
        self.assertEqual(_classify_tool_category("custom_mcp_tool"), "other")
        self.assertEqual(_classify_tool_category(""), "other")
        self.assertEqual(_classify_tool_category(None), "other")


class TruncateStrTests(unittest.TestCase):
    def test_none_or_empty_returns_none(self):
        self.assertIsNone(_truncate_str(None, 80))
        self.assertIsNone(_truncate_str("", 80))
        self.assertIsNone(_truncate_str("   ", 80))

    def test_collapses_whitespace(self):
        self.assertEqual(_truncate_str("a\n  b\tc", 80), "a b c")

    def test_truncates_with_ellipsis(self):
        long = "x" * 100
        out = _truncate_str(long, 10)
        self.assertEqual(len(out), 10)
        self.assertTrue(out.endswith("…"))

    def test_short_passes_through(self):
        self.assertEqual(_truncate_str("hello", 80), "hello")


class CountDiffLinesTests(unittest.TestCase):
    def test_counts_plus_minus_in_hunks(self):
        patch = """*** Update File: foo.py
@@ -1,3 +1,4 @@
 context
-old line
+new line
+another
"""
        added, removed = _count_diff_lines(patch)
        self.assertEqual(added, 2)
        self.assertEqual(removed, 1)

    def test_ignores_file_markers(self):
        patch = """*** Add File: new.py
+++ new.py
@@ -0,0 +1,2 @@
+import os
+import sys
"""
        added, removed = _count_diff_lines(patch)
        self.assertEqual(added, 2)
        self.assertEqual(removed, 0)

    def test_empty_or_no_hunks(self):
        self.assertEqual(_count_diff_lines(""), (0, 0))
        self.assertEqual(_count_diff_lines("no hunks here"), (0, 0))


class CodexSummarizeToolUseTests(unittest.TestCase):
    def test_shell_command(self):
        raw = json.dumps({"command": "rg -n foo\n--type py", "workdir": "/repo"})
        s = _codex_summarize_tool_use("shell_command", raw)
        self.assertEqual(s["category"], "shell")
        self.assertEqual(s["headline"], "rg -n foo --type py")
        self.assertEqual(s["file_path"], "/repo")

    def test_apply_patch_modify(self):
        raw = "*** Update File: src/app.py\n@@ -1,2 +1,3 @@\n ctx\n-old\n+new\n+extra\n"
        s = _codex_summarize_tool_use("apply_patch", raw)
        self.assertEqual(s["category"], "edit")
        self.assertEqual(s["change_kind"], "modify")
        self.assertEqual(s["file_path"], "src/app.py")
        self.assertEqual(s["headline"], "modify src/app.py")
        self.assertEqual(s["lines_added"], 2)
        self.assertEqual(s["lines_removed"], 1)

    def test_apply_patch_create(self):
        raw = "*** Add File: new.txt\n@@ -0,0 +1,1 @@\n+hello\n"
        s = _codex_summarize_tool_use("apply_patch", raw)
        self.assertEqual(s["change_kind"], "create")
        self.assertEqual(s["file_path"], "new.txt")
        self.assertEqual(s["lines_added"], 1)

    def test_search_tool(self):
        raw = json.dumps({"pattern": "TODO", "path": "/src"})
        s = _codex_summarize_tool_use("grep", raw)
        self.assertEqual(s["category"], "search")
        self.assertEqual(s["headline"], "TODO in /src")

    def test_read_tool(self):
        raw = json.dumps({"path": "/repo/file.py"})
        s = _codex_summarize_tool_use("read_file", raw)
        self.assertEqual(s["category"], "read")
        self.assertEqual(s["file_path"], "/repo/file.py")
        self.assertEqual(s["headline"], "/repo/file.py")

    def test_deploy_webfetch(self):
        raw = json.dumps({"url": "https://example.com/api"})
        s = _codex_summarize_tool_use("webfetch", raw)
        self.assertEqual(s["category"], "deploy")
        self.assertEqual(s["headline"], "https://example.com/api")

    def test_update_plan(self):
        raw = json.dumps({"todos": [{"id": 1}, {"id": 2}, {"id": 3}]})
        s = _codex_summarize_tool_use("update_plan", raw)
        self.assertEqual(s["category"], "deploy")
        self.assertEqual(s["headline"], "plan: 3 items")

    def test_unknown_tool_uses_first_input_key(self):
        raw = json.dumps({"frobnicate": "value"})
        s = _codex_summarize_tool_use("custom_tool", raw)
        self.assertEqual(s["category"], "other")
        self.assertEqual(s["headline"], "frobnicate: value")

    def test_invalid_json_falls_back_gracefully(self):
        s = _codex_summarize_tool_use("shell_command", "not json at all")
        self.assertEqual(s["category"], "shell")
        self.assertIsNone(s["headline"])

    def test_none_input(self):
        s = _codex_summarize_tool_use("bash", None)
        self.assertEqual(s["category"], "shell")
        self.assertIsNone(s["headline"])
        self.assertFalse(s["is_error"])


class CodexSummarizeToolResultTests(unittest.TestCase):
    def test_text_with_exit_code_zero(self):
        raw = "Exit code: 0\nWall time: 0.5 seconds\nOutput:\nhello world\nline 2"
        s = _codex_summarize_tool_result("shell_command", raw)
        self.assertEqual(s["exit_code"], 0)
        self.assertEqual(s["exit_status"], "ok")
        self.assertFalse(s["is_error"])
        self.assertIn("hello world", s["output_preview"])

    def test_text_with_nonzero_exit(self):
        raw = "Exit code: 1\nOutput:\nerror: file not found"
        s = _codex_summarize_tool_result("shell_command", raw)
        self.assertEqual(s["exit_code"], 1)
        self.assertEqual(s["exit_status"], "error")
        self.assertTrue(s["is_error"])

    def test_json_metadata(self):
        raw = json.dumps({"output": "done", "metadata": {"exit_code": 0, "duration_seconds": 0.1}})
        s = _codex_summarize_tool_result("shell_command", raw)
        self.assertEqual(s["exit_code"], 0)
        self.assertEqual(s["exit_status"], "ok")
        self.assertEqual(s["output_preview"], "done")

    def test_empty_output(self):
        s = _codex_summarize_tool_result("shell_command", "")
        self.assertIsNone(s["exit_code"])
        self.assertIsNone(s["exit_status"])
        self.assertFalse(s["is_error"])
        self.assertIsNone(s["output_preview"])

    def test_output_preview_truncated(self):
        body = "\n".join(f"line {i}" for i in range(50))
        raw = f"Exit code: 0\nOutput:\n{body}"
        s = _codex_summarize_tool_result("shell_command", raw)
        self.assertLessEqual(len(s["output_preview"]), 200)
        self.assertTrue(s["output_preview"].endswith("…"))


class ClaudeSummarizeToolUseTests(unittest.TestCase):
    def test_bash_command(self):
        item = {"name": "bash", "input": {"command": "npm test"}}
        s = _claude_summarize_tool_use(item)
        self.assertEqual(s["category"], "shell")
        self.assertEqual(s["headline"], "npm test")

    def test_str_replace_editor_create(self):
        item = {"name": "str_replace_editor", "input": {
            "command": "create",
            "file_path": "/repo/new.py",
            "file_text": "import os\nimport sys",
        }}
        s = _claude_summarize_tool_use(item)
        self.assertEqual(s["category"], "edit")
        self.assertEqual(s["change_kind"], "create")
        self.assertEqual(s["file_path"], "/repo/new.py")
        self.assertEqual(s["headline"], "create /repo/new.py")
        self.assertEqual(s["lines_added"], 2)

    def test_str_replace_editor_replace(self):
        item = {"name": "str_replace_editor", "input": {
            "command": "str_replace",
            "file_path": "/repo/app.py",
            "old_str": "old\nline",
            "new_str": "new\nline\nextra",
        }}
        s = _claude_summarize_tool_use(item)
        self.assertEqual(s["change_kind"], "modify")
        self.assertEqual(s["lines_added"], 3)
        self.assertEqual(s["lines_removed"], 2)

    def test_grep(self):
        item = {"name": "grep", "input": {"pattern": "TODO", "path": "/src"}}
        s = _claude_summarize_tool_use(item)
        self.assertEqual(s["category"], "search")
        self.assertEqual(s["headline"], "TODO in /src")

    def test_todo_write(self):
        item = {"name": "todo_write", "input": {"todos": [{"content": "a"}, {"content": "b"}]}}
        s = _claude_summarize_tool_use(item)
        self.assertEqual(s["category"], "deploy")
        self.assertEqual(s["headline"], "plan: 2 items")

    def test_no_input_returns_empty(self):
        s = _claude_summarize_tool_use({"name": "bash"})
        self.assertEqual(s["category"], "shell")
        self.assertIsNone(s["headline"])


class ClaudeSummarizeToolResultTests(unittest.TestCase):
    def test_is_error_true(self):
        item = {"is_error": True, "content": "boom"}
        s = _claude_summarize_tool_result(item)
        self.assertEqual(s["exit_status"], "error")
        self.assertTrue(s["is_error"])
        self.assertEqual(s["output_preview"], "boom")

    def test_is_error_false(self):
        item = {"is_error": False, "content": "ok output"}
        s = _claude_summarize_tool_result(item)
        self.assertEqual(s["exit_status"], "ok")
        self.assertFalse(s["is_error"])

    def test_stdout_stderr_combined(self):
        s = _claude_summarize_tool_result(
            {"is_error": False},
            tool_use_result={"stdout": "out", "stderr": "err"},
        )
        self.assertEqual(s["exit_status"], "ok")
        self.assertIn("out", s["output_preview"])
        self.assertIn("err", s["output_preview"])

    def test_no_status_when_is_error_missing(self):
        s = _claude_summarize_tool_result({"content": "neutral"})
        self.assertIsNone(s["exit_status"])
        self.assertFalse(s["is_error"])


class OpenclawSummarizeTests(unittest.TestCase):
    def test_tool_use_delegates_to_codex(self):
        item = {"name": "shell_command", "arguments": json.dumps({"command": "ls"})}
        s = _openclaw_summarize_tool_use(item)
        self.assertEqual(s["category"], "shell")
        self.assertEqual(s["headline"], "ls")

    def test_tool_result_with_is_error(self):
        msg = {"toolName": "bash", "isError": True, "content": "failure"}
        s = _openclaw_summarize_tool_result(msg)
        self.assertEqual(s["name"], "bash")
        self.assertEqual(s["category"], "shell")
        self.assertEqual(s["exit_status"], "error")
        self.assertTrue(s["is_error"])
        self.assertEqual(s["output_preview"], "failure")

    def test_tool_result_details_exit_code(self):
        msg = {"toolName": "shell_command", "details": {"exitCode": 0, "status": "completed"}}
        s = _openclaw_summarize_tool_result(msg)
        self.assertEqual(s["exit_code"], 0)
        self.assertEqual(s["exit_status"], "ok")

    def test_non_dict_returns_empty(self):
        s_use = _openclaw_summarize_tool_use(None)
        s_res = _openclaw_summarize_tool_result(None)
        self.assertFalse(s_use["is_error"])
        self.assertFalse(s_res["is_error"])


class ParserIntegrationTests(unittest.TestCase):
    def test_codex_parser_attaches_tool_summary(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sess.jsonl"
            lines = [
                _codex_meta("integ-0001", "2025-01-01T00:00:00Z", "/repo"),
                _codex_line("2025-01-01T00:00:01Z", "function_call",
                            name="shell_command", call_id="c1",
                            arguments=json.dumps({"command": "ls -la"})),
                _codex_line("2025-01-01T00:00:02Z", "function_call_output", call_id="c1",
                            output="Exit code: 0\nOutput:\ntotal 0"),
            ]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = parse_codex_session_file(p)
            self.assertIsNotNone(result)
            tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
            self.assertEqual(len(tool_msgs), 2)
            use_msg, result_msg = tool_msgs
            self.assertEqual(use_msg["kind"], "tool_use")
            self.assertIn("tool_summary", use_msg)
            self.assertEqual(use_msg["tool_summary"]["category"], "shell")
            self.assertEqual(use_msg["tool_summary"]["headline"], "ls -la")
            self.assertEqual(result_msg["kind"], "tool_result")
            self.assertEqual(result_msg["tool_summary"]["exit_status"], "ok")
            self.assertEqual(result_msg["tool_summary"]["exit_code"], 0)

    def test_claude_parser_attaches_tool_summary(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sess.jsonl"
            assistant = {
                "sessionId": "cl-integ-0001",
                "timestamp": "2025-01-01T00:00:00Z",
                "cwd": "/repo",
                "type": "assistant",
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "tu1", "name": "bash",
                     "input": {"command": "echo hi"}},
                ]},
            }
            user = {
                "sessionId": "cl-integ-0001",
                "timestamp": "2025-01-01T00:00:01Z",
                "cwd": "/repo",
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "tu1", "is_error": False, "content": "hi"},
                ]},
            }
            p.write_text(json.dumps(assistant) + "\n" + json.dumps(user) + "\n", encoding="utf-8")
            result = parse_claude_session_file(p)
            self.assertIsNotNone(result)
            tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
            self.assertEqual(len(tool_msgs), 2)
            use_msg, result_msg = tool_msgs
            self.assertEqual(use_msg["tool_summary"]["headline"], "echo hi")
            self.assertEqual(result_msg["tool_summary"]["exit_status"], "ok")

    def test_non_tool_messages_have_no_tool_summary(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sess.jsonl"
            lines = [
                _codex_meta("nt-0001", "2025-01-01T00:00:00Z", "/repo"),
                _codex_line("2025-01-01T00:00:01Z", "message", role="user",
                            content=[{"type": "input_text", "text": "hello"}]),
            ]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = parse_codex_session_file(p)
            for m in result["messages"]:
                self.assertNotIn("tool_summary", m)


if __name__ == "__main__":
    unittest.main()
