import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audit.handoff import build_handoff_bundle
from history_core.provenance import selected_audit


class ProvenanceTests(unittest.TestCase):
    def fixture(self, root, raw):
        path = root / 'session.jsonl'
        path.write_bytes(raw)
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE sessions (id TEXT, file_path TEXT)')
        conn.execute('INSERT INTO sessions VALUES (?, ?)', ('abc', str(path)))
        return SimpleNamespace(source='codex', sessions_dir=root, lock=threading.Lock(), conn=conn)

    def test_revision_matches_exact_selected_source_and_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = (json.dumps({'type': 'session_meta', 'payload': {'id': 'abc'}}) + '\n').encode()
            indexer = self.fixture(root, raw)
            audit, first = selected_audit(indexer, 'abc')
            self.assertEqual(first['content_revision'], 'sha256:' + hashlib.sha256(raw).hexdigest())
            self.assertEqual(first['locator']['path'], str(root / 'session.jsonl'))
            (root / 'session.jsonl').write_bytes(raw + b'{}\n')
            _, second = selected_audit(indexer, 'abc')
            self.assertNotEqual(first['content_revision'], second['content_revision'])
            self.assertEqual(audit['session_id'], 'abc')

    def test_bounded_prefix_never_claims_full_revision_or_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            indexer = self.fixture(Path(tmp), b'{}\n' * 10000)
            with patch('history_core.provenance.MAX_SOURCE_BYTES', 128):
                audit, provenance = selected_audit(indexer, 'abc')
            self.assertTrue(provenance['truncated'])
            self.assertLessEqual(provenance['bytes_captured'], 128)
            self.assertEqual(provenance['content_revision'], 'unknown')
            self.assertEqual(audit['outcome_signal'], 'unknown')

    def test_source_snapshot_does_not_probe_unselected_project_git(self):
        with patch('audit.handoff._git_state', side_effect=AssertionError('unselected project read')):
            result=build_handoff_bundle({'source':'codex','session_id':'abc'},metadata={'cwd':'/project'},provenance={'content_revision':'unknown'})
        self.assertFalse(result['payload']['git']['available'])

    def test_export_head_never_becomes_historical_baseline(self):
        audit = {'source': 'codex', 'session_id': 'abc', 'commands': [
            {'command': 'pytest', 'status': 'pass', 'exit_code': 0, 'evidence_id': 'a'}],
            'files_touched': {'local': [{'path': 'a.py'}, {'path': 'b.py'}]}}
        with patch('audit.handoff._git_state', return_value={'available': True, 'commit': 'current-head', '_paths': ['a.py']}):
            bundle = build_handoff_bundle(audit, metadata={'cwd': '/project'})
        payload = bundle['payload']
        self.assertEqual(payload['evidence_baseline']['revision'], 'unknown')
        self.assertEqual(payload['verified'][0]['current_verification'], 'unknown')
        self.assertEqual(len(payload['changed']), 2)
        self.assertEqual(payload['authorization'], 'context_only')
        self.assertEqual(payload['decisions'], [])
        self.assertEqual(payload['specmesh']['status'], 'not_loaded')
        self.assertIn('historical code baseline: unknown', bundle['standard'])

    def test_unselected_path_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            indexer = self.fixture(root, b'{}\n')
            indexer.conn.execute('UPDATE sessions SET file_path = ?', (str(root.parent / 'elsewhere'),))
            with self.assertRaisesRegex(ValueError, 'outside_selection'):
                selected_audit(indexer, 'abc')
            indexer.conn.execute('UPDATE sessions SET file_path = ?', (str(root / 'alias.jsonl'),))
            (root / 'alias.jsonl').symlink_to(root / 'session.jsonl')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                selected_audit(indexer, 'abc')

    def test_missing_native_audit_remains_explicit_and_revision_unknown(self):
        audit, provenance = selected_audit(SimpleNamespace(source='hermes'), 'x')
        self.assertIsNone(audit)
        self.assertEqual(provenance['content_revision'], 'unknown')

    def test_dotdot_escape_rejected_without_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'selected'
            root.mkdir()
            indexer = self.fixture(root, b'{}\n')
            (base / 'outside.jsonl').write_bytes(b'{}\n')
            indexer.conn.execute('UPDATE sessions SET file_path = ?', (str(root / '..' / 'outside.jsonl'),))
            with self.assertRaisesRegex(ValueError, 'outside_selection'):
                selected_audit(indexer, 'abc')

    def test_selected_snapshot_never_writes_tempfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            indexer = self.fixture(Path(tmp), b'{}\n')
            with patch('tempfile.TemporaryDirectory', side_effect=AssertionError('unexpected temporary write')), patch.object(Path, 'write_bytes', side_effect=AssertionError('unexpected write')):
                audit, provenance = selected_audit(indexer, 'abc')
            self.assertIsNotNone(audit)
            self.assertEqual(provenance['bytes_captured'], 3)

    def test_native_size_preflight_runs_before_metadata_or_audit(self):
        from history_core.service import handoff
        from unittest.mock import Mock
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.execute('CREATE TABLE message (id TEXT, data TEXT)')
        conn.execute('CREATE TABLE part (message_id TEXT, session_id TEXT, data TEXT)')
        conn.execute('INSERT INTO message VALUES (?, ?)', ('m', '{}'))
        conn.execute('INSERT INTO part VALUES (?, ?, ?)', ('m', 'abc', 'x' * 1025))
        indexer = SimpleNamespace(source='opencode', conn=conn, lock=threading.Lock(), get_session_metadata=Mock())
        with patch('history_core.provenance.MAX_SOURCE_BYTES', 1024):
            with self.assertRaisesRegex(ValueError, 'source_limit_exceeded'):
                handoff(indexer, 'abc')
        indexer.get_session_metadata.assert_not_called()

    def test_plans_are_explicit_bounded_unverified_context(self):
        from history_core.service import handoff
        from unittest.mock import Mock
        indexer = SimpleNamespace(source='hermes', get_session_metadata=Mock(return_value={'id': 'abc', 'cwd': '/project'}),
                                  build_session_audit=Mock(return_value={'session_id': 'abc'}))
        plans = [{'rel_path': 'plans/a/task_plan.md', 'mtime_ms': 123,
                  'sections': {'Status': 'x' * 1000}}] * 5
        with patch('history_core.sources.scan_plan_files', return_value=plans) as scan:
            self.assertEqual(handoff(indexer, 'abc')['payload']['specmesh']['status'], 'not_loaded')
            scan.assert_not_called()
            bundle = handoff(indexer, 'abc', include_plans=True)
        spec = bundle['payload']['specmesh']
        self.assertEqual(len(spec['files']), 3)
        self.assertEqual(len(spec['files'][0]['sections']['Status']), 600)
        self.assertEqual(spec['files'][0]['path'], 'plans/a/task_plan.md')
        self.assertEqual(bundle['payload']['decisions'], [])
        self.assertIn('unverified candidate context', bundle['standard'])

    def test_workspace_preserves_evidence_and_blockers(self):
        from history_core.service import workspace
        from unittest.mock import Mock
        indexer = SimpleNamespace(list_sessions_page=Mock(return_value={'items': [{'id': 'abc'}]}))
        payload = {'blockers': ['failed test'], 'decisions': [], 'evidence': [{'id': 'line-1'}]}
        with patch('history_core.service.handoff', return_value={'payload': payload}):
            item = workspace([('codex', 'local', indexer)])['work'][0]
        self.assertEqual(item['blockers'], ['failed test'])
        self.assertEqual(item['evidence'], [{'id': 'line-1'}])
        self.assertEqual(item['decisions'], [])
