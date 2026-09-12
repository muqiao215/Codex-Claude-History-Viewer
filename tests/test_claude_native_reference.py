import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from history_core.claude_native import claude_content_revision, claude_native_reference

FIXTURE = json.loads((Path(__file__).parent / "fixtures/claude-native-v2.json").read_text())


class ClaudeNativeReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="history-claude-native-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project-雪🌱"
        self.project.mkdir()
        self.path = self.root / (FIXTURE["session_id"] + ".jsonl")
        self.raw = FIXTURE["raw"].replace("@directory", json.dumps(str(self.project), ensure_ascii=False)[1:-1]).encode()
        self.path.write_bytes(self.raw)

    def reference(self, device="device-A"):
        return claude_native_reference(self.path, device, FIXTURE["session_id"])

    def test_shared_raw_byte_protocol_and_read_only_source(self):
        self.assertEqual(claude_content_revision(FIXTURE["store_id"], FIXTURE["raw"].encode()), FIXTURE["revision"])
        before = self.path.stat()
        ref = self.reference()
        self.assertEqual(ref["provider"], "claude")
        self.assertEqual(ref["directory"], str(self.project))
        self.assertEqual(ref["title"], "continuity 雪🌱")
        self.assertEqual(ref["model"], "fixture-model")
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertNotEqual(self.reference("device-B")["store_id"], ref["store_id"])

    def test_old_bytes_unknown_metadata_and_replacement_affect_identity(self):
        ref = self.reference()
        self.path.write_bytes(self.raw.replace(b"9007199254740993", b"9007199254740992"))
        self.assertNotEqual(self.reference()["revision"], ref["revision"])
        self.path.rename(self.root / "old.jsonl")
        self.path.write_bytes(self.raw)
        self.assertNotEqual(self.reference()["store_id"], ref["store_id"])

    def test_partial_malformed_nonobject_foreign_and_sidechain_rejected(self):
        cases = [self.raw[:-1], b"\xff\n", b"{}\n[\n", b"[]\n",
                 self.raw.replace(b'"isSidechain":false', b'"isSidechain":true'),
                 self.raw + b'{"sessionId":"foreign","type":"cost-state"}\n']
        for raw in cases:
            with self.subTest(raw=raw[:20]):
                self.path.write_bytes(raw)
                with self.assertRaises((ValueError, UnicodeError)):
                    self.reference()

    def test_directory_mix_path_alias_and_uuid_mismatch_rejected(self):
        rows = self.raw.decode().splitlines()
        changed = json.loads(rows[1]); changed["cwd"] = str(self.root)
        self.path.write_text(rows[0] + "\n" + json.dumps(changed) + "\n")
        with self.assertRaisesRegex(ValueError, "native_directory_changed"):
            self.reference()
        self.path.write_bytes(self.raw)
        alias = self.root / "alias.jsonl"; alias.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "native_store_path_must_be_canonical"):
            claude_native_reference(alias, "device-A", FIXTURE["session_id"])
        with self.assertRaisesRegex(ValueError, "native_session_path_mismatch"):
            claude_native_reference(self.path, "device-A", "11111111-2222-3333-4444-666666666666")

    def test_size_is_bounded_and_change_during_read_is_rejected(self):
        with self.path.open("wb") as stream:
            stream.truncate(32 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, "native_session_too_large"):
            self.reference()
        self.path.write_bytes(self.raw)
        import os
        original, calls = os.fstat, []

        def changed(fd):
            calls.append(fd)
            if len(calls) == 2:
                self.path.write_bytes(self.raw + b'{"type":"cost-state"}\n')
            return original(fd)

        with patch("history_core.claude_native.os.fstat", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "native_store_changed"):
                self.reference()

    def test_headless_cli_requires_no_cache_and_emits_context_only(self):
        run = subprocess.run([sys.executable, "-m", "history_core", "--source", "claude", "--source-path", str(self.path),
                              "native-reference", FIXTURE["session_id"], "--device-id", "device-A"],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads(run.stdout)
        self.assertEqual(data["authorization"], "context_only")
        self.assertEqual(data["reference"], self.reference())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [self.path.name, self.project.name])


if __name__ == "__main__":
    unittest.main()
