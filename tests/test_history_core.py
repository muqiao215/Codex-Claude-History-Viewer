import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audit.git_snapshot import legacy_git_state
from history_core import service
from history_core.sources import Indexer, parse_codex_session_file

REPO = Path(__file__).resolve().parents[1]

class HistoryCoreTests(unittest.TestCase):
    def test_headless_import_has_no_web_or_app(self):
        result = subprocess.run([sys.executable, '-c',
            "import sys; import history_core.sources; assert 'app' not in sys.modules; assert 'http.server' not in sys.modules"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_cwd_cannot_probe_process_repository(self):
        with patch('audit.git_snapshot.subprocess.run', side_effect=AssertionError('unexpected git')):
            for cwd in ('', None, 'relative'):
                self.assertFalse(legacy_git_state(cwd)['available'])

    def test_native_parser_cli_search_and_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'sessions'; source.mkdir()
            fixture = source / 'session.jsonl'
            fixture.write_text('\n'.join(json.dumps(x) for x in [
                {'timestamp':'2026-09-11T00:00:00Z','type':'session_meta','payload':{'id':'fixture','cwd':str(root)}},
                {'timestamp':'2026-09-11T00:00:01Z','type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'Check the handoff fixture'}]}},
                {'timestamp':'2026-09-11T00:00:02Z','type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Work remains; tests need checking.'}]}}
            ])+'\n')
            before = fixture.read_bytes()
            prefix = [sys.executable,'-B','-m','history_core','--source','codex','--source-path',str(source),'--data-dir',str(root/'cache')]
            def call(*args):
                out = subprocess.run(prefix + list(args), cwd=REPO, capture_output=True, text=True)
                self.assertEqual(out.returncode, 0, out.stderr)
                return json.loads(out.stdout)
            call('refresh')
            result = call('search', '--query', 'handoff')
            self.assertEqual(result['items'][0]['id'], 'fixture')
            result = call('handoff', 'fixture')
            self.assertEqual(result['authorization'], 'context_only')
            self.assertEqual(result['payload']['session'], 'codex:fixture')
            self.assertEqual(call('health')['freshness'], 'unknown')
            self.assertEqual(fixture.read_bytes(), before)

    def test_empty_workspace_and_unavailable_source_are_explicit(self):
        self.assertEqual(service.workspace([])['mode'], 'history_snapshot')
        class Broken:
            def list_sessions_page(self, **kwargs): raise OSError('unavailable')
        result = service.workspace([('linux','codex',Broken())])
        self.assertEqual(result['work'], [])
        self.assertEqual(result['errors'][0]['error'], 'source_unavailable')

    def test_existing_web_import_reexports_same_parser(self):
        app = importlib.import_module('app')
        self.assertIs(app.Indexer, Indexer)
        self.assertIs(app.parse_codex_session_file, parse_codex_session_file)

class MachineReaderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.cache = self.root / 'cache'

    def fixture(self, session_id='short', cwd=None):
        path = self.source / (session_id + '.jsonl')
        path.write_text('\n'.join(json.dumps(x) for x in [
            {'timestamp': '2026-09-14T00:00:00Z', 'type': 'session_meta',
             'payload': {'id': session_id, 'cwd': cwd}},
            {'timestamp': '2026-09-14T00:00:01Z', 'type': 'response_item',
             'payload': {'type': 'message', 'role': 'user',
                         'content': [{'type': 'input_text', 'text': '独立只读检索证据'}]}},
        ]) + '\n', encoding='utf-8')
        return path

    def reader(self, **kwargs):
        from history_core import HistoryReader
        reader = HistoryReader('codex', self.source, kwargs.get('data_dir', self.cache))
        self.addCleanup(reader.close)
        return reader

    def test_public_capabilities_do_not_forward_mutators_or_connection(self):
        reader = self.reader()
        public = {name for name in dir(reader) if not name.startswith('_')}
        self.assertEqual(public, {'refresh', 'health', 'search', 'handoff', 'close'})
        for name in ('archive_session', 'rename_session', 'delete_session',
                     'cleanup_weak_sessions', 'pin_session', 'conn', 'indexer'):
            self.assertFalse(hasattr(reader, name), name)

    def test_disjoint_cache_required_in_both_directions_before_writes(self):
        from history_core import HistoryReader
        for data in (self.source, self.source / 'cache', self.root):
            with self.assertRaisesRegex(ValueError, 'disjoint'):
                HistoryReader('codex', self.source, data)
        self.assertEqual(list(self.source.iterdir()), [])

    def test_source_file_and_directory_symlinks_fail_before_cache_creation(self):
        outside = self.root / 'outside'; outside.mkdir()
        (outside / 'secret.jsonl').write_text('do not read')
        for target in (outside, outside / 'secret.jsonl'):
            link = self.source / 'escape.jsonl'
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'source_symlink'):
                self.reader()
            self.assertFalse(self.cache.exists())
            link.unlink()

    def test_unreadable_source_fails_explicitly_before_cache_creation(self):
        self.fixture()
        original = Path.open
        def denied(path, *args, **kwargs):
            if path.parent == self.source:
                raise PermissionError('synthetic unreadable source')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', denied):
            with self.assertRaises(PermissionError):
                self.reader()
        self.assertFalse(self.cache.exists())

    def test_cache_binding_prevents_cross_source_results(self):
        self.fixture('first')
        with self.reader() as first:
            first.refresh()
        other = self.root / 'other'; other.mkdir()
        from history_core import HistoryReader
        with HistoryReader('codex', other, self.cache) as second:
            self.assertEqual(second.search()['items'], [])
        self.assertEqual(len(list(self.cache.glob('machine-*'))), 2)

    def test_cache_symlink_is_rejected(self):
        reader = self.reader(); reader.close()
        cache = next(self.cache.glob('machine-*'))
        target = self.root / 'untouched'; target.write_bytes(b'unchanged')
        (cache / 'index.sqlite').unlink()
        (cache / 'index.sqlite').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'cache_symlink'):
            self.reader()
        self.assertEqual(target.read_bytes(), b'unchanged')

    def test_poisoned_cached_file_cannot_authorize_external_handoff_read(self):
        self.fixture(); reader = self.reader(); reader.refresh(); reader.close()
        import sqlite3
        db = next(self.cache.glob('machine-*/index.sqlite'))
        with sqlite3.connect(db) as conn:
            conn.execute('UPDATE sessions SET file_path = ?', (str(REPO / 'app.py'),))
        with self.reader() as reopened:
            with self.assertRaisesRegex(ValueError, 'outside_selection'):
                reopened.handoff('short')

    def test_fixed_revision_tied_pages_are_complete_and_short_logs_unchanged(self):
        for name in ('z', 'b', 'a', 'y', 'c'):
            self.fixture(name)
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        reader = self.reader(); reader.refresh()
        rows = []; offset = 0
        while True:
            page = reader.search(limit=2, offset=offset)
            rows.extend(row['id'] for row in page['items'])
            if not page['has_more']: break
            offset = page['next_offset']
        self.assertEqual(rows, ['a', 'b', 'c', 'y', 'z'])
        self.assertEqual({p.name: p.read_bytes() for p in self.source.iterdir()}, before)

    def test_no_network_listener_background_or_app_initialization(self):
        self.fixture()
        import threading
        threads = set(threading.enumerate())
        with patch('socket.socket', side_effect=AssertionError('unexpected network')),\
             patch('threading.Thread.start', side_effect=AssertionError('unexpected background')),\
             patch('subprocess.Popen', side_effect=AssertionError('unexpected subprocess')):
            reader = self.reader()
            reader.refresh()
            self.assertEqual(len(reader.search()['items']), 1)
            self.assertEqual(reader.handoff('short')['authorization'], 'context_only')
            self.assertEqual(reader.health()['freshness'], 'unknown')
        self.assertEqual(set(threading.enumerate()), threads)

    def test_unavailable_audit_is_explicit(self):
        self.fixture(); reader = self.reader(); reader.refresh()
        with patch('history_core.provenance.extract_session_audit_bytes', return_value=None):
            with self.assertRaisesRegex(ValueError, 'audit_not_supported_or_unavailable'):
                reader.handoff('short')

    def test_source_disappearing_does_not_report_readable(self):
        reader = self.reader()
        self.source.rmdir()
        with self.assertRaisesRegex(ValueError, 'sessions_directory_required'):
            reader.health()

    def test_cli_isolated_home_and_mutation_rejection_file_effects(self):
        import os
        fixture = self.fixture()
        before = fixture.read_bytes()
        home = self.root / 'empty-home'; home.mkdir()
        env = dict(os.environ)
        env.pop('DISPLAY', None)
        env['HOME'] = str(home)
        env['XDG_CACHE_HOME'] = str(home / 'cache')
        prefix = [sys.executable, '-B', '-m', 'history_core', '--source', 'codex',
                  '--source-path', str(self.source), '--data-dir', str(self.cache)]
        for command in (['refresh'], ['search', '--query', '独立'], ['handoff', 'short']):
            out = subprocess.run(prefix + command, cwd=REPO, env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIsInstance(json.loads(out.stdout), dict)
        for command in ('archive', 'rename', 'delete', 'cleanup', 'pin'):
            out = subprocess.run(prefix + [command], cwd=REPO, env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 2)
            self.assertIn('invalid choice', out.stderr)
        self.assertEqual(fixture.read_bytes(), before)
        self.assertEqual(list(home.rglob('*')), [])
        self.assertEqual(set(self.root.iterdir()), {self.source, self.cache, home})

    def test_native_database_adapter_stays_read_only(self):
        from test_opencode_audit import OpenCodeAuditTests
        from history_core import HistoryReader
        fixture = OpenCodeAuditTests()
        fixture.db_path = self.root / 'opencode.db'
        fixture._seed_db()
        before = fixture.db_path.read_bytes()
        with HistoryReader('opencode', fixture.db_path) as reader:
            reader.refresh()
            self.assertEqual(reader.search(limit=1)['items'][0]['id'], 'ses-1')
            self.assertEqual(reader.handoff('ses-1')['authorization'], 'context_only')
            self.assertEqual(reader.health()['status'], 'readable')
        self.assertEqual(fixture.db_path.read_bytes(), before)
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'source', 'opencode.db'})

    def test_relative_cwd_handoff_cannot_probe_current_project(self):
        self.fixture(cwd='relative/project')
        reader = self.reader(); reader.refresh()
        with patch('audit.git_snapshot.subprocess.run', side_effect=AssertionError('unexpected git')):
            self.assertEqual(reader.handoff('short')['authorization'], 'context_only')
