"""Portable independent delivery contracts; source bytes must remain unchanged."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from history_core import HistoryReader
from scripts.generate_synthetic_sessions import generate_dataset

REPO = Path(__file__).resolve().parents[1]

class DeliveryContractTests(unittest.TestCase):
    def test_revision_required_across_processes_and_changes_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'source'; source.mkdir(); cache = root/'cache'
            generate_dataset(source, 4, seed=42)
            with HistoryReader('codex', source, cache) as reader:
                reader.refresh(); first = reader.search(limit=2)
                revision = first['index_revision']
                reader.refresh()
                self.assertEqual(reader.search(index_revision=revision)['index_revision'], revision)
                with HistoryReader('codex', source, cache) as other:
                    with self.assertRaisesRegex(ValueError, 'index_revision_required'):
                        other.search(limit=2, offset=2)
                    second = other.search(limit=2, offset=2, index_revision=revision)
                    self.assertEqual(len({x['id'] for x in first['items'] + second['items']}), 4)
                    (source/'session_00000.jsonl').unlink(); other.refresh()
                with self.assertRaisesRegex(ValueError, 'index_revision_changed'):
                    reader.search(limit=2, offset=2, index_revision=revision)
                self.assertNotEqual(reader.search()['index_revision'], revision)

    def test_jsonl_source_matrix_read_only_and_short_sessions(self):
        fixtures = {
            'codex': {'type':'session_meta','payload':{'id':'tiny','cwd':None},'timestamp':'2026-09-01T00:00:00Z'},
            'claude': {'sessionId':'tiny','type':'user','message':{'role':'user','content':'hello'},'timestamp':'2026-09-01T00:00:00Z'},
            'openclaw': {'type':'session','id':'tiny','timestamp':'2026-09-01T00:00:00Z'},
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for provider, obj in fixtures.items():
                with self.subTest(provider=provider):
                    source=root/provider/'sessions';source.mkdir(parents=True)
                    file=source/'tiny.jsonl';file.write_text(json.dumps(obj)+'\n',encoding='utf-8')
                    before=file.read_bytes()
                    with HistoryReader(provider, source, root/('cache-'+provider)) as reader:
                        reader.refresh(); found=reader.search()['items'];self.assertEqual(len(found),1)
                        result=reader.handoff(found[0]['id'])
                        self.assertEqual(result['authorization'],'context_only')
                        self.assertEqual(result['payload']['provenance']['content_revision'], 'sha256:'+hashlib.sha256(before).hexdigest())
                        reader.refresh()
                    self.assertEqual(file.read_bytes(),before)
                    self.assertEqual(list(source.iterdir()),[file])

    def test_handoff_requires_refresh_after_source_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir();generate_dataset(source,1,seed=42)
            with HistoryReader('codex',source,root/'cache') as reader:
                reader.refresh();path=source/'session_00000.jsonl'
                path.write_bytes(path.read_bytes().replace(b'synthetic-codex-00000',b'synthetic-codex-00999'))
                with self.assertRaisesRegex(ValueError,'source_changed_since_index'):
                    reader.handoff('synthetic-codex-00000')
                reader.refresh()
                self.assertEqual(reader.handoff('synthetic-codex-00999')['payload']['provenance']['session_id'],'synthetic-codex-00999')

    def test_native_database_matrix_read_only_and_explicit_audit_limits(self):
        from test_opencode_audit import OpenCodeAuditTests
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); fixture=OpenCodeAuditTests();fixture.db_path=root/'opencode.db';fixture._seed_db()
            hermes=root/'hermes.db'
            with sqlite3.connect(hermes) as db:
                db.executescript('CREATE TABLE sessions(id TEXT,source TEXT,user_id TEXT,model TEXT,started_at REAL,ended_at REAL,message_count INTEGER,title TEXT); CREATE TABLE messages(session_id TEXT,content TEXT,reasoning TEXT);')
                db.execute("INSERT INTO sessions VALUES ('h1','/fixture','user','model',1,2,1,'hello')")
            for provider,dbpath in [('opencode',fixture.db_path),('hermes',hermes)]:
                with self.subTest(provider=provider):
                    before=dbpath.read_bytes()
                    with HistoryReader(provider,dbpath) as reader:
                        reader.refresh(); data=reader.search();self.assertTrue(data['items'])
                        if provider=='hermes':
                            with self.assertRaisesRegex(ValueError,'audit_not_supported_or_unavailable'):
                                reader.handoff('h1')
                        else:
                            self.assertEqual(reader.handoff('ses-1')['authorization'],'context_only')
                    self.assertEqual(dbpath.read_bytes(),before)

    def test_legacy_cache_signature_backfill_preserves_source_and_title(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir();generate_dataset(source,2,seed=42)
            snapshot={p.name:p.read_bytes() for p in source.glob('*.jsonl')}
            with HistoryReader('codex',source,root/'cache') as reader:
                reader.refresh();indexer=reader._HistoryReader__indexer
                indexer.conn.execute('UPDATE sessions SET file_signature=NULL');indexer.conn.commit()
                reader.refresh();self.assertEqual(len(reader.search()['items']),2)
                self.assertTrue(all(x[0] for x in indexer.conn.execute('SELECT file_signature FROM sessions')))
            self.assertEqual({p.name:p.read_bytes() for p in source.glob('*.jsonl')},snapshot)

if __name__=='__main__': unittest.main()
