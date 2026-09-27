"""Enqueue-only persistence prototypes: full JSON, dirty JSON, SQLite transaction.

Run: PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/tasks_compare.py
Not production implementations; measures local writes, not crash guarantees.
"""
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from unittest.mock import patch
from deepseek_tui.tools.task import TaskManager,TaskManagerConfig,NewTaskRequest
from deepseek_tui.tools.task.store import _task_record_to_dict
from deepseek_tui.utils import write_json_atomic


async def run(root, mode, count):
    m = TaskManager(TaskManagerConfig(data_dir=root, default_workspace=root.parent))
    writes = 0
    sql = None
    def counted(path,data):
        nonlocal writes
        writes += 1
        write_json_atomic(path,data)
    def dirty():
        # Enqueue-only prototype: only the just-created record is dirty.
        m._persist_task_locked(m._tasks[m._queue[-1]])
        m._persist_queue_locked()
    if mode == 'sqlite_transaction':
        root.mkdir()
        sql = sqlite3.connect(root/'tasks.db')
        sql.execute('PRAGMA journal_mode=WAL')
        sql.execute('PRAGMA synchronous=FULL')
        sql.execute('CREATE TABLE task(id TEXT PRIMARY KEY, position INTEGER, data TEXT)')
        def transaction():
            nonlocal writes
            record = m._tasks[m._queue[-1]]
            with sql:
                sql.execute('INSERT INTO task VALUES(?,?,?)',(record.id,len(m._queue),json.dumps(_task_record_to_dict(record),ensure_ascii=False)))
            writes += 1
        m._persist_all_locked = transaction
    elif mode == 'dirty_json':
        m._persist_all_locked = dirty
    durations = []
    start = time.perf_counter()
    with patch('deepseek_tui.tools.task.manager.write_json_atomic',counted):
        for i in range(count):
            t = time.perf_counter()
            await m.add_task(NewTaskRequest(prompt=f'item {i} '+ 'x'*100))
            durations.append(time.perf_counter()-t)
    elapsed = time.perf_counter()-start
    if sql:
        assert sql.execute('SELECT COUNT(*) FROM task').fetchone()[0] == count
        sql.close()
    else:
        assert len(list(m._tasks_dir.glob('*.json'))) == count
        assert len(json.loads(m._queue_path.read_text())['queue']) == count
    return dict(mode=mode,count=count,ms=round(elapsed*1000,2),max_enqueue_ms=round(max(durations)*1000,2),atomic_file_writes_or_sql_commits=writes)


async def main():
    with tempfile.TemporaryDirectory(prefix='task-store-compare-') as tmp:
        rows=[]
        for count in (20,60):
            for mode in ('full_json','dirty_json','sqlite_transaction'):
                rows.append(await run(Path(tmp)/f'{mode}-{count}',mode,count))
        print(json.dumps(rows,indent=2))


if __name__=='__main__':
    asyncio.run(main())
