"""Real LCU error/reset integration, without desktop input or app grants."""
import asyncio
import json
from pathlib import Path
from deepseek_tui.config.models import CuaConfig
from deepseek_tui.cua.session import CuaSession
from deepseek_tui.cua.tools import CuaTool
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.task_delivery import FinishTaskTool, TaskDelivery

ROOT = Path(__file__).resolve().parent

async def main():
    report = {}
    session = CuaSession(CuaConfig(enabled=True), ROOT, 'live-failed-completion')
    try:
        await session.connect()
        descriptors = {d['name']: d for d in session.descriptors}
        delivery = TaskDelivery(active=True, evidence={'tool:before'})
        context = ToolContext(ROOT, metadata={
            'task_delivery': delivery, 'cua_turn_id': 'failure-check', 'cua_call_id': 'docs',
        })
        js = CuaTool(session, descriptors['js'])
        docs = await js.execute({'code': 'await cua.rewriteDocumentation();', 'title': 'Read runtime API'}, context)
        assert docs.success, docs.content[:300]
        report['real_runtime_documentation_loaded'] = True
        context.metadata['cua_call_id'] = 'intentional-error'
        error = await js.execute({'code': 'throw new Error("ACCEPTANCE_INTENTIONAL_ERROR");', 'title': 'Test failure reporting'}, context)
        assert not error.success and 'ACCEPTANCE_INTENTIONAL_ERROR' in error.content
        report['real_js_error_received'] = True
        args = dict(status='completed', answer='Should be rejected', evidence=['tool:before'], remaining=[])
        async def assert_rejected():
            try:
                await FinishTaskTool().execute(args, context)
            except ToolError as exc:
                assert 'CUA outcome needs verification' in str(exc)
                return
            raise AssertionError('Old evidence incorrectly accepted')
        await assert_rejected()
        report['old_evidence_rejected'] = True
        context.metadata['cua_call_id'] = 'reset'
        reset = await CuaTool(session, descriptors['js_reset']).execute({}, context)
        assert reset.success and reset.metadata['task_evidence'] is False
        await assert_rejected()
        report['real_reset_not_completion_evidence'] = True
    finally:
        await session.close()
        report['process_and_lock_released'] = session.process is None and session.lease.fd is None
        (ROOT / 'failure-result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)

asyncio.run(main())
