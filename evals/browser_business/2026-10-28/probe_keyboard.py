"""Post-batch deterministic diagnosis of real editor navigation; no product changes."""
import asyncio
import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from run_case import Handler
from deepseek_tui.browser.service import BrowserService, BrowserAction
from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.input import press_key

STATE="""(() => {let e=document.querySelector('#editor'),s=getSelection();
 const offset=(n,p)=>{let r=document.createRange();r.selectNodeContents(e);r.setEnd(n,p);return r.toString().length};
 let r=document.createRange();r.selectNodeContents(e);
 return {anchor:offset(s.anchorNode,s.anchorOffset),focus:offset(s.focusNode,s.focusOffset),
 selected:s.toString(),length:r.toString().length}})()"""
RESET="""(() => {let e=document.querySelector('#editor');e.focus();let n=e.querySelector('h2').firstChild;
 let r=document.createRange();r.setStart(n,5);r.collapse(true);let s=getSelection();
 s.removeAllRanges();s.addRange(r);return true})()"""

async def main():
    root=Path(tempfile.mkdtemp(prefix='keyboard-probe-'))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    service=BrowserService(root/'artifacts',profile_root=root/'profile')
    evidence=[]
    try:
        await service.action('probe',BrowserAction(action='open',url=f'http://127.0.0.1:{server.server_port}/weekly'))
        run=service.runs['probe'];client=run.session._internal.client
        observed=await service.action('probe',BrowserAction(action='observe',selector='#editor',include_editable=True))
        checked=await service.action('probe',BrowserAction(action='check_text',selector='#editor',text='2026年第22周'))
        evidence.append({'editable_check':{'text_present_in_authorized_observation':
            '2026年第22周' in observed['observation']['text'],
            'check_text_success':checked.get('success'),'check_text_content':checked.get('content')}})
        for key in ['Meta+End','Meta+ArrowDown','Ctrl+End','Meta+Shift+ArrowLeft','Shift+ArrowLeft']:
            await evaluate(client,RESET)
            before=await evaluate(client,STATE)
            await press_key(run,key)
            after=await evaluate(client,STATE)
            evidence.append({'key':key,'before':before,'after':after})
        # Chromium's explicit editing command is a diagnostic control, not a product fix.
        await evaluate(client,RESET)
        await client.send('Input.dispatchKeyEvent',{'type':'rawKeyDown','key':'End','code':'End',
            'windowsVirtualKeyCode':35,'modifiers':4,'commands':['moveToEndOfDocument']})
        await client.send('Input.dispatchKeyEvent',{'type':'keyUp','key':'End','code':'End',
            'windowsVirtualKeyCode':35,'modifiers':4})
        evidence.append({'explicit_command':'moveToEndOfDocument','after':await evaluate(client,STATE)})
    finally:
        await service.close_all();server.shutdown()
    path=Path(__file__).with_name('keyboard-probe.json')
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps(evidence,ensure_ascii=False))

asyncio.run(main())
