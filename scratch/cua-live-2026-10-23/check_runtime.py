"""Real installed LCU integration; no model calls or desktop mutations."""
import asyncio
import json
from pathlib import Path

from deepseek_tui.config.models import CuaConfig
from deepseek_tui.cua.approval import approval_question, approval_response
from deepseek_tui.cua.session import CuaSession
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.tools.registry import ToolContext

ROOT = Path(__file__).resolve().parent

async def main():
    report = {}
    engine = Engine(handle=EngineHandle(), client=None, tool_context=ToolContext(ROOT))
    approval_seen = asyncio.Event()
    async def approve(params):
        q = approval_question(params)
        if not q:
            return {'action': 'cancel'}
        approval_seen.set()
        response = await engine._await_user_input_raw('live-permission', [q], purpose='cua_permission')
        return approval_response(params, response)
    session = CuaSession(CuaConfig(enabled=True), ROOT, 'acceptance-20261023', approve)
    engine._cua_session = session
    task = None
    try:
        await session.connect()
        report['real_tool_catalog'] = [x['name'] for x in session.descriptors]
        assert {'js', 'js_reset'} <= set(report['real_tool_catalog'])
        print(json.dumps(report), flush=True)
        # Request permission, but never grant or mutate the application.
        task = asyncio.create_task(session.call('js', {
            'code': 'var acceptanceApp = await cua.getApp("com.apple.TextEdit");',
            'title': 'Acceptance: cancel permission before app access',
        }, 'acceptance-turn', 'permission-probe'))
        waiter = asyncio.create_task(approval_seen.wait())
        done, _ = await asyncio.wait({task, waiter}, timeout=40, return_when=asyncio.FIRST_COMPLETED)
        if waiter in done:
            # Wait for the actual host event, then close its real bridge while pending.
            event = await asyncio.wait_for(engine.handle._event_queue.get(), 5)
            assert type(event).__name__ == 'UserInputRequiredEvent'
            await session.close()
            await asyncio.gather(task, return_exceptions=True)
            event = await asyncio.wait_for(engine.handle._event_queue.get(), 5)
            assert type(event).__name__ == 'UserInputResolvedEvent' and event.response is None
            assert not engine.handle.pending_user_inputs
            report['real_permission_cancel_resolved'] = True
        elif task in done:
            result = task.result()
            report['permission_probe'] = 'no prompt: already permitted or runtime declined'
            report['permission_probe_is_error'] = bool(result.get('isError'))
        else:
            report['permission_probe'] = 'timed out without requesting access'
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        await session.close()
        assert session.process is None and session.lease.fd is None
        report['process_and_lock_released'] = True
        await session.connect()
        report['reconnect_catalog'] = [x['name'] for x in session.descriptors]
        # Exercise the real generic information handoff using a live connection.
        ask = asyncio.create_task(engine._await_user_input('live-question', {
            'questions': [{'id': 'next', 'header': 'Next', 'question': 'Continue the isolated test?'}]
        }))
        async with asyncio.timeout(30):
            while 'live-question' not in engine.handle.pending_user_inputs:
                await asyncio.sleep(.05)
        assert session.process is None and session.lease.fd is None
        engine.handle.pending_user_inputs['live-question'].set_result({'answers': []})
        answer = await ask
        assert 'CUA session reset' in json.loads(answer.content)['instructions']
        report['real_information_handoff_closed_connection'] = True
        report['handoff_returns_valid_json_and_reset_notice'] = True
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await session.close()
        (ROOT / 'runtime-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report), flush=True)

asyncio.run(main())
