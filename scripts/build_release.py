#!/usr/bin/env python3
"""Build a source-commit-bound portable release without local history/caches."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def build(output, revision='HEAD'):
    commit = subprocess.check_output(['git','rev-parse',revision],cwd=ROOT,text=True).strip()
    allowed = ['app.py','VERSION','README.md','LICENSE','AGENTS.md','PROJECT.md','DESIGN.md',
               'audit','history_core','static','demo','scripts','tests','docs']
    raw = subprocess.check_output(['git','archive','--format=zip',commit,'--',*allowed],cwd=ROOT)
    output = Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as target:
        manifest={}
        for name in sorted(original.namelist()):
            if name.endswith('/'): continue
            payload=original.read(name)
            target.writestr(zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0)),payload)
            manifest[name]=hashlib.sha256(payload).hexdigest()
        info={'source_commit':commit,'version':original.read('VERSION').decode().strip(),
              'files_sha256':manifest,'support':'Linux / Python 3.11+'}
        target.writestr(zipfile.ZipInfo('BUILD_INFO.json',date_time=(2020,1,1,0,0,0)),json.dumps(info,sort_keys=True,indent=2))
    result={'artifact':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(), 'source_commit':commit}
    output.with_suffix('.sha256').write_text(result['sha256']+'  '+output.name+'\n')
    print(json.dumps(result));return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--revision',default='HEAD');args=parser.parse_args();build(args.output,args.revision)
