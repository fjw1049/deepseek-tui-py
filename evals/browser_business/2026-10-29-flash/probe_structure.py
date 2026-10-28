import asyncio,tempfile,threading,json
from pathlib import Path
from http.server import ThreadingHTTPServer
from run_case import Handler
from deepseek_tui.browser.service import BrowserService,BrowserAction
from deepseek_tui.browser.observation import evaluate
async def main():
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 root=Path(tempfile.mkdtemp());s=BrowserService(root/'artifacts',profile_root=root/'profile')
 try:
  await s.action('t',BrowserAction(action='open',url=f'http://127.0.0.1:{server.server_port}/weekly'))
  async def act(action,**kw):
   o=(await s.action('t',BrowserAction(action='observe',level='full')))['observation']
   return await s.action('t',BrowserAction(action=action,observation_id=o['observation_id'],**kw))
  await act('click',selector='#editor');await act('press',key='Meta+ArrowDown');await act('press',key='Enter')
  for stage in ['empty_li','heading','typed']:
   if stage=='heading':await act('click',selector='header button:first-of-type')
   if stage=='typed':await act('type',text='2026年第43周')
   o=(await s.action('t',BrowserAction(action='observe',selector='#editor',include_editable=True)))['observation']
   html=await evaluate(s.runs['t'].session._internal.client,'editor.innerHTML.slice(-400)')
   print(stage,html,o['editor'].get('current_block'))
 finally:await s.close_all();server.shutdown()
asyncio.run(main())
