import json
import tempfile
import unittest
from pathlib import Path

from audit.ai_audit import (
    AI_AUDIT_SCHEMA_VERSION,
    CHECKLIST_STATUSES,
    VALUE_SCORE_THRESHOLD,
    build_llm_messages,
    generate_heuristic_audit,
    meets_cost_guard,
    parse_llm_json_response,
    validate_audit_json,
)
from audit.schema import LLM_AUDIT_INPUT_FIELDS, to_llm_audit_input, AuditPayload
import app


def _sample_llm_input(**overrides):
    base = {
        "first_user_prompt": "Build a REST API with auth and pagination.",
        "last_user_prompt": "Now add rate limiting.",
        "important_user_prompts": ["Add JWT auth"],
        "last_assistant_reply": "Done. All endpoints are working.",
        "files_touched": {
            "local": [
                {"path": "src/api.py", "edit_count": 5, "write_count": 1, "confidence": "high"},
                {"path": "src/auth.py", "edit_count": 0, "write_count": 1, "confidence": "high"},
            ],
            "remote": [],
            "inferred": [],
        },
        "tools_used": {"shell_command": 10, "apply_patch": 3},
        "command_intents": {"TEST": 4, "BUILD": 2, "DEBUG": 1},
        "errors": {"count": 2, "samples": ["ImportError: No module named 'flask'", "AssertionError: 401 != 200"]},
        "outcome_signal": "partially_completed",
        "evidence": [
            {"id": "sess:file:src/api.py", "type": "file", "summary": "Modified src/api.py", "message_index": 3},
            {"id": "sess:tool:shell:0", "type": "tool_call", "summary": "pytest", "message_index": 5},
        ],
    }
    base.update(overrides)
    return base


class GenerateHeuristicAuditTests(unittest.TestCase):
    def test_full_shape(self):
        result = generate_heuristic_audit(_sample_llm_input())
        self.assertEqual(result["schema_version"], AI_AUDIT_SCHEMA_VERSION)
        self.assertEqual(result["source"], "heuristic")
        self.assertIsNone(result["model"])
        self.assertIn("generated_at", result)
        self.assertIsInstance(result["generated_at"], int)
        self.assertTrue(result["user_intent"])
        self.assertIsInstance(result["checklist"], list)
        self.assertTrue(len(result["checklist"]) > 0)
        self.assertIsInstance(result["deliverables"], list)
        self.assertIsInstance(result["gaps"], list)
        self.assertTrue(result["next_action"])

    def test_intent_from_first_prompt(self):
        result = generate_heuristic_audit(_sample_llm_input(first_user_prompt="Short prompt"))
        self.assertEqual(result["user_intent"], "Short prompt")

    def test_intent_fallback_to_last(self):
        result = generate_heuristic_audit(_sample_llm_input(first_user_prompt="", last_user_prompt="Fallback intent"))
        self.assertIn("Fallback", result["user_intent"])

    def test_intent_fallback_to_important(self):
        result = generate_heuristic_audit(_sample_llm_input(first_user_prompt="", last_user_prompt="", important_user_prompts=["Important one"]))
        self.assertIn("Important", result["user_intent"])

    def test_intent_empty_all(self):
        result = generate_heuristic_audit(_sample_llm_input(first_user_prompt="", last_user_prompt="", important_user_prompts=[]))
        self.assertIn("No user prompt", result["user_intent"])

    def test_intent_truncation(self):
        long = "x" * 400
        result = generate_heuristic_audit(_sample_llm_input(first_user_prompt=long))
        self.assertTrue(len(result["user_intent"]) <= 281)
        self.assertTrue(result["user_intent"].endswith("…"))

    def test_checklist_has_file_items(self):
        result = generate_heuristic_audit(_sample_llm_input())
        items = [i["item"] for i in result["checklist"]]
        self.assertTrue(any("src/api.py" in i for i in items))
        self.assertTrue(any("src/auth.py" in i for i in items))

    def test_checklist_has_command_items(self):
        result = generate_heuristic_audit(_sample_llm_input())
        items = [i["item"] for i in result["checklist"]]
        self.assertTrue(any("TEST" in i or "test" in i for i in items))

    def test_checklist_cap_12(self):
        many_files = [{"path": f"file_{i}.py", "edit_count": 1, "write_count": 0, "confidence": "high"} for i in range(20)]
        result = generate_heuristic_audit(_sample_llm_input(files_touched={"local": many_files, "remote": [], "inferred": []}))
        self.assertLessEqual(len(result["checklist"]), 12)

    def test_checklist_status_from_outcome(self):
        result = generate_heuristic_audit(_sample_llm_input(outcome_signal="completed"))
        for item in result["checklist"]:
            self.assertEqual(item["status"], "done")

    def test_checklist_evidence_ids_linked(self):
        result = generate_heuristic_audit(_sample_llm_input())
        file_items = [i for i in result["checklist"] if "src/api.py" in i["item"]]
        self.assertTrue(file_items)
        self.assertIn("sess:file:src/api.py", file_items[0]["evidence_ids"])

    def test_deliverables_from_local(self):
        result = generate_heuristic_audit(_sample_llm_input())
        self.assertIn("src/api.py", result["deliverables"])
        self.assertIn("src/auth.py", result["deliverables"])

    def test_deliverables_dedup(self):
        ft = {"local": [{"path": "dup.py", "edit_count": 1, "write_count": 0}, {"path": "dup.py", "edit_count": 2, "write_count": 0}], "remote": [], "inferred": []}
        result = generate_heuristic_audit(_sample_llm_input(files_touched=ft))
        self.assertEqual(result["deliverables"].count("dup.py"), 1)

    def test_gaps_include_errors(self):
        result = generate_heuristic_audit(_sample_llm_input(errors={"count": 3, "samples": ["Error A"]}))
        self.assertTrue(any("3 error" in g for g in result["gaps"]))

    def test_gaps_interrupted_outcome(self):
        result = generate_heuristic_audit(_sample_llm_input(outcome_signal="interrupted"))
        self.assertTrue(any("interrupted" in g.lower() for g in result["gaps"]))

    def test_next_action_errored(self):
        result = generate_heuristic_audit(_sample_llm_input(outcome_signal="errored"))
        self.assertIn("error", result["next_action"].lower())

    def test_next_action_completed_no_errors(self):
        result = generate_heuristic_audit(_sample_llm_input(outcome_signal="completed", errors={"count": 0, "samples": []}))
        self.assertIn("archiv", result["next_action"].lower())


class ValidateAuditJsonTests(unittest.TestCase):
    def test_valid_passthrough(self):
        obj = {
            "user_intent": "Do X",
            "checklist": [{"item": "Task A", "status": "done", "evidence_ids": ["e1"]}],
            "deliverables": ["file.py"],
            "gaps": ["Missing tests"],
            "next_action": "Add tests",
        }
        validated = validate_audit_json(obj)
        self.assertEqual(validated["user_intent"], "Do X")
        self.assertEqual(validated["checklist"][0]["status"], "done")

    def test_missing_field_raises(self):
        with self.assertRaises(ValueError):
            validate_audit_json({"user_intent": "X"})

    def test_empty_intent_raises(self):
        with self.assertRaises(ValueError):
            validate_audit_json({"user_intent": "", "checklist": [], "deliverables": [], "gaps": [], "next_action": "X"})

    def test_invalid_status_normalized(self):
        obj = {"user_intent": "X", "checklist": [{"item": "A", "status": "COMPLETE"}], "deliverables": [], "gaps": [], "next_action": "Y"}
        validated = validate_audit_json(obj)
        self.assertEqual(validated["checklist"][0]["status"], "skipped")

    def test_empty_checklist_gets_placeholder(self):
        obj = {"user_intent": "X", "checklist": [], "deliverables": [], "gaps": [], "next_action": "Y"}
        validated = validate_audit_json(obj)
        self.assertEqual(len(validated["checklist"]), 1)

    def test_truncation(self):
        obj = {"user_intent": "x" * 600, "checklist": [], "deliverables": [], "gaps": [], "next_action": "y" * 400}
        validated = validate_audit_json(obj)
        self.assertLessEqual(len(validated["user_intent"]), 500)
        self.assertLessEqual(len(validated["next_action"]), 300)


class ParseLlmJsonResponseTests(unittest.TestCase):
    def test_plain_json(self):
        raw = '{"user_intent": "Build API", "checklist": [], "deliverables": [], "gaps": [], "next_action": "Ship it"}'
        result = parse_llm_json_response(raw, model="gpt-4o")
        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["model"], "gpt-4o")
        self.assertEqual(result["user_intent"], "Build API")

    def test_markdown_fenced(self):
        raw = 'Here is the audit:\n```json\n{"user_intent": "X", "checklist": [], "deliverables": [], "gaps": [], "next_action": "Y"}\n```'
        result = parse_llm_json_response(raw)
        self.assertEqual(result["user_intent"], "X")

    def test_markdown_fenced_no_lang(self):
        raw = '```\n{"user_intent": "X", "checklist": [], "deliverables": [], "gaps": [], "next_action": "Y"}\n```'
        result = parse_llm_json_response(raw)
        self.assertEqual(result["source"], "llm")

    def test_prose_wrapped(self):
        raw = 'Sure! Here is my analysis:\n{"user_intent": "X", "checklist": [], "deliverables": [], "gaps": [], "next_action": "Y"}\nHope this helps!'
        result = parse_llm_json_response(raw)
        self.assertEqual(result["user_intent"], "X")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parse_llm_json_response("")

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            parse_llm_json_response("not json at all")

    def test_schema_violation_raises(self):
        raw = '{"user_intent": "X"}'
        with self.assertRaises(ValueError):
            parse_llm_json_response(raw)


class MeetsCostGuardTests(unittest.TestCase):
    def test_below_threshold(self):
        ok, reason = meets_cost_guard(10, threshold=20)
        self.assertFalse(ok)
        self.assertIn("below", reason)

    def test_at_threshold(self):
        ok, _ = meets_cost_guard(20, threshold=20)
        self.assertTrue(ok)

    def test_above_threshold(self):
        ok, _ = meets_cost_guard(80, threshold=20)
        self.assertTrue(ok)

    def test_default_threshold(self):
        ok, _ = meets_cost_guard(VALUE_SCORE_THRESHOLD)
        self.assertTrue(ok)


class BuildLlmMessagesTests(unittest.TestCase):
    def test_two_messages(self):
        messages = build_llm_messages(_sample_llm_input())
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("first_user_prompt", messages[1]["content"])


class StorageRoundTripTests(unittest.TestCase):
    def _make_indexer(self, tmpdir):
        indexer = app.Indexer(
            sessions_dir=Path(tmpdir),
            data_dir=Path(tmpdir),
            source="codex",
            db_filename="test.sqlite",
            parse_file_fn=lambda _: None,
            parser_version=1,
            recall_db_path=None,
        )
        return indexer

    def test_store_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexer = self._make_indexer(tmpdir)
            indexer.conn.execute(
                "INSERT INTO sessions (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version, pinned) VALUES (?, ?, 0, 0, '', '', 0, 0, '', 1, 0)",
                ("test-sess-1", str(Path(tmpdir) / "fake.jsonl")),
            )
            indexer.conn.commit()
            audit = {"schema_version": 1, "source": "heuristic", "user_intent": "Test"}
            indexer.store_ai_audit("test-sess-1", audit)
            result = indexer.get_stored_ai_audit("test-sess-1")
            self.assertIsNotNone(result)
            self.assertEqual(result["source"], "heuristic")
            self.assertEqual(result["user_intent"], "Test")

    def test_get_returns_none_when_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexer = self._make_indexer(tmpdir)
            indexer.conn.execute(
                "INSERT INTO sessions (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version, pinned) VALUES (?, ?, 0, 0, '', '', 0, 0, '', 1, 0)",
                ("test-sess-2", str(Path(tmpdir) / "fake.jsonl")),
            )
            indexer.conn.commit()
            self.assertIsNone(indexer.get_stored_ai_audit("test-sess-2"))

    def test_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexer = self._make_indexer(tmpdir)
            indexer.conn.execute(
                "INSERT INTO sessions (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version, pinned) VALUES (?, ?, 0, 0, '', '', 0, 0, '', 1, 0)",
                ("test-sess-3", str(Path(tmpdir) / "fake.jsonl")),
            )
            indexer.conn.commit()
            indexer.store_ai_audit("test-sess-3", {"source": "heuristic"})
            self.assertIsNotNone(indexer.get_stored_ai_audit("test-sess-3"))
            indexer.clear_ai_audit("test-sess-3")
            self.assertIsNone(indexer.get_stored_ai_audit("test-sess-3"))

    def test_get_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            indexer = self._make_indexer(tmpdir)
            indexer.conn.execute(
                "INSERT INTO sessions (id, file_path, start_ts_ms, end_ts_ms, cwd, title, message_count, mtime, search_blob, parser_version, pinned) VALUES (?, ?, 0, 0, '', '', 0, 0, '', 1, 0)",
                ("test-sess-4", str(Path(tmpdir) / "fake.jsonl")),
            )
            indexer.conn.execute("UPDATE sessions SET audit_json = ? WHERE id = ?", ("{broken json", "test-sess-4"))
            indexer.conn.commit()
            self.assertIsNone(indexer.get_stored_ai_audit("test-sess-4"))


class ToLlmAuditInputTests(unittest.TestCase):
    def test_returns_only_safe_fields(self):
        payload = AuditPayload(session_id="s1", first_user_prompt="Hello", value_score=50)
        payload_dict = payload.to_dict()
        slimmed = {k: payload_dict.get(k) for k in LLM_AUDIT_INPUT_FIELDS}
        self.assertIn("first_user_prompt", slimmed)
        self.assertIn("evidence", slimmed)
        self.assertNotIn("session_id", slimmed)
        self.assertNotIn("value_score", slimmed)

    def test_to_llm_audit_input_function(self):
        payload = AuditPayload(session_id="s1", first_user_prompt="Hi")
        result = to_llm_audit_input(payload)
        self.assertEqual(result["first_user_prompt"], "Hi")
        self.assertEqual(len(result), len(LLM_AUDIT_INPUT_FIELDS))


if __name__ == "__main__":
    unittest.main()
