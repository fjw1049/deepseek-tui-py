"""Real file/shell actions through the engine, with only the model scripted."""
import shlex
import sys

from deepseek_tui.engine.events import ToolResultEvent
from deepseek_tui.engine.turn import TurnOutcomeStatus
from deepseek_tui.policy.sandbox import ExecutionSandboxPolicy
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import ToolCall
from tests.engine.test_truncated_rounds import _allow, engine_for


async def test_successful_recovery_keeps_history_without_claiming_task_verification(tmp_path):
    script = "from pathlib import Path\nPath('result.txt').write_text('42')\n"
    engine, client = await engine_for(tmp_path, [
        ToolCall(id='probe', name='exec_shell', arguments={'command': 'exit 1'}),
        ToolCall(id='edit', name='write_file', arguments={'path': 'build.py', 'content': script}),
        ToolCall(id='run', name='exec_shell',
                 arguments={'command': f'{shlex.quote(sys.executable)} build.py'}),
        'Generated result.txt.',
    ])
    engine._handle_approval_flow = _allow
    # The test runner supplies isolation; no permission/network changes in product code.
    engine.tool_context.execution_sandbox_policy = ExecutionSandboxPolicy.external_sandbox()
    try:
        result = await engine._run_conversation(
            [Message.user('Generate the result')], 'test', 'sys', None,
        )
        assert result.outcome is TurnOutcomeStatus.SUCCESS
        assert len(client.requests) == 4  # no added model validator or recovery round
        assert (tmp_path / 'result.txt').read_text() == '42'
        assert result.task_outcome['status'] == 'partial'
        assert result.task_outcome['remaining'] == ['exec_shell exit 1']
        assert 'exit 1' in result.completion_note
        assert 'Unresolved tool failures' not in result.completion_note
    finally:
        await engine.shutdown_session()


async def test_deleted_file_recovery_completes_through_the_engine(tmp_path, monkeypatch):
    target = tmp_path / 'generated.txt'
    target.write_text('original')
    engine, client = await engine_for(tmp_path, [
        ToolCall(id='read', name='read_file', arguments={'path': target.name}),
        ToolCall(id='stale', name='write_file',
                 arguments={'path': target.name, 'content': 'replacement'}),
        ToolCall(id='missing', name='read_file', arguments={'path': target.name}),
        ToolCall(id='recreate', name='write_file',
                 arguments={'path': target.name, 'content': 'replacement'}),
        'Recreated the observed missing file.',
    ])
    stream = client.stream_chat_completion

    async def with_external_changes(request):
        if len(client.requests) == 1:
            target.write_text('changed by another writer')
        elif len(client.requests) == 2:
            assert target.read_text() == 'changed by another writer'
            target.unlink()
        async for event in stream(request):
            yield event

    monkeypatch.setattr(client, 'stream_chat_completion', with_external_changes)
    engine._handle_approval_flow = _allow
    try:
        result = await engine._run_conversation(
            [Message.user('Update the generated file')], 'test', 'sys', None,
        )
        assert result.outcome is TurnOutcomeStatus.SUCCESS
        assert target.read_text() == 'replacement'
        assert len(client.requests) == 5
        results = {e.tool_call_id: e.success for e in engine.handle.drain_events()
                   if isinstance(e, ToolResultEvent)}
        assert results == {'read': True, 'stale': False, 'missing': False, 'recreate': True}
        assert result.task_outcome == {'status': 'completed_unverified', 'remaining': []}
    finally:
        await engine.shutdown_session()
