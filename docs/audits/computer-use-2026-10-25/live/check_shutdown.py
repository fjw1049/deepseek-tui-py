import os, subprocess, sys, tempfile, socket, time
from pathlib import Path
import httpx
root=Path('/Users/fjw/Desktop/deepseek-tui-py-main')
with tempfile.TemporaryDirectory(prefix='cua-shutdown-') as tmp:
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]; sock.close()
    env={**os.environ,'PYTHONPATH':str(root/'src'),'DEEPSEEK_HOME':tmp,'DEEPSEEK_API_KEY':'test-only-no-requests'}
    with open('/tmp/cua-qa/shutdown.log','w') as log:
        p=subprocess.Popen([sys.executable,'-m','deepseek_tui','serve','--http','--host','127.0.0.1','--port',str(port),'--insecure'],cwd=tmp,env=env,stdout=log,stderr=log)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=3) as c:
                for _ in range(100):
                    try:
                        if c.get('/health').status_code==200: break
                    except httpx.HTTPError: pass
                    time.sleep(.1)
                r=c.post('/v1/threads',json={'workspace':tmp,'title':'Shutdown test'});r.raise_for_status();tid=r.json()['id']
                with c.stream('GET',f'/v1/threads/{tid}/events') as stream:
                    stream.raise_for_status();start=time.monotonic();p.terminate()
                    try:
                        p.wait(timeout=8); print('EXIT',p.returncode,'SECONDS',round(time.monotonic()-start,2))
                    except subprocess.TimeoutExpired: print('HANG_WITH_IDLE_SSE_AFTER_8_SECONDS')
        finally:
            if p.poll() is None: p.kill();p.wait()
