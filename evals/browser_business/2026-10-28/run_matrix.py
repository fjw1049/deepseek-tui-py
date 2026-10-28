"""Sequential paired repeats avoid shared-browser and load interference."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PYTHON = ROOT / '.venv/bin/python'
BEFORE = Path('/tmp/browser-before-src/src')
AFTER = ROOT / 'src'

def tree_hash(source):
    h = hashlib.sha256()
    for path in sorted(source.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix in {'.py','.md'}:
            h.update(str(path.relative_to(source)).encode());h.update(path.read_bytes())
    return h.hexdigest()

if __name__ == '__main__':
    manifest = json.loads((HERE/'manifest.json').read_text())
    assert tree_hash(AFTER) == manifest['after_sha256'], 'Source changed after freeze'
    assert tree_hash(BEFORE) == manifest['before_sha256'], 'Baseline changed'
    for repeat in range(1,4):
        for case in ['shopping','crm','weekly','orders']:
            # Alternate ordering between independent repeats.
            for version in (['before','after'] if repeat%2 else ['after','before']):
                output = HERE/f'{version}-{case}-{repeat}.json'
                if output.exists() or output.with_suffix(".json.gz").exists():
                    raise RuntimeError(f'Refusing to overwrite {output}')
                env = dict(os.environ, PYTHONPATH=str(BEFORE if version=='before' else AFTER))
                started=time.time()
                with output.with_suffix('.log').open('w') as log:
                    try:
                        result = subprocess.run([str(PYTHON),str(HERE/'run_case.py'),
                            '--version',version,'--case',case,'--repeat',str(repeat),
                            '--output',str(output)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1100)
                        code=result.returncode
                    except subprocess.TimeoutExpired:
                        code='process_timeout'
                data=json.loads(output.read_text()) if output.exists() else {}
                print(json.dumps({'version':version,'case':case,'repeat':repeat,'exit':code,
                    'pass':data.get('pass',False),'seconds':round(time.time()-started,1),
                    'error':data.get('error')},ensure_ascii=False),flush=True)
                assert tree_hash(AFTER) == manifest['after_sha256'], 'Source changed mid-batch'
