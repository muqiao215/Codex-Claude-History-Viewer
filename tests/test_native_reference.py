import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from history_core.native import content_revision, native_reference


FIXTURE = json.loads((Path(__file__).parent / "fixtures/native-session-v2.json").read_text())


def populate(db):
    db.executescript(FIXTURE["schema"])
    for table, values in FIXTURE["rows"]:
        db.execute("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" for _ in values)), values)
    db.commit()


class NativeReferenceTests(unittest.TestCase):
    def test_shared_content_fixture(self):
        with sqlite3.connect(":memory:") as db:
            populate(db)
            self.assertEqual(content_revision(db, FIXTURE["session_id"], FIXTURE["store_id"]), FIXTURE["revision"])

    def test_read_only_reference_detects_old_content_and_device_change(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "opencode.db"
            with sqlite3.connect(str(source)) as db:
                populate(db)
                db.execute("UPDATE session SET directory=?", (temp,))
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            ref = native_reference(source, "device-A", FIXTURE["session_id"])
            self.assertEqual(ref["model"], "fixture/model")
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            other = native_reference(source, "device-B", FIXTURE["session_id"])
            self.assertNotEqual(ref["store_id"], other["store_id"])
            with sqlite3.connect(str(source)) as db:
                db.execute("UPDATE message SET data='{}' WHERE id='msg_A'")
            self.assertNotEqual(native_reference(source, "device-A", FIXTURE["session_id"])["revision"], ref["revision"])

    def test_cli_exposes_explicit_context_only_reference_without_web_or_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "opencode.db"
            with sqlite3.connect(str(source)) as db:
                populate(db)
                db.execute("UPDATE session SET directory=?", (temp,))
            result = subprocess.run([sys.executable, "-m", "history_core", "--source", "opencode", "--source-path", str(source),
                                     "native-reference", FIXTURE["session_id"], "--device-id", "device-A"], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertEqual(envelope["authorization"], "context_only")
            self.assertEqual(envelope["reference"], native_reference(source, "device-A", FIXTURE["session_id"]))
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()), ["opencode.db"])

    def test_archive_and_large_content_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "opencode.db"
            with sqlite3.connect(str(source)) as db:
                populate(db)
                db.execute("UPDATE session SET directory=?,time_archived=1", (temp,))
            with self.assertRaisesRegex(ValueError, "native_session_missing_or_archived"):
                native_reference(source, "device-A", FIXTURE["session_id"])
            with sqlite3.connect(str(source)) as db:
                db.execute("UPDATE session SET time_archived=NULL")
                db.execute("UPDATE part SET data=zeroblob(33554433)")
            with self.assertRaisesRegex(ValueError, "native_session_too_large"):
                native_reference(source, "device-A", FIXTURE["session_id"])
