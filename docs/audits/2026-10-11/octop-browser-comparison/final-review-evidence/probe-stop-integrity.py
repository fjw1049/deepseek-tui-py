"""Fault injection on disposable localhost recording; production sources unchanged."""
import asyncio
import json
from pathlib import Path

from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.service import BrowserAction, BrowserService
from deepseek_tui.browser.workflows import (
    assert_capture_complete,
    finish_recording,
    start_recording,
)

ROOT = Path('/private/tmp/browser-final-audit-20261012')
PAGE = b'<!doctype html><title>Stop integrity</title><input id=q aria-label=Draft>'


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
    service = BrowserService(ROOT / 'stop-artifacts')
    try:
        await service.action('stop', BrowserAction(action='open', url=
            f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/'))
        run = service.runs['stop']
        client = run.session._internal.client
        await service.control('stop', 'user')
        started = await start_recording(service, 'stop')
        recorder = run.recorder
        await evaluate(client, "document.querySelector('#q').focus();true")
        await client.send('Input.insertText', {'text': 'TEST_PRIVATE_DRAFT'})
        original = recorder.client.send
        failures = 0

        async def reject_dispose(method, params=None, **kwargs):
            nonlocal failures
            if method == 'Runtime.evaluate' and '__deepseekRecorder?.dispose()' in str(params):
                failures += 1
                return {'exceptionDetails': {'text': 'Injected stop flush failure'}}
            return await original(method, params, **kwargs)

        recorder.client.send = reject_dispose
        result = await finish_recording(run)
        events = recorder.store.read_events(started['recordingId'])
        manifest = recorder.store.read_manifest(started['recordingId'])
        assert_capture_complete(service, 'stop', started['recordingId'])
        report = {
            'evidence': 'real_localhost_chrome_with_injected_Runtime_exceptionDetails',
            'fault': 'stop dispose did not flush pending input',
            'injected_failures': failures,
            'finish_returned_success': bool(result),
            'manifest_status': manifest.status,
            'input_events': sum(e['kind'] == 'input' for e in events),
            'capture_warnings': len(recorder.capture_warnings),
            'completeness_gate_accepted': True,
            'private_text_in_events': 'TEST_PRIVATE_DRAFT' in str(events),
        }
        (ROOT / 'stop-integrity.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        await service.close_all()
        server.close()
        await server.wait_closed()


asyncio.run(main())
