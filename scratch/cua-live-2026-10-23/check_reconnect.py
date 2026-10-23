"""Real bridge process death and idle pause, without any desktop UI input."""
import asyncio
import json
from pathlib import Path
from deepseek_tui.config.models import CuaConfig
from deepseek_tui.cua.session import CuaSession
from deepseek_tui.cua.tools import CuaTool
from deepseek_tui.tools.registry import ToolContext, ToolError

ROOT = Path(__file__).resolve().parent

async def main():
    report = {}
    pause = asyncio.Event()
    session = CuaSession(CuaConfig(enabled=True), ROOT, 'live-reconnect-20261023')
    try:
        await session.connect()
        tool = CuaTool(session, next(d for d in session.descriptors if d['name'] == 'js'), [pause])
        context = ToolContext(ROOT, metadata={'cua_turn_id': 'live-reconnect', 'cua_call_id': 'initial'})
        result = await tool.execute({'code': 'await cua.rewriteDocumentation();'}, context)
        assert result.success
        original_segment = session.runtime_turn_id
        context.metadata['cua_call_id'] = 'binding'
        result = await tool.execute({'code': 'var acceptanceOldBinding = 23; nodeRepl.write(acceptanceOldBinding);'}, context)
        assert result.success and '23' in result.content
        process = session.process
        process.terminate()
        await asyncio.wait_for(process.wait(), 10)
        await asyncio.wait_for(session.reader, 10)
        context.metadata['cua_call_id'] = 'after-crash'
        try:
            await tool.execute({'code': 'nodeRepl.write("SHOULD_NOT_RUN");'}, context)
        except ToolError as exc:
            assert 'bindings are gone' in str(exc) and 'observe again' in str(exc)
            report['first_call_after_bridge_death_refused'] = True
        else:
            raise AssertionError('Potential action was executed after bridge death')
        context.metadata['cua_call_id'] = 'reinitialize'
        result = await tool.execute({'code': 'await cua.rewriteDocumentation();'}, context)
        assert result.success
        assert session.runtime_turn_id != original_segment
        report['new_runtime_segment_on_reconnect'] = True
        context.metadata['cua_call_id'] = 'check-binding'
        result = await tool.execute({'code': 'nodeRepl.write(typeof acceptanceOldBinding);'}, context)
        assert result.success and 'undefined' in result.content
        report['old_javascript_binding_discarded'] = True
        monitor = session._monitor
        pause.set()
        await asyncio.wait_for(monitor, 20)
        assert session.process is None and session.lease.fd is None
        report['idle_pause_releases_process_and_lock'] = True
    finally:
        await session.close()
        (ROOT / 'reconnect-result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)

asyncio.run(main())
