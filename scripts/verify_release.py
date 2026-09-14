#!/usr/bin/env python3
"""Linux clean-install and source-integrity acceptance for the portable release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv
import zipfile


def verify(root, isolated, previous=None):
    root=Path(root).resolve();isolated=Path(isolated).resolve()
    envdir=isolated/'venv';venv.EnvBuilder(with_pip=False).create(envdir)
    python=envdir/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    home=isolated/'home';home.mkdir();env=dict(os.environ,HOME=str(home),XDG_CACHE_HOME=str(home/'cache'),PYTHONDONTWRITEBYTECODE='1');env.pop('DISPLAY',None)
    env.pop('PYTHONPATH',None)
    def run(args,cwd=root):
        result=subprocess.run([str(python),'-B',*args],cwd=cwd,env=env,capture_output=True,text=True,timeout=60)
        if result.returncode: raise RuntimeError(result.stderr or result.stdout)
        return result.stdout.strip()
    before={str(p.relative_to(root/'demo')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'demo').rglob('*') if p.is_file()}
    source=root/'demo/codex/sessions';cache=isolated/'cache'
    prefix=['-m','history_core','--source','codex','--source-path',str(source),'--data-dir',str(cache)]
    run(prefix+['refresh']);first=json.loads(run(prefix+['search','--limit','2']))
    second=json.loads(run(prefix+['search','--limit','2','--offset','2','--index-revision',first['index_revision']]))
    assert len({x['id'] for x in first['items']+second['items']})==4
    handoff=json.loads(run(prefix+['handoff',first['items'][0]['id']]))
    assert handoff['authorization']=='context_only'
    assert handoff['payload']['provenance']['content_revision'].startswith('sha256:')
    version=run(['app.py','--version'])
    # Use only synthetic paths and Viewer-owned caches in the upgrade/rollback check.
    upgrade={'status':'not_requested'}
    if previous:
        previous=Path(previous).resolve();legacy=isolated/'legacy-cache';legacy.mkdir()
        snippet="from pathlib import Path; from history_core.sources import Indexer; i=Indexer(Path(%r),Path(%r),'codex',parser_version=5); i.maybe_update_index(0); print(len(i.list_sessions_page()['items'])); i.conn.close()" % (str(source),str(legacy))
        old_count=run(['-c',snippet],cwd=previous)
        backup=isolated/'rollback-cache';shutil.copytree(legacy,backup)
        new_count=run(['-c',snippet])
        rollback_snippet=snippet.replace(repr(str(legacy)),repr(str(backup)))
        rolled_count=run(['-c',rollback_snippet],cwd=previous)
        assert old_count==new_count==rolled_count=='4'
        upgrade={'status':'passed','previous_version':run(['app.py','--version'],cwd=previous),'before':old_count,'after':new_count,'rollback':rolled_count}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    web_cache=isolated/'web-cache';web_cache.mkdir()
    existing=web_cache/'index_linux.sqlite'
    with sqlite3.connect(existing) as db:
        db.execute('CREATE TABLE sessions(id TEXT,pinned INTEGER,ai_audit TEXT)')
        db.execute("INSERT INTO sessions VALUES ('real-cache-sentinel',1,'retained audit')")
    cached_before=existing.read_bytes()
    process=subprocess.Popen([str(python),'-B','app.py','--demo','--data-dir',str(isolated/'web-cache'),'--port',str(port)],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    base='http://127.0.0.1:'+str(port)
    try:
        for _ in range(100):
            if process.poll() is not None: raise RuntimeError(process.stderr.read())
            try:
                with urllib.request.urlopen(base+'/api/version',timeout=1) as response: observed=json.load(response)
                break
            except (OSError,urllib.error.URLError):time.sleep(.1)
        else:raise RuntimeError('server_start_timeout')
        with urllib.request.urlopen(base+'/api/workspace',timeout=15) as response: workspace=json.load(response)
        assert observed['version']==version and workspace['demo'] is True and workspace['work']
        assert all(x['source'] not in ('hermes','opencode') for x in workspace['sources'])
        request=urllib.request.Request(base+'/api/linux/codex/cleanup/weak-sessions',data=b'{}',headers={'Content-Type':'application/json'})
        try:urllib.request.urlopen(request);raise AssertionError('cleanup allowed')
        except urllib.error.HTTPError as error:assert error.code==405
    finally:
        process.terminate();process.communicate(timeout=10)
    after={str(p.relative_to(root/'demo')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'demo').rglob('*') if p.is_file()}
    assert before==after,'demo source changed'
    assert existing.read_bytes()==cached_before,'demo overwrote existing cache'
    assert not list(home.rglob('*')),'unexpected HOME write'
    return {'status':'passed','platform':sys.platform,'python':run(['--version']), 'version':version,'runtime_identity':observed,'source_unchanged':True,'existing_cache_unchanged':True,'home_unchanged':True,'pagination':'revision_bound','workspace_records':len(workspace['work']),'cleanup_http':405,'upgrade_rollback':upgrade}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--artifact',type=Path);parser.add_argument('--previous-root',type=Path);parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hv-release-') as temp:
        isolated=Path(temp);root=args.root
        if args.artifact:
            root=isolated/'release';root.mkdir()
            with zipfile.ZipFile(args.artifact) as archive:
                for name in archive.namelist():
                    if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('unsafe_archive_path')
                archive.extractall(root)
            info=json.loads((root/'BUILD_INFO.json').read_text())
            for name,digest in info['files_sha256'].items(): assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
        result=verify(root,isolated,args.previous_root)
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2,ensure_ascii=False));print(json.dumps(result,ensure_ascii=False))
