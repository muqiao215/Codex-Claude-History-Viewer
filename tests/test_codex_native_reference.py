import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from history_core.codex_native import codex_native_reference


class CodexReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "项目"
        self.project.mkdir()
        self.session = "11111111-2222-3333-4444-555555555555"
        self.path = self.root / ("rollout-fixture-" + self.session + ".jsonl")
        self.rows = [
            {"type": "session_meta", "payload": {"id": self.session, "cwd": str(self.project)}},
            {"type": "turn_context", "payload": {"turn_id": "turn", "cwd": str(self.project), "model": "fixture-model"}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "中文 context"}},
        ]
        self.write()

    def write(self):
        self.path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in self.rows), encoding="utf-8")

    def read(self):
        return codex_native_reference(self.path, "desktop", self.session)

    def test_content_and_inode_are_bound_without_changing_source(self):
        raw = self.path.read_bytes()
        before = self.read()
        self.assertEqual(self.path.read_bytes(), raw)
        self.rows[-1]["payload"]["message"] = "changed"
        self.write()
        after = self.read()
        self.assertEqual(before["store_id"], after["store_id"])
        self.assertNotEqual(before["revision"], after["revision"])
        replacement = self.root / "replacement"
        replacement.write_bytes(self.path.read_bytes())
        replacement.replace(self.path)
        self.assertNotEqual(after["store_id"], self.read()["store_id"])

    def test_malformed_identity_model_lineage_and_partial_output_refuse(self):
        original = json.dumps(self.rows)
        mutations = [
            lambda r: r[0]["payload"].update(id="foreign"),
            lambda r: r[1]["payload"].update(thread_id="foreign"),
            lambda r: r[1]["payload"].update(model=""),
            lambda r: r[1].update(payload=None),
            lambda r: r.append(r[0]),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.rows = json.loads(original)
                mutate(self.rows)
                self.write()
                with self.assertRaises(ValueError):
                    self.read()
        self.rows = json.loads(original)
        self.write()
        self.path.write_bytes(self.path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "native_transcript_incomplete"):
            self.read()

    def test_symlink_and_nonfinite_json_refuse(self):
        alias = self.root / "alias"
        alias.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "canonical"):
            codex_native_reference(alias, "desktop", self.session)
        self.path.write_bytes(self.path.read_bytes() + b'{"type":"event_msg","payload":{"n":NaN}}\n')
        with self.assertRaises(ValueError):
            self.read()

    def test_headless_cli_returns_context_only_without_cache_or_source_writes(self):
        raw = self.path.read_bytes()
        result = subprocess.run([sys.executable, "-B", "-m", "history_core", "--source", "codex", "--source-path", str(self.path),
                                 "native-reference", self.session, "--device-id", "desktop"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["authorization"], "context_only")
        self.assertEqual(value["reference"], self.read())
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertFalse(list(self.root.rglob("*.sqlite")))

    @unittest.skipUnless(os.environ.get("CM_CODEX_REFERENCE_READER") and os.environ.get("CM_TEST_BUN"), "cross-repo reader not configured")
    def test_matches_controlmesh_typescript_reader(self):
        code = "const {CodexSessionStore}=await import(" + json.dumps(os.environ["CM_CODEX_REFERENCE_READER"]) + "); console.log(JSON.stringify(new CodexSessionStore(process.argv[1],'desktop').read(process.argv[2])));"
        result = subprocess.run([os.environ["CM_TEST_BUN"], "-e", code, str(self.path), self.session], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.read())


if __name__ == "__main__":
    unittest.main()
