"""Real local files, durable workers and credential migration boundaries."""

import asyncio
import json

import pytest
from cryptography.fernet import Fernet

from deepseek_tui.automation.credential_migration import migrate_run_credentials
from deepseek_tui.automation.delivery import DeliveryConfig
from deepseek_tui.state.secrets import load_delivery_secret
from deepseek_tui.tools.file import WriteFileTool
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.search import FileSearchTool, GrepFilesTool
from deepseek_tui.tools.task import (
    NewTaskRequest,
    TaskExecutionResult,
    TaskManager,
    TaskManagerConfig,
)
from deepseek_tui.tools.task.tools import TaskOutputTool
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpointStore


async def test_repeated_polling_waits_without_blocking_worker(tmp_path):
    release = asyncio.Event()
    started = asyncio.Event()

    async def execute(task, cancel):
        started.set()
        await release.wait()
        return TaskExecutionResult(summary="done")

    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path), executor=execute
    )
    await manager.start()
    try:
        task = await manager.add_task(NewTaskRequest(prompt="wait"))
        await asyncio.wait_for(started.wait(), 2)
        context = ToolContext(working_directory=tmp_path, task_manager=manager)
        tool = TaskOutputTool()
        for _ in range(3):
            result = await tool.execute({"task_id": task.id}, context)
            assert "automatic_wait_ms" not in result.metadata
        result = await tool.execute({"task_id": task.id, "timeout_ms": 5}, context)
        assert result.metadata["timed_out"]
        assert result.metadata["automatic_wait_ms"] == 5
        context.active_task_id = "occupying-worker"
        result = await tool.execute({"task_id": task.id}, context)
        assert "automatic_wait_ms" not in result.metadata
        context.active_task_id = None
        waiter = asyncio.create_task(tool.execute({"task_id": task.id}, context))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not (await manager.get_task(task.id)).status.is_terminal()
        release.set()
        result = await tool.execute(
            {"task_id": task.id, "block": True, "timeout_ms": 2000}, context
        )
        assert result.metadata["status"] == "completed"
    finally:
        release.set()
        await manager.shutdown()


@pytest.mark.parametrize(
    "tool,args",
    [(GrepFilesTool(), {"pattern": "needle"}), (FileSearchTool(), {"pattern": "*.txt"})],
)
async def test_filtered_directories_reported_and_explicitly_searchable(tmp_path, tool, args):
    for name in ("dist", "build", "node_modules", "src"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "sample.txt").write_text("needle")
    context = ToolContext(working_directory=tmp_path)
    result = await tool.execute({**args, "path": "."}, context)
    assert result.metadata["skipped_default_dirs"] == 3
    assert "Skipped 3" in result.content
    result = await tool.execute({**args, "path": "dist"}, context)
    assert "sample.txt" in result.content
    assert result.metadata["skipped_default_dirs"] == 0


def test_migration_encrypts_backup_and_roundtrips_credentials(tmp_path):
    root = tmp_path / "automations"
    path = root / "runs" / "automation" / "old.json"
    path.parent.mkdir(parents=True)
    secret = "test-old-key-no-real-service"
    raw = {
        "id": "old",
        "delivery": {"mode": "wecom", "to": secret},
        "delivery_snapshot": {"config": {"mode": "wecom", "to": secret}, "summary": "body"},
        "delivery_error": f"HTTP 400 https://test.invalid/send?key={secret}",
    }
    original = json.dumps(raw).encode()
    path.write_bytes(original)
    assert migrate_run_credentials(root) == 1
    saved = json.loads(path.read_bytes())
    assert secret not in path.read_text()
    assert DeliveryConfig.from_mapping(saved["delivery"]).to == secret
    assert DeliveryConfig.from_mapping(saved["delivery_snapshot"]["config"]).to == secret
    backups = list((root / "state" / "credential-backups").glob("*.json"))
    assert len(backups) == 1 and secret not in backups[0].read_text()
    backup = json.loads(backups[0].read_bytes())
    assert (
        Fernet(load_delivery_secret(backup["key_ref"]).encode()).decrypt(
            backup["ciphertext"].encode()
        )
        == original
    )
    assert migrate_run_credentials(root) == 0
    assert json.loads(path.read_text()) == saved


def test_missing_credential_never_falls_back_to_default():
    with pytest.raises(ValueError, match="credential unavailable"):
        DeliveryConfig.from_mapping({"mode": "wecom", "credential_ref": "delivery_" + "0" * 64})


def test_migration_failure_preserves_source_and_retries(tmp_path, monkeypatch):
    import deepseek_tui.automation.credential_migration as migration

    root = tmp_path / "automation"
    path = root / "runs" / "a" / "r.json"
    path.parent.mkdir(parents=True)
    original = b'{"delivery":{"mode":"wecom","to":"local-test-key"}}'
    path.write_bytes(original)
    writer = migration.write_json_atomic

    def fail_backup(target, data):
        if target.parent.name == "credential-backups":
            raise OSError("disk full")
        writer(target, data)

    monkeypatch.setattr(migration, "write_json_atomic", fail_backup)
    with pytest.raises(OSError, match="disk full"):
        migrate_run_credentials(root)
    assert path.read_bytes() == original
    assert not (root / "state" / "credential-migration-v1.json").exists()
    monkeypatch.setattr(migration, "write_json_atomic", writer)
    assert migrate_run_credentials(root) == 1


@pytest.mark.parametrize("external_edit", [False, True])
async def test_gbk_overwrite_and_durable_rewind(tmp_path, external_edit):
    path = tmp_path / "report.csv"
    original = "姓名,成绩\r\n张三,90\r\n".encode("gbk")
    path.write_bytes(original)
    store = TurnCheckpointStore(tmp_path / "checkpoints")
    store.begin_turn(
        "turn", None, head=None, is_git=False, execution_root=str(tmp_path), tool_writes_only=True
    )
    context = ToolContext(
        working_directory=tmp_path,
        pre_write_capture=lambda name, old: store.record_pre_write("turn", name, old),
        on_file_mutation=lambda change: store.record_tool_write(
            "turn", change["path"], change["_before_content"], change["_after_content"]
        ),
    )
    tool = WriteFileTool()
    assert (
        await tool.execute({"path": "report.csv", "content": "姓名,成绩\n李四,95\n"}, context)
    ).success
    # A second UTF-8 write still retains the first GBK pre-image.
    assert (await tool.execute({"path": "report.csv", "content": "final\n"}, context)).success
    store.record_post_images("turn", tmp_path)
    if external_edit:
        path.write_bytes(b"user edit")
    store = TurnCheckpointStore(tmp_path / "checkpoints")
    report = await store.restore(["turn"], tmp_path)
    if external_edit:
        assert "report.csv" in report.conflicted and path.read_bytes() == b"user edit"
    else:
        assert "report.csv" in report.restored and path.read_bytes() == original


async def test_failed_byte_checkpoint_prevents_overwrite(tmp_path):
    path = tmp_path / "gbk.txt"
    original = "中文".encode("gbk")
    path.write_bytes(original)

    def fail(*args):
        raise OSError("disk full")

    with pytest.raises(ToolError, match="checkpoint"):
        await WriteFileTool().execute(
            {"path": "gbk.txt", "content": "replacement"},
            ToolContext(working_directory=tmp_path, pre_write_capture=fail),
        )
    assert path.read_bytes() == original


async def test_workspace_under_build_still_filters_children_and_explicit_ignored_root(tmp_path):
    workspace = tmp_path / "build" / "project"
    (workspace / "dist").mkdir(parents=True)
    (workspace / ".git").mkdir()
    (workspace / ".gitignore").write_text("dist/\n")
    (workspace / "dist" / "output.txt").write_text("needle")
    context = ToolContext(working_directory=workspace)
    result = await FileSearchTool().execute({"pattern": "*.txt", "path": "."}, context)
    assert "output.txt" not in result.content
    assert result.metadata["skipped_default_dirs"] == 2
    result = await FileSearchTool().execute({"pattern": "*.txt", "path": "dist"}, context)
    assert "output.txt" in result.content


def test_migration_reports_unparseable_records_without_destroying_them(tmp_path):
    path = tmp_path / "runs" / "a" / "broken.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"incomplete":')
    assert migrate_run_credentials(tmp_path) == 0
    report = json.loads((tmp_path / "state" / "credential-migration-v1.json").read_text())
    assert report["skipped"] == ["runs/a/broken.json"]
    assert path.read_bytes() == b'{"incomplete":'
