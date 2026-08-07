import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from audit.extractor import extract_session_audit  # noqa: E402
from audit.handoff import build_handoff_bundle, build_handoff_payload  # noqa: E402


def _line(ts, payload_type, **kwargs):
    return json.dumps({
        "timestamp": ts,
        "type": "response_item",
        "payload": {"type": payload_type, **kwargs},
    })


class CurrentCodexExecTests(unittest.TestCase):
    def _extract(self, output_text):
        script = r'''const patch = "*** Begin Patch\n*** Update File: src/app.py\n@@\n-old\n+new\n*** Add File: tests/test_app.py\n+ok\n*** End Patch";
const r = await Promise.all([
  tools.exec_command({cmd:"python3 -m unittest",workdir:"/workspace","yield_time_ms":10000}),
  tools.exec_command({cmd:"node --check static/app.js",workdir:"/workspace","yield_time_ms":10000}),
  tools.apply_patch(patch)
]);
for (const x of r) text(x.output);'''
        rows = [
            json.dumps({"timestamp": "2026-07-22T00:00:00Z", "type": "session_meta", "payload": {"id": "session-1", "cwd": "/workspace"}}),
            _line("2026-07-22T00:00:01Z", "message", role="user", content=[{"type": "input_text", "text": "<environment_context>\n<cwd>/workspace</cwd>\n</environment_context>"}]),
            _line("2026-07-22T00:00:02Z", "message", role="user", content=[{"type": "input_text", "text": "Review the project and prepare a reusable handoff."}]),
            _line("2026-07-22T00:00:03Z", "message", role="user", content=[{"type": "input_text", "text": "Keep OpenCode out of scope."}]),
            _line("2026-07-22T00:00:04Z", "custom_tool_call", name="exec", call_id="call-1", input=script),
            _line("2026-07-22T00:00:05Z", "custom_tool_call_output", call_id="call-1", output=[{"type": "input_text", "text": output_text}]),
            _line("2026-07-22T00:00:06Z", "message", role="assistant", content=[{"type": "output_text", "text": "Implemented the handoff and ran validation."}]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            payload = extract_session_audit(path, "codex", session_id_hint="session-1")
            return payload.to_dict()

    def test_exec_envelope_recovers_intent_tools_files_and_status(self):
        audit = self._extract('{"exit_code":0,"output":"10 tests passed"}\n{"exit_code":1,"output":"syntax failed"}\n{}')
        self.assertEqual(audit["first_user_prompt"], "Review the project and prepare a reusable handoff.")
        self.assertEqual(audit["important_user_prompts"], ["Keep OpenCode out of scope."])
        self.assertEqual(audit["tools_used"]["shell_command"], 2)
        self.assertEqual(audit["tools_used"]["apply_patch"], 1)
        self.assertEqual({item["path"] for item in audit["files_touched"]["local"]}, {"src/app.py", "tests/test_app.py"})
        self.assertEqual([item["status"] for item in audit["commands"]], ["pass", "fail"])
        self.assertEqual([item["exit_code"] for item in audit["commands"]], [0, 1])

    def test_explicit_zero_exit_ignores_error_word_in_successful_output(self):
        audit = self._extract('{"exit_code":0,"output":"source contains error: marker"}\n{"exit_code":0,"output":"ok"}')
        self.assertEqual(audit["errors"]["count"], 0)
        self.assertEqual([item["status"] for item in audit["commands"]], ["pass", "pass"])


class HandoffPayloadTests(unittest.TestCase):
    def setUp(self):
        self.audit = {
            "session_id": "abc",
            "source": "codex",
            "first_user_prompt": "Build a context handoff feature.",
            "last_user_prompt": "Do not include OpenCode.",
            "important_user_prompts": ["Keep it deterministic."],
            "last_assistant_reply": "Done.",
            "last_assistant_before_last_user": "Implement a deterministic handoff capsule.",
            "has_assistant_after_last_user": True,
            "outcome_signal": "completed",
            "files_touched": {"local": [{"path": "audit/handoff.py", "edit_count": 1, "write_count": 0, "confidence": "high"}], "remote": []},
            "commands": [{"command": "python3 -m unittest", "status": "pass", "exit_code": 0, "evidence_id": "abc:tool:shell:4"}],
            "evidence": [
                {"id": "abc:message:1", "type": "user_prompt", "message_index": 1, "summary": "Build a context handoff feature."},
                {"id": "abc:file:audit_handoff.py", "type": "file", "message_index": 2, "summary": "local file touched: audit/handoff.py"},
            ],
        }

    def test_payload_preserves_handoff_contract(self):
        payload = build_handoff_payload(self.audit, metadata={"cwd": "/workspace"})
        self.assertEqual(payload["session"], "codex:abc")
        self.assertEqual(payload["cwd"], "/workspace")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["changed"][0]["path"], "audit/handoff.py")
        self.assertEqual(payload["verified"][0]["exit_code"], 0)
        self.assertIn("Do not include OpenCode.", payload["constraints"])
        self.assertTrue(any(item["id"] == "abc:file:audit_handoff.py" for item in payload["evidence"]))

    def test_status_is_partial_when_user_spoke_after_last_assistant_reply(self):
        self.audit["has_assistant_after_last_user"] = False
        payload = build_handoff_payload(self.audit, metadata={"cwd": "/workspace"})
        self.assertEqual(payload["status"], "partial")

    def test_bundle_has_compact_and_standard_text(self):
        bundle = build_handoff_bundle(self.audit, metadata={"cwd": "/workspace"})
        self.assertTrue(bundle["compact"].startswith("[HANDOFF]\n"))
        self.assertIn("verified:", bundle["standard"])
        self.assertIn("message 1", bundle["standard"])
        self.assertLessEqual(len(bundle["compact"]), len(bundle["standard"]))

    def test_referential_confirmation_uses_prior_assistant_context(self):
        self.audit["last_user_prompt"] = "可以，按这个需求继续吧"
        payload = build_handoff_payload(self.audit, metadata={"cwd": "/workspace"})
        self.assertEqual(payload["goal"], "Implement a deterministic handoff capsule.")


if __name__ == "__main__":
    unittest.main()
