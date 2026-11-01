import asyncio
import json
from pathlib import Path

from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.service import BrowserAction, BrowserService

ROOT = Path('/private/tmp/browser-optimization-20261012/observe')
PAGE = b'''<!doctype html><title>Owned observation probe</title>
<button id=chosen onclick="document.querySelector('#result').textContent='CHOSEN'">Chosen</button>
<button id=other onclick="document.querySelector('#result').textContent='OTHER'">Other</button>
<input type=submit value="Continue">
<fieldset disabled><button>Disabled inherited</button></fieldset>
<span id=label>ARIA label</span><input aria-labelledby=label>
<span hidden id=hidden-label>Hidden referenced</span><button aria-labelledby=hidden-label></button>
<div contenteditable=true>Draft</div><output id=result>NONE</output>
<section id=row data-record=A><span id=row-label>Record A</span>
<button id=row-action onclick="document.querySelector('#result').textContent=this.parentElement.dataset.record">Details</button></section>'''

async def main():
    async def serve(reader, writer):
        try:
            try:
                await reader.readuntil(b'\r\n\r\n')
            except asyncio.IncompleteReadError:
                return
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: '
                         + str(len(PAGE)).encode() + b'\r\nConnection: close\r\n\r\n' + PAGE)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    service = BrowserService(ROOT/'owned-profile-artifacts')
    try:
        opened = await service.action('probe', BrowserAction(action='open', url=
            f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'))
        assert opened['success'], opened
        run = service.runs['probe']
        observation = (await service.action('probe', BrowserAction(action='observe')))['observation']
        chosen = next(e for e in observation['elements'] if e['name'] == 'Chosen')
        accessible = [{k:e.get(k) for k in ('ref','tag','role','name','disabled','editable')}
                      for e in observation['elements']]
        ax = await run.session._internal.client.send('Accessibility.getFullAXTree')
        native_names=[{'role':n.get('role',{}).get('value'), 'name':n.get('name',{}).get('value')}
            for n in ax.get('nodes',[]) if n.get('name',{}).get('value')
            in {'Continue','Hidden referenced'}]
        tampering = await evaluate(run.session._internal.client, '''(()=>{
          const state=window.__deepseekObservation, e=document.querySelector('#other');
          const chosen=[...state.refs].find(([ref,v])=>v.name==='Chosen')[0];
          const r=e.getBoundingClientRect();
          state.refs.set(chosen,{element:e,name:state.name(e),role:e.getAttribute('role')||e.tagName.toLowerCase(),box:[r.x,r.y,r.width,r.height]});
          return {shared_world_state_visible:!!state, public_fixture_ref_rebound:true};
        })()''')
        result = await service.action('probe', BrowserAction(action='click',
            observation_id=observation['observation_id'], ref=chosen['ref']), require_observation=True)
        actual = await evaluate(run.session._internal.client, "document.querySelector('#result').textContent")
        fresh = (await service.action('probe', BrowserAction(action='observe')))['observation']
        row_ref = next(e for e in fresh['elements'] if e['name']=='Details')['ref']
        await evaluate(run.session._internal.client, '''(()=>{
          document.querySelector('#row').dataset.record='B';
          document.querySelector('#row-label').textContent='Record B';
          return true;
        })()''')
        row_result = await service.action('probe', BrowserAction(action='click',
            observation_id=fresh['observation_id'], ref=row_ref), require_observation=True)
        row_actual = await evaluate(run.session._internal.client, "document.querySelector('#result').textContent")
        report={'scope':'Owned localhost fixture only; no external sites, APIs or credentials',
                'tampering':tampering,'requested_name':'Chosen','actual_clicked':actual,
                'receipt':result.get('receipt'), 'accessible_elements':accessible,
                'native_ax_comparison':native_names,
                'finding_reproduced':actual=='OTHER',
                'recycled_row':{'observed_record':'A','actual_record':row_actual,
                    'same_button_node':True,'receipt':row_result.get('receipt'),
                    'finding_reproduced':row_actual=='B'}}
        (ROOT/'mainworld-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report, ensure_ascii=False))
    finally:
        await service.close_all()
        server.close()
        await server.wait_closed()

asyncio.run(main())
