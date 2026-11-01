"""Read-only source review probes against disposable loopback Chrome pages."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from octop_browser.record.models import SemanticStep, StepsDocument
from deepseek_tui.browser import workflows
from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.service import BrowserAction, BrowserService


ROOT = Path('/private/tmp/browser-final-audit-20261012/replay')
PAGE = b"""<!doctype html><meta charset=utf-8><title>probe</title>
<button id=save onclick='window.clicks++'>Save</button>
<input id=q aria-label=Name value=old>
<script>window.clicks=0</script>"""


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
    service = BrowserService(ROOT / 'probe-artifacts')
    results = []
    try:
        await service.action('probe', BrowserAction(action='open', url=
            f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/'))
        run = service.runs['probe']
        client = run.session._internal.client
        doc = StepsDocument(recordingId='rec_probe', inputs=[{'name': 'name', 'required': True}],
            steps=[SemanticStep(id='1', kind='click', target={'selectorCandidates': ['#save']}),
                   SemanticStep(id='2', kind='fill', value='{{name}}',
                                target={'selectorCandidates': ['#q']})])
        await service.control('probe', 'user')
        with patch.object(workflows, 'read_workflow', return_value=doc):
            await workflows.start_replay(service, 'probe', 'rec_probe', {'name': 'x' * 9000})
            await asyncio.wait_for(run.demo_task, timeout=20)
        results.append({'name': 'oversized_later_input', 'evidence': 'real_loopback_chrome',
            'status': run.demo_status, 'error': run.error, 'earlier_clicks':
            await evaluate(client, 'window.clicks')})
        await evaluate(client, "document.querySelector('#q').value='old';"
                       "setTimeout(()=>document.querySelector('#q').value='new',350);true")
        start = asyncio.get_running_loop().time()
        try:
            await workflows._verify(service, run, {'type': 'input_value_equals',
                                                 'selector': '#q', 'value': 'new'})
            initial = 'passed'
        except ValueError:
            initial = 'failed'
        elapsed = asyncio.get_running_loop().time() - start
        await asyncio.sleep(.5)
        await workflows._verify(service, run, {'type': 'input_value_equals',
                                             'selector': '#q', 'value': 'new'})
        results.append({'name': 'async_input_verification', 'evidence': 'real_loopback_chrome',
                        'initial': initial, 'elapsed_ms': round(elapsed * 1000),
                        'after_condition_reached': 'passed'})
        from deepseek_tui.browser.skills import preview_skill
        await evaluate(client, "document.body.innerHTML='<div id=editor contenteditable></div>';"
                       "document.querySelector('#editor').focus();true")
        await service.control('probe', 'user')
        started = await workflows.start_recording(service, 'probe')
        recorder = run.recorder
        await client.send('Input.insertText', {'text': 'PRIVATE_CONTENTEDITABLE_SENTINEL'})
        await asyncio.sleep(.5)
        await workflows.finish_recording(run)
        doc = workflows.read_workflow(service, 'probe', started['recordingId'])
        raw = json.dumps(recorder.store.read_events(started['recordingId']))
        semantic = doc.model_dump_json()
        skill = preview_skill(service, 'probe', started['recordingId'], 'test-editor', 'Test editor')
        results.append({'name': 'mask_all_contenteditable_target_metadata',
                        'evidence': 'real_loopback_chrome', 'raw_event_contains_private_text':
                        'PRIVATE_CONTENTEDITABLE_SENTINEL' in raw,
                        'semantic_document_contains_private_text':
                        'PRIVATE_CONTENTEDITABLE_SENTINEL' in semantic,
                        'exported_skill_contains_private_text':
                        'PRIVATE_CONTENTEDITABLE_SENTINEL' in skill['content'],
                        'recorded_value_is_masked': any(s.value == '{{sensitive_value}}'
                                                     for s in doc.steps)})
    finally:
        await service.close_all()
        server.close()
        await server.wait_closed()
    (ROOT / 'probe-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2))


asyncio.run(main())
