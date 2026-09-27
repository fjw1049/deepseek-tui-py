"""Task persistence characterization using temporary stores and fake executors.

PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/tasks_probe.py
No LLM, network, or shell calls. Assertions describe current defects.
"""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from deepseek_tui.config.models import Config
from deepseek_tui.tools.task import TaskManager, TaskManagerConfig, NewTaskRequest, TaskExecutionResult, TaskStatus, ExecutionTask
from deepseek_tui.tools.task.store import _load_state, _task_record_to_dict
from deepseek_tui.tools.durable_transcript import load_transcript, task_transcript_path
from deepseek_tui.engine.dispatch import _run_task_engine_turn


def manager(root, executor=None, config=None):
    return TaskManager(TaskManagerConfig(data_dir=root, default_workspace=root.parent, config=config), executor=executor)


async def probe(root):
    out = {}
    # A second manager mistakes another live manager's task for crash recovery.
    started, twice, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    seen = []
    async def execute(task, cancel):
        seen.append(task.id)
        started.set()
        if len(seen) == 2:
            twice.set()
        await release.wait()
        return TaskExecutionResult(summary='mock')
    first, second = manager(root/'shared', execute), manager(root/'shared', execute)
    await first.start()
    try:
        record = await first.add_task(NewTaskRequest(prompt='one operation'))
        await asyncio.wait_for(started.wait(), 2)
        await second.start()
        await asyncio.wait_for(twice.wait(), 2)
        out['same_task_executed_by_two_managers'] = seen
        assert seen == [record.id, record.id]
    finally:
        release.set()
        await first.shutdown()
        await second.shutdown()

    # Failed enqueue leaves a runnable in-memory request despite raising.
    m = manager(root/'enqueue')
    with patch.object(m, '_persist_task_locked', side_effect=OSError('synthetic disk failure')):
        try:
            await m.add_task(NewTaskRequest(prompt='caller saw failure'))
        except OSError:
            pass
    claimed = await m._pop_next_task()
    out['failed_enqueue_still_claimable'] = claimed is not None
    assert claimed is not None

    # Disk failure during claim escapes the worker loop entirely.
    m = manager(root/'worker')
    await m.add_task(NewTaskRequest(prompt='not executed'))
    with patch.object(m, '_persist_all_locked', side_effect=OSError('synthetic disk failure')):
        worker = asyncio.create_task(m._worker_loop())
        result = (await asyncio.gather(worker, return_exceptions=True))[0]
    out['worker_exits_on_storage_error'] = type(result).__name__
    assert isinstance(result, OSError)

    # Corrupt nested data isn't covered by the loader's exception boundary.
    m = manager(root/'corrupt')
    rec = await m.add_task(NewTaskRequest(prompt='valid'))
    raw = _task_record_to_dict(rec)
    raw['checklist'] = ['bad nested type']
    (m._tasks_dir/f'{rec.id}.json').write_text(json.dumps(raw))
    try:
        _load_state(m._tasks_dir, m._queue_path)
    except Exception as exc:
        out['malformed_record_load_exception'] = type(exc).__name__
    assert out['malformed_record_load_exception'] == 'AttributeError'

    # Cache eviction changes user-visible list/count and permits ambiguous prefixes.
    m = manager(root/'catalog')
    with patch.object(m, '_persist_all_locked'):
        records = [await m.add_task(NewTaskRequest(prompt=f'item {i}')) for i in range(51)]
    m._queue.clear()
    for i, rec in enumerate(records):
        rec.status = TaskStatus.COMPLETED
        rec.ended_at = f'2026-01-01T00:00:{i:02d}+00:00'
    m._persist_all_locked()
    m._evict_terminal_tasks_locked()
    before = len(await m.list_tasks())
    await m.get_task(records[0].id)
    after = len(await m.list_tasks())
    out['catalog_changes_after_read'] = {'before':before,'after':after,'disk_records':len(list(m._tasks_dir.glob('*.json')))}
    assert (before,after)==(50,51)
    # Keep exactly one cached candidate while all records still exist on disk.
    m._tasks = {records[0].id:records[0]}
    out['ambiguous_prefix_returns_cached_record'] = (await m.get_task('task_')).id == records[0].id
    assert out['ambiguous_prefix_returns_cached_record']

    # Successful execution drops detail field.
    async def detail_executor(task,cancel):
        return TaskExecutionResult(summary='short', detail='long durable result')
    m = manager(root/'detail', detail_executor)
    record = await m.add_task(NewTaskRequest(prompt='detail'))
    await m._run_task(*await m._pop_next_task())
    out['result_detail_lost'] = record.result_detail_path is None and not record.artifacts
    assert out['result_detail_lost']

    # A snapshot is memory-only; restart uses the current manager config.
    m = manager(root/'config', config=Config(sandbox_mode='read-only'))
    record = await m.add_task(NewTaskRequest(prompt='scope',config=Config(sandbox_mode='read-only')))
    restored = manager(root/'config', config=Config(sandbox_mode='workspace-write'))
    restored._tasks, restored._queue = _load_state(restored._tasks_dir, restored._queue_path)
    out['restart_uses_new_config'] = (await restored._pop_next_task())[1].config.sandbox_mode
    assert out['restart_uses_new_config'] == 'workspace-write'

    # Transcript schema isn't checked; semantic corruption can raise after init.
    path = root/'future.json'
    path.write_text(json.dumps({'schema_version':999,'owner_id':'x','messages':[]}))
    out['future_transcript_version_accepted'] = load_transcript(path).schema_version
    assert out['future_transcript_version_accepted'] == 999
    data = root/'hydrate'
    path = task_transcript_path(data,'task_probe')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'cursor':{'steps_taken':'invalid'}}))
    client = SimpleNamespace(close=AsyncMock())
    runtime = SimpleNamespace(context=SimpleNamespace(trust_mode=False), shutdown=AsyncMock())
    engine = SimpleNamespace(tool_context=SimpleNamespace(trust_mode=False, active_task_id=None, metadata={},subagent_manager=None),shutdown=AsyncMock())
    task = ExecutionTask(id='task_probe',prompt='mock',model='mock',workspace=str(root),mode_label='agent',allow_shell=False,trust_mode=False,auto_approve=False,config=Config(),task_manager=SimpleNamespace(data_dir=lambda:data))
    with patch('deepseek_tui.client.factory.build_llm_client', return_value=client), \
         patch('deepseek_tui.tools.runtime.create_tool_runtime', AsyncMock(return_value=runtime)), \
         patch('deepseek_tui.engine.orchestrator.Engine.create', AsyncMock(return_value=engine)):
        try:
            await _run_task_engine_turn(task,asyncio.Event())
        except ValueError:
            pass
    out['hydrate_failure_cleanup_calls'] = {'client':client.close.await_count,'runtime':runtime.shutdown.await_count,'engine':engine.shutdown.await_count}
    assert all(n==0 for n in out['hydrate_failure_cleanup_calls'].values())
    return out


async def main():
    with tempfile.TemporaryDirectory(prefix='tasks-audit-') as tmp:
        print(json.dumps(await probe(Path(tmp)), indent=2))


if __name__=='__main__':
    asyncio.run(main())
