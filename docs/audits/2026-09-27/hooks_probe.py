"""Offline characterization; real hooks only write temporary files and terminate.

PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/hooks_probe.py
Assertions describe current behavior, including defects. No model/network calls.
"""
import asyncio
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from deepseek_tui.config.models import Config, HooksConfig, LifecycleHookEntry
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.integrations.hooks import (
    HookContext, HookExecutor, HookResult, _run_shell, _base_env,
    aggregate_hook_decision, build_hook_dispatcher,
)
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolContext, ToolRegistry, ToolResult
from deepseek_tui.tools.file import ReadFileTool
from deepseek_tui.tools.subagent.loop import _execute_subagent_tool


async def probes(root):
    out = {}
    # Finite descendants: even a missing cleanup can leave no persistent job.
    script = root / 'finite.py'
    script.write_text('import pathlib,sys,time\ntime.sleep(0.25)\npathlib.Path(sys.argv[1]).write_text("done")\n')
    def command(marker):
        return f'{shlex.quote(sys.executable)} {shlex.quote(str(script))} {shlex.quote(str(marker))} & wait'
    marker = root / 'after-timeout'
    try:
        await _run_shell(command(marker), timeout=0.05)
    except asyncio.TimeoutError:
        pass
    await asyncio.sleep(0.35)
    out['descendant_completed_after_timeout'] = marker.exists()
    assert marker.exists()

    # Deterministic cancellation check: inspect kill/reap contract without a child.
    started = asyncio.Event()
    async def communicate(**kwargs):
        started.set()
        await asyncio.Future()
    proc = SimpleNamespace(communicate=communicate, kill=AsyncMock(), wait=AsyncMock())
    with patch('deepseek_tui.integrations.hooks.asyncio.create_subprocess_shell', AsyncMock(return_value=proc)):
        task = asyncio.create_task(_run_shell('mock', timeout=10))
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    out['cancel_cleanup'] = {'kill_calls': proc.kill.call_count, 'wait_calls': proc.wait.call_count}
    assert proc.kill.call_count == proc.wait.call_count == 0

    cfg = HooksConfig(hooks=[
        LifecycleHookEntry(event='tool_call_before', command='exit 1', name='broken', continue_on_error=False),
        LifecycleHookEntry(event='tool_call_before', command='exit 2', name='deny'),
    ])
    executor = HookExecutor(cfg, root)
    results = await executor.execute('tool_call_before')
    out['failed_hook_skips_deny'] = {'executed': [r.name for r in results], 'blocked': aggregate_hook_decision(results).blocked}
    assert len(results) == 1 and not aggregate_hook_decision(results).blocked

    disabled = build_hook_dispatcher(Config(hooks=HooksConfig(enabled=False, stdout=True, webhook_urls=['https://example.invalid'])))
    out['disabled_dispatcher_sinks'] = [type(s).__name__ for s in disabled.sinks]
    assert len(disabled.sinks) == 2  # Construct only; no stdout or network emission.

    # Exercise the real tool wrapper; replace actual tool dispatch only.
    gate = ToolExecutionMixin()
    gate.tool_context = ToolContext(working_directory=root)
    gate.session_messages = []
    gate._lifecycle_hook_context = lambda **kw: HookContext(tool_name=kw['tool_name'], tool_args=json.dumps(kw['tool_args']))
    gate._accrue_child_token_cost_from_metadata = lambda _: None
    gate._execute_single_tool_impl = AsyncMock(return_value=ToolResult(success=False, content='mock', metadata={'returncode': 7}))
    seen = []
    async def capture(event, ctx):
        seen.append((event, ctx.tool_name, ctx.tool_exit_code))
        return []
    gate._run_lifecycle_hook = capture
    call = ToolCall(id='probe', name='task_shell_start', arguments={'command': 'echo mock'})
    await gate._execute_single_tool(call, [{'type':'function','function':{'name':'exec_shell'}}], 'mock')
    out['hook_sees_legacy_name_and_missing_exit_code'] = seen
    assert seen[0][1] == 'task_shell_start' and seen[1][2] is None

    # Real child tool entry never calls the executor's pre/post hooks.
    child_executor = SimpleNamespace(execute=AsyncMock(), has_hooks_for_event=lambda _: True)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.execute = AsyncMock(return_value=ToolResult(success=True, content='mock'))
    runtime = SimpleNamespace(config=SimpleNamespace(approval_policy='auto'), hook_executor=child_executor)
    await _execute_subagent_tool(registry, ToolContext(working_directory=root), tool_name='read_file',
        tool_input={'path':'x'}, auto_approve=True, runtime=runtime)
    out['child_hook_calls'] = child_executor.execute.await_count
    assert child_executor.execute.await_count == 0 and registry.execute.await_count == 1

    # Claimed dialect changes names, but native file arguments remain native.
    payload = HookContext(tool_name='write_file', tool_args='{"path":"x","content":"v"}').to_stdin_payload('tool_call_before', 'claude')
    out['claude_write_payload'] = payload
    assert payload['tool_name'] == 'Write' and 'file_path' not in payload['tool_input']
    unknown = LifecycleHookEntry(event='tool_call_before', command='true', condition={'type':'tool_nam','name':'other'})
    out['unknown_condition_matches'] = executor._matches_condition(unknown, HookContext(tool_name='read_file'))
    assert out['unknown_condition_matches']
    out['default_overrides_entry_timeout'] = HookExecutor(HooksConfig(default_timeout_secs=60), root)._timeout(LifecycleHookEntry(event='x', command='true', timeout_secs=1))
    assert out['default_overrides_entry_timeout'] == 60
    with patch.dict(os.environ, {'AUDIT_FAKE_API_KEY':'synthetic-only'}):
        out['hook_inherits_synthetic_secret'] = _base_env().get('AUDIT_FAKE_API_KEY') == 'synthetic-only'
    large = HookContext(tool_args=json.dumps({'content':'x'*200_000}))
    out['unbounded_tool_args_env_length'] = len(large.to_env_vars()['DEEPSEEK_TOOL_ARGS'])
    # Modest 1 MiB, proves result buffering lacks a cap without stressing memory.
    code = 'import sys; sys.stdout.write("x"*1048576)'
    result = await HookExecutor(HooksConfig(hooks=[LifecycleHookEntry(event='session_start', command=f'{shlex.quote(sys.executable)} -c {shlex.quote(code)}')]), root).execute('session_start')
    out['retained_stdout_and_context_bytes'] = [len(result[0].stdout), len(result[0].additional_context)]
    assert out['retained_stdout_and_context_bytes'] == [1048576,1048576]
    return out


async def main():
    with tempfile.TemporaryDirectory(prefix='hooks-audit-') as tmp:
        print(json.dumps(await probes(Path(tmp)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
