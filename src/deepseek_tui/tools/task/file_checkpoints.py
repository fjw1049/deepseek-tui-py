"""Durable file-tool undo for detached tasks; shell effects are not captured."""

from pathlib import Path
from typing import Any

from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpointStore


def checkpoint_store(data_dir: Path, task_id: str) -> TurnCheckpointStore:
    TurnCheckpointStore._validate_id(task_id)
    return TurnCheckpointStore(data_dir / "file-checkpoints" / task_id)


def restore_marker(data_dir: Path, task_id: str) -> Path:
    TurnCheckpointStore._validate_id(task_id)
    return data_dir / "file-restores" / f"{task_id}.json"


class TaskFileCheckpoints:
    def __init__(self, data_dir: Path, task_id: str, workspace: Path) -> None:
        if restore_marker(data_dir, task_id).exists():
            raise ValueError("Task file restoration started; a new task is required")
        self.workspace = workspace.resolve()
        self.store = checkpoint_store(data_dir, task_id)
        # One journal per logical task, including all resume attempts. This
        # preserves the very first bytes when a later attempt sees UTF-8 output
        # from a task that originally replaced a GBK file.
        self.turn_id = task_id
        existing = self.store.load(self.turn_id)
        if existing is not None:
            if existing.execution_root != str(self.workspace) or existing.thread_id != task_id:
                raise ValueError("Task checkpoint workspace or owner changed")
        elif self.store._path(self.turn_id).exists():
            raise ValueError("Task checkpoint is unreadable")
        else:
            self.store.begin_turn(
                self.turn_id,
                None,
                head=None,
                is_git=False,
                thread_id=task_id,
                execution_root=str(self.workspace),
                tool_writes_only=True,
            )

    def bind(self, context: ToolContext) -> None:
        def relative(path: str) -> str | None:
            target = Path(path)
            if not target.is_absolute():
                target = context.working_directory / target
            try:
                return target.resolve().relative_to(self.workspace).as_posix()
            except ValueError:
                # Trusted tasks retain their existing outside-workspace authority,
                # but those writes are explicitly outside this undo contract.
                return None

        def capture(path: str, before: str | bytes | None) -> None:
            rel = relative(path)
            if rel is None:
                return
            try:
                if self.store.load(self.turn_id) is None:
                    raise OSError("task checkpoint is missing or unreadable")
                self.store.record_pre_write(self.turn_id, rel, before)
            except Exception as exc:
                raise ToolError("Cannot checkpoint file; write was not started") from exc

        def record(mutation: dict[str, Any]) -> None:
            if "_before_content" not in mutation or "_after_content" not in mutation:
                return
            rel = relative(mutation["path"])
            if rel is None:
                return
            try:
                if self.store.load(self.turn_id) is None:
                    raise OSError("task checkpoint is missing or unreadable")
                self.store.record_tool_write(
                    self.turn_id,
                    rel,
                    mutation["_before_content"],
                    mutation["_after_content"],
                    capture_post_image=True,
                )
            except Exception as exc:
                raise ToolError(
                    "File was written, but its undo record could not be completed"
                ) from exc

        context.pre_write_capture = capture
        context.on_file_mutation = record
