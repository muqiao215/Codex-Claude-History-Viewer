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
