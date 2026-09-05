from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

import deepseek_tui.workspace.managed_worktree as managed_worktree
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.server.threads.manager import _ActiveThreadState
from deepseek_tui.server.threads.models import (
    CreateThreadRequest,
    RuntimeTurnStatus,
    StartTurnRequest,
    TurnRecord,
    UpdateThreadRequest,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.workspace.execution import execution_root, project_root
from deepseek_tui.workspace.managed_worktree import planned_worktree_path
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpoint


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "init")
    return repo


def _seed_turn(manager, thread_id: str, turn_id: str) -> None:
    now = datetime.now(timezone.utc)
    manager.store.save_turn(
        TurnRecord(
            id=turn_id,
            thread_id=thread_id,
            status=RuntimeTurnStatus.COMPLETED,
            input_summary="edit",
            created_at=now,
            started_at=now,
            ended_at=now,
        )
    )


def _save_checkpoint(manager, checkpoint: TurnCheckpoint) -> None:
    checkpoint.post_signatures = managed_worktree.worktree_path_signatures(
        Path(checkpoint.execution_root), checkpoint.mutated
    )
    checkpoint.post_signatures_captured = True
    manager.checkpoints._save(checkpoint)


@pytest.mark.asyncio
async def test_start_turn_never_dispatches_without_checkpoint(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    handle = EngineHandle()
    engine_task = asyncio.create_task(asyncio.sleep(3600), name="test-engine-idle")

    async def fake_ensure(live_thread, *, trace=None):
        del trace
        engine = SimpleNamespace(
            mode="agent",
            tool_context=ToolContext(working_directory=execution_root(live_thread)),
        )
        async with manager._active_lock:
            manager._active[live_thread.id] = _ActiveThreadState(
                handle, engine, engine_task, provider=live_thread.provider
            )
        return handle, engine_task

    def fail_checkpoint(*args, **kwargs):
        del args, kwargs
        raise OSError("checkpoint disk unavailable")

    monkeypatch.setattr(manager, "_ensure_engine_loaded", fake_ensure)
    monkeypatch.setattr(manager.checkpoints, "begin_turn", fail_checkpoint)

    try:
        with pytest.raises(RuntimeError, match="checkpoint initialization failed"):
            await manager.start_turn(thread.id, StartTurnRequest(prompt="edit app.py"))

        assert handle._op_queue.empty()
        turns = manager.store.list_turns_for_thread(thread.id)
        assert len(turns) == 1
        assert turns[0].status == RuntimeTurnStatus.FAILED
        assert "initialization failed" in (turns[0].error or "")
        assert thread.id not in manager._thread_leases
    finally:
        engine_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await engine_task
        async with manager._active_lock:
            manager._active.pop(thread.id, None)


@pytest.mark.asyncio
async def test_prepare_isolates_git_and_publish_writes_project(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    assert thread.env_mode == "local"
    prepared = await manager._prepare_isolated_workspace(thread)
    assert prepared.env_mode == "worktree"
    tree = execution_root(prepared)
    assert tree != project_root(prepared)
    assert (tree / "app.py").read_text(encoding="utf-8") == "one\n"
    (tree / "app.py").write_text("two\n", encoding="utf-8")
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    turn_id = "turn_pub1"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "two\n"},
        )
    )
    published = await manager._publish_isolated_thread(prepared)
    assert published.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "two\n"
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == repo.resolve()


@pytest.mark.parametrize("git_mutation", ["attach_branch", "move_detached_head"])
@pytest.mark.asyncio
async def test_publish_rejects_changed_worktree_git_state(
    runtime_app, tmp_path: Path, git_mutation: str
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("task change\n", encoding="utf-8")

    turn_id = f"turn_git_state_{git_mutation}"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(
        manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "task change\n"},
        ),
    )
    if git_mutation == "attach_branch":
        _git(tree, "switch", "-c", "agent/session-branch")
    else:
        _git(tree, "add", "app.py")
        _git(tree, "commit", "-m", "agent commit")

    published = await manager._publish_isolated_thread(prepared)

    assert published.publish_blocked is True
    assert published.publish_issue == "recovery"
    assert published.publish_conflicts == ["app.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == tree.resolve()

    action = "use_agent" if git_mutation == "attach_branch" else "keep_project"
    resolved = await manager.resolve_publish_conflicts(
        prepared.id, action=action, paths=["app.py"]
    )
    expected = "task change\n" if action == "use_agent" else "one\n"
    assert resolved.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == expected
    assert (tree / "app.py").read_text(encoding="utf-8") == expected
    assert await managed_worktree.current_worktree_branch(tree) == ""
    project_state = await managed_worktree.capture_worktree_baseline(repo)
    worktree_state = await managed_worktree.capture_worktree_baseline(tree)
    assert worktree_state.head == project_state.head


@pytest.mark.asyncio
async def test_publish_conflict_leaves_project(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("from-agent\n", encoding="utf-8")
    (repo / "app.py").write_text("from-claude\n", encoding="utf-8")
    turn_id = "turn_pub2"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "from-agent\n"},
        )
    )
    published = await manager._publish_isolated_thread(prepared)
    assert published.publish_blocked is True
    assert "app.py" in published.publish_conflicts
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-claude\n"

    kept = await manager.resolve_publish_conflicts(
        prepared.id, action="keep_project", paths=["app.py"]
    )
    assert kept.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-claude\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == "from-claude\n"
    retired = manager.checkpoints.load(turn_id)
    assert retired is not None
    assert retired.mutated == []

    (tree / "app.py").write_text("from-agent-again\n", encoding="utf-8")
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "from-agent-again\n"},
        )
    )
    (repo / "app.py").write_text("from-claude-2\n", encoding="utf-8")
    blocked_again = await manager._publish_isolated_thread(prepared)
    assert blocked_again.publish_conflicts == ["app.py"]
    forced = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent", paths=["app.py"]
    )
    assert forced.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-agent-again\n"


@pytest.mark.asyncio
async def test_use_agent_forces_only_conflicts_the_user_saw(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "other.py").write_text("other base\n", encoding="utf-8")
    _git(repo, "add", "other.py")
    _git(repo, "commit", "-m", "add other")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("task app\n", encoding="utf-8")
    (tree / "other.py").write_text("task other\n", encoding="utf-8")
    turn_id = "turn_scoped_force"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(
        manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py", "other.py"],
            pre_contents={"app.py": "one\n", "other.py": "other base\n"},
            post_contents={"app.py": "task app\n", "other.py": "task other\n"},
        ),
    )
    (repo / "app.py").write_text("editor app\n", encoding="utf-8")
    blocked = await manager._publish_isolated_thread(prepared)
    assert blocked.publish_conflicts == ["app.py"]

    # This conflict arrived after the confirmation was rendered.
    (repo / "other.py").write_text("late editor other\n", encoding="utf-8")
    retried = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent", paths=["app.py"]
    )

    assert retried.publish_blocked is True
    assert set(retried.publish_conflicts) == {"app.py", "other.py"}
    assert (repo / "other.py").read_text(encoding="utf-8") == "late editor other\n"


@pytest.mark.skipif(os.name == "nt", reason="executable mode is a POSIX concept")
@pytest.mark.asyncio
async def test_publish_requires_choice_for_task_mode_change(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("draft\n", encoding="utf-8")
    (tree / "app.py").chmod(0o755)
    turn_id = "turn_mode_change"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "draft\n"},
        )
    )

    blocked = await manager._publish_isolated_thread(prepared)

    assert blocked.publish_conflicts == ["app.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    assert (repo / "app.py").stat().st_mode & 0o777 == 0o644

    resolved = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent", paths=["app.py"]
    )
    assert resolved.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "draft\n"
    assert (repo / "app.py").stat().st_mode & 0o777 == 0o755


@pytest.mark.skipif(os.name == "nt", reason="executable mode is a POSIX concept")
@pytest.mark.asyncio
async def test_publish_preserves_mode_of_new_checkpointed_file(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    script = tree / "run.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    turn_id = "turn_new_executable"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["run.sh"],
            pre_contents={"run.sh": None},
            post_contents={"run.sh": "#!/bin/sh\n"},
        )
    )

    published = await manager._publish_isolated_thread(prepared)

    assert published.publish_blocked is False
    assert (repo / "run.sh").read_text(encoding="utf-8") == "#!/bin/sh\n"
    assert (repo / "run.sh").stat().st_mode & 0o777 == 0o755


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
@pytest.mark.asyncio
async def test_explicit_publish_preserves_new_symlink_identity(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    os.symlink("app.py", tree / "link.py")
    turn_id = "turn_new_symlink"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["link.py"],
            uncertain=["link.py"],
            pre_contents={},
            post_contents={},
        )
    )

    blocked = await manager._publish_isolated_thread(prepared)
    assert blocked.publish_conflicts == ["link.py"]

    published = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent", paths=["link.py"]
    )
    assert published.publish_blocked is False
    assert (repo / "link.py").is_symlink()
    assert os.readlink(repo / "link.py") == "app.py"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
@pytest.mark.asyncio
async def test_explicit_symlink_delete_never_deletes_link_target(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    os.symlink("app.py", repo / "link.py")
    _git(repo, "add", "link.py")
    _git(repo, "commit", "-m", "add link")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "link.py").unlink()
    turn_id = "turn_delete_symlink"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["link.py"],
            pre_contents={"link.py": "one\n"},
            post_contents={"link.py": None},
        )
    )

    blocked = await manager._publish_isolated_thread(prepared)
    assert blocked.publish_conflicts == ["link.py"]

    published = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent", paths=["link.py"]
    )
    assert published.publish_blocked is False
    assert not (repo / "link.py").exists()
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"


@pytest.mark.asyncio
async def test_opaque_change_blocks_instead_of_being_falsely_published(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    payload = b"\x00\x01agent-binary\xff"
    (tree / "asset.bin").write_bytes(payload)
    turn_id = "turn_binary"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["asset.bin"],
            pre_contents={},
            post_contents={},
        )
    )

    blocked = await manager._publish_isolated_thread(prepared)

    assert blocked.publish_blocked is True
    assert blocked.publish_conflicts == ["asset.bin"]
    assert not (repo / "asset.bin").exists()
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == tree.resolve()


@pytest.mark.asyncio
async def test_use_agent_explicitly_publishes_opaque_bytes(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    payload = b"\x00\x01agent-binary\xff"
    (tree / "asset.bin").write_bytes(payload)
    turn_id = "turn_binary_force"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["asset.bin"],
            post_contents={},
        )
    )

    blocked = await manager._publish_isolated_thread(prepared)
    assert blocked.publish_blocked is True
    resolved = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent", paths=["asset.bin"]
    )

    assert resolved.publish_blocked is False
    assert (repo / "asset.bin").read_bytes() == payload
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == repo.resolve()


@pytest.mark.asyncio
async def test_safe_raw_creation_rejects_mutation_at_apply_seam(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    asset = tree / "asset.bin"
    asset.write_bytes(b"\0checkpoint")
    turn_id = "turn_safe_raw_late"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["asset.bin"],
            pre_contents={"asset.bin": None},
        )
    )
    manager.checkpoints.record_post_images(turn_id, tree)
    real_apply_raw_images = managed_worktree.apply_raw_path_images
    injected = False

    async def mutate_before_raw_apply(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            asset.write_bytes(b"\0late")
        return await real_apply_raw_images(*args, **kwargs)

    monkeypatch.setattr(
        managed_worktree, "apply_raw_path_images", mutate_before_raw_apply
    )

    blocked = await manager._publish_isolated_thread(prepared)

    assert blocked.publish_blocked is True
    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["asset.bin"]
    assert (repo / "asset.bin").read_bytes() == b"\0checkpoint"
    assert asset.read_bytes() == b"\0late"
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert checkpoint.publish_apply_complete is True


@pytest.mark.asyncio
async def test_safe_raw_creation_retry_accepts_only_matching_partial_publish(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    old_payloads = {
        "first.bin": b"\0first project",
        "second.bin": b"\0second project",
    }
    for path, payload in old_payloads.items():
        (repo / path).write_bytes(payload)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    payloads = {
        "first.bin": b"\0first checkpoint",
        "second.bin": b"\0second checkpoint",
    }
    (tree / "app.py").write_text("task text\n", encoding="utf-8")
    for path, payload in payloads.items():
        (tree / path).write_bytes(payload)
    turn_id = "turn_safe_raw_partial_retry"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py", *payloads],
            pre_contents={
                "app.py": "one\n",
                **{path: None for path in payloads},
            },
        )
    )
    manager.checkpoints.record_post_images(turn_id, tree)
    real_apply_raw_images = managed_worktree.apply_raw_path_images
    real_write_text = managed_worktree._write_text
    crashed = False

    def assert_journal_before_text_write(
        project_root: Path, path: str, content: str | None
    ) -> None:
        staged = manager.checkpoints.load(turn_id)
        assert staged is not None
        assert staged.publish_pending_sync is True
        assert set(staged.raw_pre_images) == set(payloads)
        assert set(staged.raw_post_images) == set(payloads)
        for image in manager.checkpoints.raw_publish_images(turn_id, list(payloads)):
            assert all(
                item.payload_path is None or item.payload_path.is_file()
                for item in image
            )
        real_write_text(project_root, path, content)

    async def crash_after_first_raw_write(
        project_root: Path,
        pre_images: list[managed_worktree.RawPathImage],
        post_images: list[managed_worktree.RawPathImage],
        **kwargs,
    ):
        nonlocal crashed
        if not crashed:
            crashed = True
            first = min(post_images, key=lambda image: image.path)
            managed_worktree._write_raw_path_image(project_root, first)
            raise RuntimeError("simulated crash during raw publish")
        return await real_apply_raw_images(
            project_root, pre_images, post_images, **kwargs
        )

    monkeypatch.setattr(
        managed_worktree, "apply_raw_path_images", crash_after_first_raw_write
    )
    monkeypatch.setattr(
        managed_worktree, "_write_text", assert_journal_before_text_write
    )
    with pytest.raises(RuntimeError, match="during raw publish"):
        await manager._publish_isolated_thread(
            prepared, force_paths=list(payloads)
        )

    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert checkpoint.publish_pending_sync is True
    assert checkpoint.publish_apply_complete is False
    assert set(checkpoint.raw_pre_images) == set(payloads)
    assert set(checkpoint.raw_post_images) == set(payloads)
    assert (repo / "app.py").read_text(encoding="utf-8") == "task text\n"
    assert managed_worktree.worktree_path_signatures(repo, ["first.bin"])[
        "first.bin"
    ] == checkpoint.post_signatures["first.bin"]
    assert (repo / "second.bin").read_bytes() == old_payloads["second.bin"]

    monkeypatch.setattr(
        managed_worktree, "apply_raw_path_images", real_apply_raw_images
    )
    (repo / "first.bin").write_bytes(b"\0external edit")
    blocked = await manager._publish_isolated_thread(
        manager.store.load_thread(prepared.id)
    )

    assert blocked.publish_blocked is True
    assert blocked.publish_conflicts == ["first.bin"]
    assert (repo / "first.bin").read_bytes() == b"\0external edit"
    assert (repo / "second.bin").read_bytes() == old_payloads["second.bin"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "task text\n"

    managed_worktree._copy_raw(tree, repo, "first.bin")
    published = await manager._publish_isolated_thread(
        manager.store.load_thread(prepared.id)
    )

    assert published.publish_blocked is False
    assert published.publish_pending is False
    for path, payload in payloads.items():
        assert (repo / path).read_bytes() == payload
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert checkpoint.publish_pending_sync is False
    assert checkpoint.publish_apply_complete is False

    restored = await manager.checkpoints.restore([turn_id], tree)

    assert set(restored.restored) == {"app.py", *payloads}
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    for path, payload in old_payloads.items():
        assert (repo / path).read_bytes() == payload


@pytest.mark.asyncio
async def test_raw_failure_rollback_preserves_late_project_text_edit(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("task text\n", encoding="utf-8")
    (tree / "asset.bin").write_bytes(b"\0task")
    turn_id = "turn_raw_rollback_cas"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py", "asset.bin"],
            pre_contents={"app.py": "one\n", "asset.bin": None},
        )
    )
    manager.checkpoints.record_post_images(turn_id, tree)

    async def fail_raw_after_external_text_edit(*_args, **_kwargs):
        (repo / "app.py").write_text("late editor text\n", encoding="utf-8")
        return managed_worktree.ApplyReport(skipped=["asset.bin"])

    monkeypatch.setattr(
        managed_worktree,
        "apply_raw_path_images",
        fail_raw_after_external_text_edit,
    )

    blocked = await manager._publish_isolated_thread(prepared)

    assert blocked.publish_blocked is True
    assert set(blocked.publish_conflicts) == {"app.py", "asset.bin"}
    assert (repo / "app.py").read_text(encoding="utf-8") == "late editor text\n"
    assert not (repo / "asset.bin").exists()


@pytest.mark.asyncio
async def test_non_git_stays_on_project(runtime_app, tmp_path: Path) -> None:
    manager = runtime_app.state.thread_manager
    folder = tmp_path / "plain"
    folder.mkdir()
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(folder), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    assert prepared.env_mode == "local"
    assert execution_root(prepared) == folder.resolve()


@pytest.mark.asyncio
async def test_archiving_reclaims_clean_owned_worktree(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    assert tree.is_dir()

    archived = await manager.update_thread(
        prepared.id, UpdateThreadRequest(archived=True)
    )

    assert archived.archived is True
    assert not tree.exists()
    assert archived.env_mode == "local"
    assert archived.worktree_path is None
    assert archived.associated_worktree_path is None


@pytest.mark.asyncio
async def test_archiving_keeps_unpublished_worktree(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("unpublished\n", encoding="utf-8")
    prepared.publish_blocked = True
    manager.store.save_thread(prepared)

    archived = await manager.update_thread(
        prepared.id, UpdateThreadRequest(archived=True)
    )

    assert archived.archived is True
    assert tree.is_dir()
    assert archived.worktree_path == str(tree)


@pytest.mark.asyncio
async def test_delete_refuses_to_orphan_unpublished_worktree(
    runtime_app, client: AsyncClient, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("unpublished\n", encoding="utf-8")
    prepared.publish_blocked = True
    prepared.publish_conflicts = ["app.py"]
    manager.store.save_thread(prepared)

    refused = await client.delete(f"/v1/threads/{prepared.id}")

    assert refused.status_code == 409
    assert refused.json()["detail"]["error"] == "unpublished_worktree_code"
    assert tree.is_dir()
    assert manager.store.load_thread(prepared.id).worktree_path == str(tree)

    deleted = await client.delete(
        f"/v1/threads/{prepared.id}?discard_unpublished=true"
    )

    assert deleted.status_code == 204
    assert not tree.exists()
    with pytest.raises(FileNotFoundError):
        manager.store.load_thread(prepared.id)


@pytest.mark.asyncio
async def test_startup_reconciliation_clears_stale_path_and_merged_branch(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    stale_path = planned_worktree_path(repo, thread.id)
    branch = f"ds/{thread.id}"
    _git(repo, "branch", branch)
    thread.env_mode = "worktree"
    thread.worktree_path = str(stale_path)
    thread.associated_worktree_path = str(stale_path)
    thread.worktree_owned = True
    thread.worktree_branch = branch
    manager.store.save_thread(thread)

    manager._reconcile_missing_worktrees_on_boot()

    reconciled = manager.store.load_thread(thread.id)
    assert reconciled.env_mode == "local"
    assert reconciled.worktree_path is None
    assert reconciled.associated_worktree_path is None
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")


@pytest.mark.asyncio
async def test_startup_reconciliation_preserves_missing_recovery_evidence(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    stale_path = planned_worktree_path(repo, thread.id)
    thread.env_mode = "worktree"
    thread.worktree_path = str(stale_path)
    thread.associated_worktree_path = str(stale_path)
    thread.worktree_owned = True
    thread.publish_pending = True
    thread.publish_blocked = True
    thread.publish_conflicts = ["<unpublished-worktree-labor>", "app.py"]
    manager.store.save_thread(thread)

    manager._reconcile_missing_worktrees_on_boot()

    reconciled = manager.store.load_thread(thread.id)
    assert reconciled.env_mode == "worktree"
    assert reconciled.worktree_path == str(stale_path)
    assert reconciled.publish_pending is True
    assert reconciled.publish_blocked is True
    assert reconciled.publish_issue == "missing"
    assert reconciled.publish_conflicts == ["app.py"]
    prepared = await manager._prepare_isolated_workspace(reconciled)
    assert prepared.worktree_path == str(stale_path)
    assert not stale_path.exists()
    with pytest.raises(ValueError, match="pending code state"):
        await manager.start_turn(
            thread.id, StartTurnRequest(prompt="continue editing")
        )
    assert manager.store.list_turns_for_thread(thread.id) == []


@pytest.mark.asyncio
async def test_prepare_syncs_current_project_into_isolate(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("from-claude\n", encoding="utf-8")
    synced = await manager._prepare_isolated_workspace(prepared)
    assert execution_root(synced) == tree
    assert (tree / "app.py").read_text(encoding="utf-8") == "from-claude\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-claude\n"


@pytest.mark.asyncio
async def test_existing_inbound_sync_failure_is_visible_and_apply_retries_sync(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("project update\n", encoding="utf-8")
    real_sync = manager._sync_isolate_with_baseline

    async def fail_sync(*args, **kwargs):
        del args, kwargs
        raise OSError("temporary inbound sync failure")

    monkeypatch.setattr(manager, "_sync_isolate_with_baseline", fail_sync)
    with pytest.raises(OSError, match="temporary inbound sync failure"):
        await manager._prepare_isolated_workspace(prepared)

    failed = manager.store.load_thread(thread.id)
    assert failed.publish_pending is True
    assert failed.publish_blocked is True
    assert failed.publish_issue == "failure"
    assert failed.publish_request_action is None
    assert failed.publish_conflicts == []
    assert (tree / "app.py").read_text(encoding="utf-8") == "one\n"
    assert any(
        event.event == "thread.updated"
        and event.payload.get("changes", {}).get("publish_issue") == "failure"
        for event in manager.events_since(thread.id)
    )

    monkeypatch.setattr(manager, "_sync_isolate_with_baseline", real_sync)
    result = await manager.request_publish_action(thread.id, action="apply")

    assert result["status"] == "applied"
    assert result["thread"].publish_pending is False
    assert result["thread"].publish_blocked is False
    assert result["thread"].publish_issue is None
    assert result["thread"].publish_request_action is None
    assert result["thread"].publish_request_paths == []
    assert result["thread"].publish_waiting_on is None
    assert (tree / "app.py").read_text(encoding="utf-8") == "project update\n"


@pytest.mark.asyncio
async def test_prepare_never_falls_back_to_project_when_isolation_fails(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )

    async def fail_create(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected isolation failure")

    monkeypatch.setattr(managed_worktree, "create_managed_worktree", fail_create)

    with pytest.raises(RuntimeError, match="injected isolation failure"):
        await manager._prepare_isolated_workspace(thread)

    persisted = manager.store.load_thread(thread.id)
    assert persisted.env_mode == "local"
    assert persisted.worktree_path is None
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"


@pytest.mark.asyncio
async def test_prepare_does_not_report_inherited_project_dirt_as_thread_labor(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("project-dirty-a\n", encoding="utf-8")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "extra.py").write_text("project-dirty-b\n", encoding="utf-8")

    refreshed = await manager._prepare_isolated_workspace(prepared)

    assert refreshed.publish_pending is False
    assert refreshed.publish_blocked is False
    assert refreshed.publish_conflicts == []
    assert (tree / "app.py").read_text(encoding="utf-8") == "project-dirty-a\n"
    assert (tree / "extra.py").read_text(encoding="utf-8") == "project-dirty-b\n"


@pytest.mark.asyncio
async def test_publish_resyncs_unrelated_concurrent_project_change(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("task change\n", encoding="utf-8")
    (repo / "extra.py").write_text("project change\n", encoding="utf-8")
    turn_id = "turn_concurrent_project"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "task change\n"},
        )
    )

    published = await manager._publish_isolated_thread(prepared)

    assert published.publish_pending is False
    assert published.publish_blocked is False
    assert published.publish_conflicts == []
    assert (repo / "app.py").read_text(encoding="utf-8") == "task change\n"
    assert (tree / "extra.py").read_text(encoding="utf-8") == "project change\n"


@pytest.mark.asyncio
async def test_prepare_tracks_same_path_project_dirt_from_last_sync(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("project-dirty-a\n", encoding="utf-8")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("project-dirty-b\n", encoding="utf-8")

    refreshed = await manager._prepare_isolated_workspace(prepared)

    assert refreshed.publish_pending is False
    assert refreshed.publish_blocked is False
    assert (tree / "app.py").read_text(encoding="utf-8") == "project-dirty-b\n"


@pytest.mark.asyncio
async def test_prepare_self_heals_legacy_false_recovery_marker(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("project-dirty-a\n", encoding="utf-8")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "extra.py").write_text("project-dirty-b\n", encoding="utf-8")
    manager.store.delete_worktree_baseline(thread.id)
    prepared.publish_pending = True
    prepared.publish_blocked = True
    prepared.publish_conflicts = ["<unpublished-worktree-labor>"]
    manager.store.save_thread(prepared)

    refreshed = await manager._prepare_isolated_workspace(prepared)

    assert refreshed.publish_pending is False
    assert refreshed.publish_blocked is False
    assert refreshed.publish_conflicts == []
    assert (tree / "extra.py").read_text(encoding="utf-8") == "project-dirty-b\n"
    assert manager.store.load_worktree_baseline(thread.id) is not None


@pytest.mark.asyncio
async def test_legacy_ambiguous_labor_cannot_overwrite_project(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "inherited.txt").write_text("inherited-old\n", encoding="utf-8")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    manager.store.delete_worktree_baseline(thread.id)
    (tree / "agent.txt").write_text("task version\n", encoding="utf-8")
    (repo / "inherited.txt").write_text("project-new\n", encoding="utf-8")

    blocked = await manager._prepare_isolated_workspace(prepared)

    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == []
    with pytest.raises(ValueError, match="ownership could not be verified"):
        await manager.resolve_publish_conflicts(thread.id, action="use_agent")
    assert (repo / "inherited.txt").read_text(encoding="utf-8") == "project-new\n"
    assert not (repo / "agent.txt").exists()

    kept = await manager.resolve_publish_conflicts(
        thread.id, action="keep_project"
    )
    assert kept.publish_pending is False
    assert kept.publish_blocked is False
    assert kept.publish_issue is None
    assert (repo / "inherited.txt").read_text(encoding="utf-8") == "project-new\n"
    assert not (repo / "agent.txt").exists()
    assert (tree / "inherited.txt").read_text(encoding="utf-8") == "project-new\n"
    assert not (tree / "agent.txt").exists()
    assert manager.store.load_worktree_baseline(thread.id) is not None


@pytest.mark.asyncio
async def test_legacy_keep_project_retires_only_paths_that_differ(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "delivered.py").write_text("task\n", encoding="utf-8")
    (repo / "delivered.py").write_text("task\n", encoding="utf-8")
    (tree / "rejected.py").write_text("task\n", encoding="utf-8")
    (repo / "rejected.py").write_text("keep\n", encoding="utf-8")
    turn_id = "turn_legacy_precise_keep"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=thread.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["delivered.py", "rejected.py"],
            pre_contents={"delivered.py": None, "rejected.py": None},
        )
    )
    manager.checkpoints.record_post_images(turn_id, tree)
    manager.store.delete_worktree_baseline(thread.id)
    prepared.publish_pending = True
    prepared.publish_blocked = True
    prepared.publish_issue = "recovery"
    prepared.publish_conflicts = []
    manager.store.save_thread(prepared)

    kept = await manager.resolve_publish_conflicts(
        thread.id, action="keep_project"
    )

    assert kept.publish_blocked is False
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert checkpoint.mutated == ["delivered.py"]
    assert (repo / "delivered.py").read_text(encoding="utf-8") == "task\n"
    assert (repo / "rejected.py").read_text(encoding="utf-8") == "keep\n"
    # A later edit matching the rejected task image is unrelated and must not
    # become eligible for rollback through the retired checkpoint entry.
    (repo / "rejected.py").write_text("task\n", encoding="utf-8")

    report = await manager.checkpoints.restore([turn_id], tree)

    assert report.restored == ["delivered.py"]
    assert not (repo / "delivered.py").exists()
    assert (repo / "rejected.py").read_text(encoding="utf-8") == "task\n"


@pytest.mark.asyncio
async def test_legacy_checkpoint_publish_establishes_first_baseline(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "inherited.txt").write_text("project inherited\n", encoding="utf-8")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    manager.store.delete_worktree_baseline(thread.id)
    (tree / "task.txt").write_text("task change\n", encoding="utf-8")
    (repo / "later.txt").write_text("later project change\n", encoding="utf-8")
    turn_id = "turn_legacy_checkpoint"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=thread.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["task.txt"],
            pre_contents={"task.txt": None},
            post_contents={"task.txt": "task change\n"},
        )
    )

    published = await manager._publish_isolated_thread(prepared)

    assert published.publish_blocked is False
    assert published.publish_issue is None
    assert (repo / "task.txt").read_text(encoding="utf-8") == "task change\n"
    assert (tree / "later.txt").read_text(encoding="utf-8") == (
        "later project change\n"
    )
    assert manager.store.load_worktree_baseline(thread.id) is not None


@pytest.mark.asyncio
async def test_prepare_auto_reconciles_checkpointed_labor(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("recovered\n", encoding="utf-8")
    turn_id = "turn_recovered_checkpoint"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "recovered\n"},
        )
    )

    reconciled = await manager._prepare_isolated_workspace(prepared)

    assert reconciled.publish_pending is False
    assert reconciled.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "recovered\n"


@pytest.mark.asyncio
async def test_prepare_preserves_uncheckpointed_isolate_labor(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("uncheckpointed-agent\n", encoding="utf-8")
    (repo / "app.py").write_text("from-editor\n", encoding="utf-8")

    async def fake_ensure_engine_loaded(_thread):
        return None

    monkeypatch.setattr(manager, "_ensure_engine_loaded", fake_ensure_engine_loaded)
    warmup = await manager.warmup_thread(thread.id)
    prepared = manager.store.load_thread(thread.id)

    assert warmup["status"] == "ready"
    assert execution_root(prepared) == tree
    assert (tree / "app.py").read_text(encoding="utf-8") == "uncheckpointed-agent\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-editor\n"
    persisted = manager.store.load_thread(thread.id)
    assert persisted.publish_blocked is True
    assert persisted.publish_issue == "recovery"
    assert persisted.publish_conflicts == ["app.py"]
    assert any(
        event.event == "thread.updated"
        and event.payload.get("changes", {}).get("publish_blocked") is True
        for event in manager.events_since(thread.id)
    )

    resolved = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )
    assert resolved.publish_blocked is False
    assert resolved.publish_conflicts == []
    assert (repo / "app.py").read_text(encoding="utf-8") == "uncheckpointed-agent\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == "uncheckpointed-agent\n"


@pytest.mark.asyncio
async def test_apply_never_chooses_agent_bytes_for_recovery(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("uncheckpointed task\n", encoding="utf-8")
    blocked = await manager._prepare_isolated_workspace(prepared)
    assert blocked.publish_issue == "recovery"

    result = await manager.request_publish_action(thread.id, action="apply")

    assert result["status"] == "conflict"
    assert result["thread"].publish_issue == "recovery"
    assert result["thread"].publish_request_action is None
    assert result["thread"].publish_waiting_on is None
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == (
        "uncheckpointed task\n"
    )


@pytest.mark.asyncio
async def test_stale_recovery_token_cannot_apply_new_snapshot(
    runtime_app, client: AsyncClient, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("shown task bytes\n", encoding="utf-8")
    shown = await manager._prepare_isolated_workspace(prepared)
    shown_at = shown.updated_at
    shown_token = shown_at.isoformat()

    (tree / "app.py").write_text("new unseen task bytes\n", encoding="utf-8")
    refreshed = await manager._prepare_isolated_workspace(shown)
    assert refreshed.updated_at != shown_at

    missing = await client.post(
        f"/v1/threads/{thread.id}/worktree/resolve",
        json={"action": "use_agent"},
    )
    assert missing.status_code == 200
    assert missing.json()["status"] == "conflict"
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    response = await client.post(
        f"/v1/threads/{thread.id}/worktree/resolve",
        json={"action": "use_agent", "recovery_token": shown_token},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "conflict"
    assert manager.store.load_thread(thread.id).publish_blocked is True
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == (
        "new unseen task bytes\n"
    )

    current = manager.store.load_thread(thread.id)
    accepted = await client.post(
        f"/v1/threads/{thread.id}/worktree/resolve",
        json={
            "action": "use_agent",
            "recovery_token": current.updated_at.isoformat(),
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "applied"
    assert (repo / "app.py").read_text(encoding="utf-8") == (
        "new unseen task bytes\n"
    )


@pytest.mark.asyncio
async def test_recovery_applies_only_task_owned_delta(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "seed.txt").write_text("seed-one\n", encoding="utf-8")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("uncheckpointed-agent\n", encoding="utf-8")
    (repo / "seed.txt").write_text("seed-two\n", encoding="utf-8")

    blocked = await manager._prepare_isolated_workspace(prepared)

    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["app.py"]
    resolved = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )
    assert resolved.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "uncheckpointed-agent\n"
    assert (repo / "seed.txt").read_text(encoding="utf-8") == "seed-two\n"
    assert (tree / "seed.txt").read_text(encoding="utf-8") == "seed-two\n"


@pytest.mark.asyncio
async def test_recovery_preserves_filename_equal_to_legacy_marker(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "<publish-failed>").write_text("task version\n", encoding="utf-8")

    blocked = await manager._prepare_isolated_workspace(prepared)

    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["<publish-failed>"]
    resolved = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )
    assert resolved.publish_blocked is False
    assert (repo / "<publish-failed>").read_text(encoding="utf-8") == (
        "task version\n"
    )


@pytest.mark.asyncio
async def test_recovery_refreshes_changed_path_set_before_writing(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("task app\n", encoding="utf-8")

    blocked = await manager._prepare_isolated_workspace(prepared)
    assert blocked.publish_conflicts == ["app.py"]

    # The recovery choice was rendered for app.py, then the isolate changed.
    (tree / "later.py").write_text("task later\n", encoding="utf-8")
    refreshed = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )

    assert refreshed.publish_blocked is True
    assert refreshed.publish_issue == "recovery"
    assert refreshed.publish_conflicts == ["app.py", "later.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    assert not (repo / "later.py").exists()

    applied = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )
    assert applied.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "task app\n"
    assert (repo / "later.py").read_text(encoding="utf-8") == "task later\n"


@pytest.mark.asyncio
async def test_recovery_refreshes_changed_bytes_before_writing_same_path(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("shown task version\n", encoding="utf-8")
    blocked = await manager._prepare_isolated_workspace(prepared)
    assert blocked.publish_conflicts == ["app.py"]

    (tree / "app.py").write_text("new unseen task version\n", encoding="utf-8")
    refreshed = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )

    assert refreshed.publish_blocked is True
    assert refreshed.publish_conflicts == ["app.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    applied = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )
    assert applied.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == (
        "new unseen task version\n"
    )


@pytest.mark.asyncio
async def test_incomplete_inbound_sync_recovers_without_claiming_partial_copy(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("project two\n", encoding="utf-8")
    (repo / "later.py").write_text("project later\n", encoding="utf-8")
    real_overlay = managed_worktree.overlay_working_paths

    def crash_after_first_path(
        source: Path, dest: Path, paths: list[str], **_kwargs
    ) -> None:
        first = sorted(paths)[0]
        managed_worktree._copy_raw(source, dest, first)
        raise OSError("simulated process exit during inbound sync")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", crash_after_first_path
    )
    engine_loaded = False

    async def fail_if_engine_loads(*args, **kwargs):
        nonlocal engine_loaded
        engine_loaded = True
        raise AssertionError("engine must not load from a partially synced isolate")

    monkeypatch.setattr(manager, "_ensure_engine_loaded", fail_if_engine_loads)
    with pytest.raises(OSError, match="simulated process exit"):
        await manager.start_turn(
            thread.id, StartTurnRequest(prompt="continue editing")
        )
    assert engine_loaded is False
    assert manager.store.list_turns_for_thread(thread.id) == []
    journal = manager.store.load_worktree_baseline(thread.id)
    assert journal is not None
    assert journal.get("sync_in_progress") is True
    sync_journal = journal.get("sync_journal")
    assert isinstance(sync_journal, dict)
    assert set(sync_journal.get("before", {})) >= {"app.py", "later.py"}
    assert set(sync_journal.get("target", {})) >= {"app.py", "later.py"}

    monkeypatch.setattr(managed_worktree, "overlay_working_paths", real_overlay)
    recovered = await manager._prepare_isolated_workspace(
        manager.store.load_thread(thread.id)
    )

    assert recovered.publish_blocked is False
    assert recovered.publish_issue is None
    assert (tree / "app.py").read_text(encoding="utf-8") == "project two\n"
    assert (tree / "later.py").read_text(encoding="utf-8") == "project later\n"
    baseline = manager.store.load_worktree_baseline(thread.id)
    assert baseline is not None
    assert "sync_in_progress" not in baseline


@pytest.mark.asyncio
async def test_incomplete_sync_never_overwrites_later_isolate_edit(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("project two\n", encoding="utf-8")
    (repo / "later.py").write_text("project later\n", encoding="utf-8")
    real_overlay = managed_worktree.overlay_working_paths

    def crash_after_first_path(
        source: Path, dest: Path, paths: list[str], **_kwargs
    ) -> None:
        first = sorted(paths)[0]
        managed_worktree._copy_raw(source, dest, first)
        raise OSError("simulated process exit during inbound sync")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", crash_after_first_path
    )
    with pytest.raises(OSError, match="simulated process exit"):
        await manager._prepare_isolated_workspace(prepared)

    # This edit happened after the interrupted sync. It is neither the
    # journaled pre-sync image nor the intended project target.
    (tree / "app.py").write_text("later task edit\n", encoding="utf-8")
    monkeypatch.setattr(managed_worktree, "overlay_working_paths", real_overlay)

    recovered = await manager._prepare_isolated_workspace(
        manager.store.load_thread(thread.id)
    )

    assert recovered.publish_pending is True
    assert recovered.publish_blocked is True
    assert recovered.publish_issue == "recovery"
    assert "app.py" in recovered.publish_conflicts
    assert (tree / "app.py").read_text(encoding="utf-8") == "later task edit\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "project two\n"


@pytest.mark.asyncio
async def test_checkout_interruption_retries_without_fake_task_labor(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("committed target\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "advance project")
    target_head = (
        await managed_worktree._git(repo, ["rev-parse", "HEAD"])
    ).strip()
    (repo / "app.py").write_text("project dirty target\n", encoding="utf-8")
    real_overlay = managed_worktree.overlay_working_paths

    def crash_after_checkout(
        _source: Path, dest: Path, _paths: list[str], **_kwargs
    ) -> None:
        assert (dest / "app.py").read_text(encoding="utf-8") == (
            "committed target\n"
        )
        raise OSError("simulated crash after checkout")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", crash_after_checkout
    )
    with pytest.raises(OSError, match="simulated crash after checkout"):
        await manager._prepare_isolated_workspace(prepared)

    failed = manager.store.load_thread(thread.id)
    assert failed.publish_issue == "failure"
    journal = manager.store.load_worktree_baseline(thread.id)
    assert journal is not None
    assert journal.get("sync_in_progress") is True
    assert journal.get("sync_journal", {}).get("checkout_target_head") == target_head
    assert (tree / "app.py").read_text(encoding="utf-8") == "committed target\n"

    monkeypatch.setattr(managed_worktree, "overlay_working_paths", real_overlay)
    result = await manager.request_publish_action(thread.id, action="apply")

    assert result["status"] == "applied"
    assert result["thread"].publish_blocked is False
    assert result["thread"].publish_issue is None
    assert result["thread"].publish_conflicts == []
    assert (repo / "app.py").read_text(encoding="utf-8") == (
        "project dirty target\n"
    )
    assert (tree / "app.py").read_text(encoding="utf-8") == (
        "project dirty target\n"
    )


@pytest.mark.asyncio
async def test_mixed_incomplete_sync_only_recovers_third_state_labor(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("project target one\n", encoding="utf-8")
    (repo / "later.py").write_text("project later\n", encoding="utf-8")
    real_overlay = managed_worktree.overlay_working_paths

    def crash_after_partial_target(
        source: Path, dest: Path, paths: list[str], **_kwargs
    ) -> None:
        assert sorted(paths)[0] == "app.py"
        managed_worktree._copy_raw(source, dest, "app.py")
        raise OSError("simulated mixed inbound sync interruption")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", crash_after_partial_target
    )
    with pytest.raises(OSError, match="mixed inbound sync interruption"):
        await manager._prepare_isolated_workspace(prepared)

    # app.py is exactly the journaled target and therefore only a sync
    # artifact. later.py is neither its before nor target image: it is the one
    # path whose ownership requires a user decision.
    (tree / "later.py").write_text("task labor\n", encoding="utf-8")
    monkeypatch.setattr(managed_worktree, "overlay_working_paths", real_overlay)
    blocked = await manager._prepare_isolated_workspace(
        manager.store.load_thread(thread.id)
    )

    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["later.py"]
    raw_baseline = manager.store.load_worktree_baseline(thread.id)
    assert raw_baseline is not None
    assert raw_baseline.get("sync_in_progress") is True
    assert set(raw_baseline.get("recovery_snapshot", {})) == {"later.py"}

    # The project advances after the choice is shown. Resolving task labor may
    # copy only later.py to the project; the stale journal target for app.py
    # must be discarded in favor of the project's newest bytes.
    (repo / "app.py").write_text("project target two\n", encoding="utf-8")
    resolved = await manager.resolve_publish_conflicts(
        thread.id, action="use_agent"
    )

    assert resolved.publish_pending is False
    assert resolved.publish_blocked is False
    assert resolved.publish_issue is None
    assert (repo / "app.py").read_text(encoding="utf-8") == (
        "project target two\n"
    )
    assert (repo / "later.py").read_text(encoding="utf-8") == "task labor\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == (
        "project target two\n"
    )
    assert (tree / "later.py").read_text(encoding="utf-8") == "task labor\n"
    completed_baseline = manager.store.load_worktree_baseline(thread.id)
    assert completed_baseline is not None
    assert "sync_in_progress" not in completed_baseline
    assert "recovery_snapshot" not in completed_baseline


@pytest.mark.asyncio
async def test_sync_post_verify_never_adopts_edit_after_overlay(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (repo / "app.py").write_text("project update\n", encoding="utf-8")
    real_overlay = managed_worktree.overlay_working_paths
    injected = False

    def edit_after_overlay(*args, **kwargs) -> None:
        nonlocal injected
        real_overlay(*args, **kwargs)
        if not injected:
            injected = True
            (tree / "app.py").write_text("late task edit\n", encoding="utf-8")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", edit_after_overlay
    )

    blocked = await manager._prepare_isolated_workspace(prepared)

    assert blocked.publish_pending is True
    assert blocked.publish_blocked is True
    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["app.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "project update\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == "late task edit\n"


@pytest.mark.asyncio
async def test_initial_inbound_sync_failure_keeps_copy_for_journal_recovery(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("project two\n", encoding="utf-8")
    (repo / "later.py").write_text("project later\n", encoding="utf-8")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    real_overlay = managed_worktree.overlay_working_paths

    def crash_after_first_path(
        source: Path, dest: Path, paths: list[str], **_kwargs
    ) -> None:
        first = sorted(paths)[0]
        managed_worktree._copy_raw(source, dest, first)
        raise OSError("simulated first sync failure")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", crash_after_first_path
    )
    with pytest.raises(OSError, match="simulated first sync failure"):
        await manager.start_turn(
            thread.id, StartTurnRequest(prompt="start editing")
        )

    failed = manager.store.load_thread(thread.id)
    assert failed.env_mode == "worktree"
    assert failed.worktree_path
    tree = execution_root(failed)
    assert tree.is_dir()
    journal = manager.store.load_worktree_baseline(thread.id)
    assert journal is not None
    assert journal.get("sync_in_progress") is True
    assert manager.store.list_turns_for_thread(thread.id) == []

    monkeypatch.setattr(managed_worktree, "overlay_working_paths", real_overlay)
    recovered = await manager._prepare_isolated_workspace(failed)

    assert execution_root(recovered) == tree
    assert (tree / "app.py").read_text(encoding="utf-8") == "project two\n"
    assert (tree / "later.py").read_text(encoding="utf-8") == (
        "project later\n"
    )
    baseline = manager.store.load_worktree_baseline(thread.id)
    assert baseline is not None
    assert "sync_in_progress" not in baseline


@pytest.mark.asyncio
async def test_initial_sync_journal_makes_later_edit_recoverable(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("project two\n", encoding="utf-8")
    (repo / "later.py").write_text("project later\n", encoding="utf-8")
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    real_overlay = managed_worktree.overlay_working_paths

    def crash_after_first_path(
        source: Path, dest: Path, paths: list[str], **_kwargs
    ) -> None:
        managed_worktree._copy_raw(source, dest, sorted(paths)[0])
        raise OSError("simulated first sync failure")

    monkeypatch.setattr(
        managed_worktree, "overlay_working_paths", crash_after_first_path
    )
    with pytest.raises(OSError, match="simulated first sync failure"):
        await manager._prepare_isolated_workspace(thread)
    failed = manager.store.load_thread(thread.id)
    tree = execution_root(failed)
    (tree / "app.py").write_text("later task edit\n", encoding="utf-8")
    monkeypatch.setattr(managed_worktree, "overlay_working_paths", real_overlay)

    blocked = await manager._prepare_isolated_workspace(failed)

    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["app.py"]
    assert (tree / "app.py").read_text(encoding="utf-8") == "later task edit\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "project two\n"


@pytest.mark.asyncio
async def test_orphan_checkpoint_remains_a_publish_journal(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("orphan draft\n", encoding="utf-8")
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id="turn_orphan_publish",
            is_git=True,
            thread_id=thread.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "orphan draft\n"},
        )
    )

    refreshed = await manager._prepare_isolated_workspace(prepared)

    assert refreshed.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "orphan draft\n"
    checkpoint = manager.checkpoints.load("turn_orphan_publish")
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == repo.resolve()


@pytest.mark.asyncio
async def test_publish_keeps_checkpoint_provenance_until_resync_is_durable(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("task version\n", encoding="utf-8")
    turn_id = "turn_publish_crash"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=thread.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "task version\n"},
        )
    )
    real_sync = manager._sync_isolate_with_baseline

    async def crash_before_durable_sync(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("simulated crash before durable resync")

    monkeypatch.setattr(
        manager, "_sync_isolate_with_baseline", crash_before_durable_sync
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        await manager._publish_isolated_thread(prepared)

    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == repo.resolve()
    assert checkpoint.publish_pending_sync is True
    assert checkpoint.publish_apply_complete is True
    assert checkpoint.pre_contents["app.py"] == "one\n"
    assert [item.turn_id for item in manager._unpublished_checkpoints(prepared)] == [
        turn_id
    ]
    assert (repo / "app.py").read_text(encoding="utf-8") == "task version\n"

    monkeypatch.setattr(manager, "_sync_isolate_with_baseline", real_sync)
    published = await manager._publish_isolated_thread(
        manager.store.load_thread(thread.id)
    )
    assert published.publish_blocked is False
    checkpoint = manager.checkpoints.load(turn_id)
    assert checkpoint is not None
    assert Path(checkpoint.execution_root).resolve() == repo.resolve()
    assert checkpoint.publish_pending_sync is False
    assert checkpoint.publish_apply_complete is False
    assert checkpoint.pre_contents["app.py"] == "one\n"

    restored = await manager.checkpoints.restore([turn_id], repo)

    assert restored.restored == ["app.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"


@pytest.mark.asyncio
async def test_publish_retry_does_not_replay_older_completed_checkpoint(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("three\n", encoding="utf-8")
    for turn_id, created_at, pre, post in (
        ("turn_publish_one", 1.0, "one\n", "two\n"),
        ("turn_publish_two", 2.0, "two\n", "three\n"),
    ):
        _seed_turn(manager, prepared.id, turn_id)
        _save_checkpoint(manager,
            TurnCheckpoint(
                turn_id=turn_id,
                is_git=True,
                thread_id=thread.id,
                created_at=created_at,
                execution_root=str(tree),
                mutated=["app.py"],
                pre_contents={"app.py": pre},
                post_contents={"app.py": post},
            )
        )
    real_sync = manager._sync_isolate_with_baseline

    async def crash_before_durable_sync(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("simulated crash before durable resync")

    monkeypatch.setattr(
        manager, "_sync_isolate_with_baseline", crash_before_durable_sync
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        await manager._publish_isolated_thread(prepared)

    assert (repo / "app.py").read_text(encoding="utf-8") == "three\n"
    for turn_id in ("turn_publish_one", "turn_publish_two"):
        checkpoint = manager.checkpoints.load(turn_id)
        assert checkpoint is not None
        assert checkpoint.publish_pending_sync is True
        assert checkpoint.publish_apply_complete is True

    monkeypatch.setattr(manager, "_sync_isolate_with_baseline", real_sync)
    published = await manager._publish_isolated_thread(
        manager.store.load_thread(thread.id)
    )

    assert published.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "three\n"
    restored = await manager.checkpoints.restore(
        ["turn_publish_two", "turn_publish_one"], repo
    )
    assert restored.restored == ["app.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"


@pytest.mark.asyncio
async def test_restart_clears_request_left_after_final_publish_sync(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("published once\n", encoding="utf-8")
    turn_id = "turn_crash_after_sync"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(
        manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "published once\n"},
        ),
    )
    prepared.publish_pending = True
    prepared.publish_request_action = "apply"
    prepared.publish_request_paths = ["app.py"]
    prepared.publish_waiting_on = "thread_old_sibling"
    manager.store.save_thread(prepared)
    real_save_thread = manager.store.save_thread

    def crash_before_thread_state_save(record) -> None:
        if record.id == prepared.id and not manager._unpublished_checkpoints(record):
            raise RuntimeError("simulated crash after final checkpoint sync")
        real_save_thread(record)

    monkeypatch.setattr(manager.store, "save_thread", crash_before_thread_state_save)

    with pytest.raises(RuntimeError, match="after final checkpoint sync"):
        await manager._publish_isolated_thread(prepared)

    monkeypatch.setattr(manager.store, "save_thread", real_save_thread)
    stale = manager.store.load_thread(prepared.id)
    assert stale.publish_pending is True
    assert stale.publish_request_action == "apply"
    assert manager._unpublished_checkpoints(stale) == []
    assert (repo / "app.py").read_text(encoding="utf-8") == "published once\n"

    manager.shutdown()
    restarted = manager.__class__(
        manager.config,
        manager.workspace,
        manager.manager_cfg,
        llm_client=manager._llm_client,
    )
    try:
        reconciled = restarted.store.load_thread(prepared.id)
        assert reconciled.publish_pending is False
        assert reconciled.publish_request_action is None
        assert reconciled.publish_request_paths == []
        assert reconciled.publish_waiting_on is None

        ready = await restarted._prepare_isolated_workspace(reconciled)
        assert ready.publish_pending is False
        assert ready.publish_blocked is False
        assert restarted._unpublished_checkpoints(ready) == []
        assert (repo / "app.py").read_text(encoding="utf-8") == "published once\n"
    finally:
        restarted.shutdown()


@pytest.mark.asyncio
async def test_restart_finishes_publish_when_checkpoint_sync_clear_was_partial(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("three\n", encoding="utf-8")
    turn_ids = ["turn_partial_sync_one", "turn_partial_sync_two"]
    for turn_id, created_at, pre, post in (
        (turn_ids[0], 1.0, "one\n", "two\n"),
        (turn_ids[1], 2.0, "two\n", "three\n"),
    ):
        _seed_turn(manager, prepared.id, turn_id)
        _save_checkpoint(
            manager,
            TurnCheckpoint(
                turn_id=turn_id,
                is_git=True,
                thread_id=prepared.id,
                created_at=created_at,
                execution_root=str(tree),
                mutated=["app.py"],
                pre_contents={"app.py": pre},
                post_contents={"app.py": post},
            ),
        )
    prepared.publish_pending = True
    prepared.publish_request_action = "apply"
    manager.store.save_thread(prepared)
    real_mark_synced = manager.checkpoints.mark_publish_synced
    cleared = 0

    def crash_after_first_clear(turn_id: str) -> None:
        nonlocal cleared
        real_mark_synced(turn_id)
        cleared += 1
        if cleared == 1:
            raise RuntimeError("simulated crash during checkpoint clear")

    monkeypatch.setattr(
        manager.checkpoints, "mark_publish_synced", crash_after_first_clear
    )

    with pytest.raises(RuntimeError, match="during checkpoint clear"):
        await manager._publish_isolated_thread(prepared)

    monkeypatch.setattr(manager.checkpoints, "mark_publish_synced", real_mark_synced)
    stale = manager.store.load_thread(prepared.id)
    assert stale.publish_pending is True
    assert len(manager._unpublished_checkpoints(stale)) == 1
    assert (repo / "app.py").read_text(encoding="utf-8") == "three\n"

    manager.shutdown()
    restarted = manager.__class__(
        manager.config,
        manager.workspace,
        manager.manager_cfg,
        llm_client=manager._llm_client,
    )
    try:
        still_pending = restarted.store.load_thread(prepared.id)
        assert still_pending.publish_pending is True
        assert len(restarted._unpublished_checkpoints(still_pending)) == 1

        completed = await restarted._publish_isolated_thread(still_pending)

        assert completed.publish_pending is False
        assert completed.publish_blocked is False
        assert restarted._unpublished_checkpoints(completed) == []
        assert (repo / "app.py").read_text(encoding="utf-8") == "three\n"
    finally:
        restarted.shutdown()


@pytest.mark.asyncio
async def test_missing_worktree_state_revalidates_when_path_returns(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    offline = tree.with_name(f"{tree.name}-offline")
    tree.rename(offline)
    prepared.publish_pending = True
    prepared.publish_blocked = True
    prepared.publish_issue = "failure"
    manager.store.save_thread(prepared)

    manager._reconcile_missing_worktrees_on_boot()
    missing = manager.store.load_thread(thread.id)
    assert missing.publish_issue == "missing"

    offline.rename(tree)
    recovered = await manager._prepare_isolated_workspace(missing)

    assert recovered.publish_pending is False
    assert recovered.publish_blocked is False
    assert recovered.publish_issue is None


@pytest.mark.asyncio
async def test_prepare_preserves_association_when_worktree_disappears_at_runtime(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    offline = tree.with_name(f"{tree.name}-offline")
    (tree / "only-in-task.txt").write_text("preserve me\n", encoding="utf-8")
    tree.rename(offline)

    missing = await manager._prepare_isolated_workspace(prepared)

    assert missing.env_mode == "worktree"
    assert missing.worktree_path == str(tree)
    assert missing.associated_worktree_path == str(tree)
    assert missing.publish_pending is True
    assert missing.publish_blocked is True
    assert missing.publish_issue == "missing"
    assert not tree.exists()
    assert (offline / "only-in-task.txt").read_text(encoding="utf-8") == "preserve me\n"

    offline.rename(tree)
    recovered = await manager._prepare_isolated_workspace(missing)

    assert recovered.worktree_path == str(tree)
    assert recovered.publish_issue == "recovery"
    assert recovered.publish_blocked is True
    assert (tree / "only-in-task.txt").read_text(encoding="utf-8") == "preserve me\n"


@pytest.mark.asyncio
async def test_uncheckpointed_isolate_labor_can_keep_project(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("uncheckpointed-agent\n", encoding="utf-8")
    (repo / "app.py").write_text("from-editor\n", encoding="utf-8")

    prepared = await manager._prepare_isolated_workspace(prepared)

    resolved = await manager.resolve_publish_conflicts(
        thread.id, action="keep_project"
    )
    assert resolved.publish_blocked is False
    assert resolved.publish_conflicts == []
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-editor\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == "from-editor\n"


@pytest.mark.asyncio
async def test_publish_waits_while_sibling_turn_is_active(
    runtime_app, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    first = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    second = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(first)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("from-agent\n", encoding="utf-8")
    turn_id = "turn_busy"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "from-agent\n"},
        )
    )
    async with manager._active_lock:
        manager._active[second.id] = SimpleNamespace(
            active_turn=SimpleNamespace(turn_id="turn_other")
        )
    skipped = await manager._publish_isolated_thread(prepared)
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    assert skipped.publish_blocked is False
    async with manager._active_lock:
        manager._active.pop(second.id, None)
    published = await manager._publish_isolated_thread(prepared)
    assert published.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "from-agent\n"


@pytest.mark.asyncio
async def test_completed_isolated_labor_auto_publishes(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("draft\n", encoding="utf-8")
    turn_id = "turn_auto_publish"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "draft\n"},
        )
    )

    await manager._after_turn_released(prepared.id)

    persisted = manager.store.load_thread(prepared.id)
    assert persisted.publish_pending is False
    assert persisted.publish_blocked is False
    assert persisted.publish_request_action is None
    assert (repo / "app.py").read_text(encoding="utf-8") == "draft\n"


@pytest.mark.parametrize(
    ("action", "expected_app", "expected_binary"),
    [
        ("use_agent", "late background\n", b"\0late"),
        ("keep_project", "one\n", None),
    ],
)
@pytest.mark.asyncio
async def test_auto_publish_recovers_labor_changed_after_checkpoint(
    runtime_app,
    tmp_path: Path,
    action: str,
    expected_app: str,
    expected_binary: bytes | None,
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("checkpoint\n", encoding="utf-8")
    (tree / "asset.bin").write_bytes(b"\0checkpoint")
    turn_id = f"turn_late_{action}"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py", "asset.bin"],
            pre_contents={"app.py": "one\n", "asset.bin": None},
        )
    )
    manager.checkpoints.record_post_images(turn_id, tree)
    captured = manager.checkpoints.load(turn_id)
    assert captured is not None
    assert set(captured.post_signatures) == {"app.py", "asset.bin"}
    checkpoint_signatures = dict(captured.post_signatures)

    # These writes land after turn-end capture and therefore do not belong to
    # the checkpoint that automatic publish is about to replay.
    (tree / "app.py").write_text("late background\n", encoding="utf-8")
    (tree / "asset.bin").write_bytes(b"\0late")

    await manager._after_turn_released(prepared.id)

    blocked = manager.store.load_thread(prepared.id)
    assert blocked.publish_pending is True
    assert blocked.publish_blocked is True
    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["app.py", "asset.bin"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    assert not (repo / "asset.bin").exists()
    assert (tree / "app.py").read_text(encoding="utf-8") == "late background\n"
    assert (tree / "asset.bin").read_bytes() == b"\0late"
    captured = manager.checkpoints.load(turn_id)
    assert captured is not None
    assert Path(captured.execution_root).resolve() == tree.resolve()
    assert captured.publish_pending_sync is False
    assert captured.publish_apply_complete is False

    resolved = await manager.resolve_publish_conflicts(
        prepared.id, action=action
    )

    assert resolved.publish_pending is False
    assert resolved.publish_blocked is False
    assert (repo / "app.py").read_text(encoding="utf-8") == expected_app
    if expected_binary is None:
        assert not (repo / "asset.bin").exists()
    else:
        assert (repo / "asset.bin").read_bytes() == expected_binary
    captured = manager.checkpoints.load(turn_id)
    assert captured is not None
    assert Path(captured.execution_root).resolve() == repo.resolve()
    if action == "keep_project":
        assert captured.mutated == []
        assert captured.post_signatures == {}
    else:
        assert captured.post_signatures == checkpoint_signatures
    assert manager._unpublished_checkpoints(resolved) == []

    await manager._after_turn_released(prepared.id)

    assert (repo / "app.py").read_text(encoding="utf-8") == expected_app
    if expected_binary is None:
        assert not (repo / "asset.bin").exists()
    else:
        assert (repo / "asset.bin").read_bytes() == expected_binary


@pytest.mark.asyncio
async def test_publish_sync_does_not_resolve_mutation_after_preflight(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("checkpoint\n", encoding="utf-8")
    turn_id = "turn_late_during_publish"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
        )
    )
    manager.checkpoints.record_post_images(turn_id, tree)
    real_sync = manager._sync_isolate_with_baseline
    injected = False

    async def mutate_before_sync(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            (tree / "app.py").write_text("late during publish\n", encoding="utf-8")
        return await real_sync(*args, **kwargs)

    monkeypatch.setattr(manager, "_sync_isolate_with_baseline", mutate_before_sync)

    await manager._after_turn_released(prepared.id)

    blocked = manager.store.load_thread(prepared.id)
    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["app.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "checkpoint\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == (
        "late during publish\n"
    )

    resolved = await manager.resolve_publish_conflicts(
        prepared.id, action="use_agent"
    )

    assert (repo / "app.py").read_text(encoding="utf-8") == (
        "late during publish\n"
    )
    assert manager._unpublished_checkpoints(resolved) == []


@pytest.mark.asyncio
async def test_legacy_checkpoint_post_image_rejects_late_edit(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("late legacy\n", encoding="utf-8")
    turn_id = "turn_legacy_late_edit"
    _seed_turn(manager, prepared.id, turn_id)
    manager.checkpoints._save(
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "checkpoint\n"},
            post_modes={"app.py": 0o644},
            post_signatures_captured=False,
        )
    )

    await manager._after_turn_released(prepared.id)

    blocked = manager.store.load_thread(prepared.id)
    assert blocked.publish_issue == "recovery"
    assert blocked.publish_conflicts == ["app.py"]
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"
    assert (tree / "app.py").read_text(encoding="utf-8") == "late legacy\n"


@pytest.mark.asyncio
async def test_auto_publish_queues_behind_active_sibling_and_retries(
    runtime_app, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    draft_thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    active_thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(draft_thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("queued-auto\n", encoding="utf-8")
    turn_id = "turn_queued_auto"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "queued-auto\n"},
        )
    )
    async with manager._active_lock:
        manager._active[active_thread.id] = SimpleNamespace(
            active_turn=SimpleNamespace(turn_id="turn_other")
        )

    await manager._after_turn_released(prepared.id)

    queued = manager.store.load_thread(prepared.id)
    assert queued.publish_request_action == "apply"
    assert queued.publish_waiting_on == active_thread.id
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    async with manager._active_lock:
        manager._active.pop(active_thread.id, None)
    await manager._after_turn_released(active_thread.id)

    applied = manager.store.load_thread(prepared.id)
    assert applied.publish_pending is False
    assert applied.publish_request_action is None
    assert applied.publish_waiting_on is None
    assert (repo / "app.py").read_text(encoding="utf-8") == "queued-auto\n"


@pytest.mark.asyncio
async def test_auto_publish_failure_keeps_draft_and_can_retry(
    runtime_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("safe-draft\n", encoding="utf-8")
    turn_id = "turn_publish_failure"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "safe-draft\n"},
        )
    )
    request_publish_action = manager.request_publish_action

    async def fail_publish(*args, **kwargs):
        del args, kwargs
        raise OSError("temporary publish failure")

    monkeypatch.setattr(manager, "request_publish_action", fail_publish)
    await manager._after_turn_released(prepared.id)

    failed = manager.store.load_thread(prepared.id)
    assert failed.publish_pending is True
    assert failed.publish_blocked is True
    assert failed.publish_issue == "failure"
    assert failed.publish_conflicts == []
    assert (tree / "app.py").read_text(encoding="utf-8") == "safe-draft\n"
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    monkeypatch.setattr(manager, "request_publish_action", request_publish_action)
    result = await manager.request_publish_action(prepared.id, action="apply")

    assert result["status"] == "applied"
    assert (repo / "app.py").read_text(encoding="utf-8") == "safe-draft\n"


@pytest.mark.asyncio
async def test_apply_endpoint_reports_applied_and_updates_project(
    runtime_app, client: AsyncClient, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("draft\n", encoding="utf-8")
    turn_id = "turn_apply_endpoint"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "draft\n"},
        )
    )

    response = await client.post(
        f"/v1/threads/{prepared.id}/worktree/resolve",
        json={"action": "apply"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    assert response.json()["thread"]["publish_pending"] is False
    assert (repo / "app.py").read_text(encoding="utf-8") == "draft\n"


@pytest.mark.asyncio
async def test_apply_endpoint_queues_behind_active_sibling_and_retries(
    runtime_app, client: AsyncClient, tmp_path: Path
) -> None:
    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    draft_thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    active_thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(draft_thread)
    tree = execution_root(prepared)
    (tree / "app.py").write_text("queued-draft\n", encoding="utf-8")
    turn_id = "turn_queued_apply"
    _seed_turn(manager, prepared.id, turn_id)
    _save_checkpoint(manager,
        TurnCheckpoint(
            turn_id=turn_id,
            is_git=True,
            thread_id=prepared.id,
            created_at=1.0,
            execution_root=str(tree),
            mutated=["app.py"],
            pre_contents={"app.py": "one\n"},
            post_contents={"app.py": "queued-draft\n"},
        )
    )
    async with manager._active_lock:
        manager._active[active_thread.id] = SimpleNamespace(
            active_turn=SimpleNamespace(turn_id="turn_other")
        )

    response = await client.post(
        f"/v1/threads/{prepared.id}/worktree/resolve",
        json={"action": "apply"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    queued = manager.store.load_thread(prepared.id)
    assert queued.publish_request_action == "apply"
    assert queued.publish_waiting_on == active_thread.id
    assert (repo / "app.py").read_text(encoding="utf-8") == "one\n"

    async with manager._active_lock:
        manager._active.pop(active_thread.id, None)
    await manager._after_turn_released(active_thread.id)

    applied = manager.store.load_thread(prepared.id)
    assert applied.publish_pending is False
    assert applied.publish_request_action is None
    assert applied.publish_waiting_on is None
    assert (repo / "app.py").read_text(encoding="utf-8") == "queued-draft\n"


@pytest.mark.asyncio
async def test_idle_reclaim_removes_clean_worktree_and_keeps_thread(
    runtime_app, tmp_path: Path
) -> None:
    from datetime import timedelta

    from deepseek_tui.server.threads.manager import IDLE_WORKTREE_RECLAIM_AFTER

    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    thread = await manager.create_thread(
        CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
    )
    prepared = await manager._prepare_isolated_workspace(thread)
    tree = execution_root(prepared)
    assert tree.is_dir()

    prepared.updated_at = datetime.now(timezone.utc) - (
        IDLE_WORKTREE_RECLAIM_AFTER + timedelta(hours=1)
    )
    manager.store.save_thread(prepared)

    removed = await manager.reclaim_idle_worktrees()

    assert removed == 1
    assert not tree.exists()
    reloaded = manager.store.load_thread(prepared.id)
    assert reloaded.archived is False
    assert reloaded.worktree_path is None
    assert reloaded.env_mode == "local"

    # Resuming the thread rebuilds the worktree from the project.
    resumed = await manager._prepare_isolated_workspace(reloaded)
    assert execution_root(resumed).is_dir()


@pytest.mark.asyncio
async def test_idle_reclaim_keeps_recent_and_unpublished_worktrees(
    runtime_app, tmp_path: Path
) -> None:
    from datetime import timedelta

    from deepseek_tui.server.threads.manager import IDLE_WORKTREE_RECLAIM_AFTER

    manager = runtime_app.state.thread_manager
    repo = _repo(tmp_path)
    recent = await manager._prepare_isolated_workspace(
        await manager.create_thread(
            CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
        )
    )
    stale = await manager._prepare_isolated_workspace(
        await manager.create_thread(
            CreateThreadRequest(workspace=str(repo), model="deepseek-chat")
        )
    )
    (execution_root(stale) / "app.py").write_text(
        "unpublished\n", encoding="utf-8"
    )
    stale.publish_blocked = True
    stale.updated_at = datetime.now(timezone.utc) - (
        IDLE_WORKTREE_RECLAIM_AFTER + timedelta(hours=1)
    )
    manager.store.save_thread(stale)

    removed = await manager.reclaim_idle_worktrees()

    assert removed == 0
    assert execution_root(recent).is_dir()
    assert execution_root(stale).is_dir()
