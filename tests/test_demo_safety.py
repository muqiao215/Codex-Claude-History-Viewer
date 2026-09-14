import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

class DemoSafetyTests(unittest.TestCase):
    def test_demo_cannot_replace_existing_cache_or_user_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); cache=root/'index_linux.sqlite'
            with sqlite3.connect(cache) as db:
                db.execute('CREATE TABLE sessions(id TEXT,pinned INTEGER,ai_audit TEXT)')
                db.execute("INSERT INTO sessions VALUES('keep-real-session',1,'keep-audit')")
            before=cache.read_bytes()
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            p=subprocess.Popen([sys.executable,'-B','app.py','--demo','--data-dir',str(root),'--port',str(port)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                for _ in range(60):
                    self.assertIsNone(p.poll())
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:%s/api/workspace'%port,timeout=1) as res: data=json.load(res)
                        break
                    except OSError: time.sleep(.05)
                else:self.fail('demo start timed out')
                self.assertTrue(data['demo']);self.assertTrue(data['work'])
                self.assertTrue((root/'demo-isolated'/'index_linux.sqlite').exists())
                self.assertEqual(cache.read_bytes(),before)
            finally:
                p.terminate();p.communicate(timeout=10)
            self.assertEqual(cache.read_bytes(),before)
