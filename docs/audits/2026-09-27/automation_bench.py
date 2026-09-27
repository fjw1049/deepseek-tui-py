"""Local read-path prototype comparison; not an end-to-end storage migration benchmark.

Run: PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/automation_bench.py
Uses synthetic data in a temporary directory. Setup/index writes excluded from timings.
"""
import json
import platform
import sqlite3
import statistics
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from deepseek_tui.tools.automation import AutomationManager, AutomationRunRecord, AutomationRunStatus


def median_ms(fn):
    fn()  # warm up
    samples = []
    for _ in range(7):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(samples), 3)


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="automation-bench-") as tmp:
        for count in (100, 1000, 5000):
            mgr = AutomationManager(Path(tmp) / str(count))
            runs = mgr.runs_dir / "job"
            runs.mkdir()
            db = sqlite3.connect(Path(tmp) / f"{count}.sqlite")
            db.execute("CREATE TABLE runs (created_at TEXT, pending INTEGER, payload TEXT)")
            db.execute("CREATE INDEX run_pending ON runs (pending, created_at DESC)")
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            for i in range(count):
                stamp = (start + timedelta(seconds=i)).isoformat()
                run = AutomationRunRecord(id=str(i), automation_id="job", scheduled_for=stamp,
                    created_at=stamp, status=AutomationRunStatus.RUNNING if i == 0 else AutomationRunStatus.COMPLETED,
                    delivery_done=i != 0, task_id="t")
                data = json.dumps(run.to_dict())
                (runs / f"{i}.json").write_text(data)
                db.execute("INSERT INTO runs VALUES (?, ?, ?)", (stamp, int(i == 0), data))
            db.commit()
            read_count = 0
            original_read = Path.read_text
            def counted_read(path, *args, **kwargs):
                nonlocal read_count
                read_count += 1
                return original_read(path, *args, **kwargs)
            with patch.object(Path, "read_text", counted_read):
                mgr.list_runs("job", limit=100)
            def json_pending():
                return [r for r in mgr.list_runs("job") if r.status == AutomationRunStatus.RUNNING]
            def sqlite_pending():
                rows = db.execute("SELECT payload FROM runs WHERE pending=1 ORDER BY created_at DESC").fetchall()
                return [AutomationRunRecord.from_dict(json.loads(row[0])) for row in rows]
            assert [r.id for r in json_pending()] == [r.id for r in sqlite_pending()] == ["0"]
            results.append(dict(records=count, reads_with_limit_100=read_count,
                current_latest100_ms=median_ms(lambda: mgr.list_runs("job", limit=100)),
                json_all_pending_ms=median_ms(json_pending),
                sqlite_indexed_pending_ms=median_ms(sqlite_pending)))
            db.close()
    print(json.dumps(dict(python=platform.python_version(), platform=platform.system(),
                         repeats=7, results=results), indent=2))


if __name__ == "__main__":
    main()
