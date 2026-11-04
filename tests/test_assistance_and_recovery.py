"""Recovery must preserve identity and remain resumable across runtime boundaries."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from deepseek_tui.engine.completion import TurnFacts
from deepseek_tui.engine.dispatch import _collect_turn_events
from deepseek_tui.engine.events import TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.browser import BrowserUseTool
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig, TaskStatus
from deepseek_tui.tools.task.store import _task_record_from_dict
from deepseek_tui.tools.task.tools import TaskCreateTool


async def test_background_assistance_is_durable_non_success_and_resumable(tmp_path):
    handle = EngineHandle()
    outcome = {"status": "needs_assistance", "requests": [{"reason": "login"}]}
    await handle.emit(
        TurnCompleteEvent(
            assistant_message=Message.assistant("Needs human input"), task_outcome=outcome
        )
    )
    result = await _collect_turn_events(handle, asyncio.Event())
    assert result.error and result.task_outcome == outcome

    async def executor(*args):
        return result

    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "data", default_workspace=tmp_path), executor=executor
    )
    try:
        record = await manager.add_task(NewTaskRequest(prompt="Read private report"))
        await manager._run_task_and_finalize(record.id, None, asyncio.Event())
        loaded = _task_record_from_dict(
            json.loads((tmp_path / "data/tasks" / f"{record.id}.json").read_text())
        )
        assert loaded.status is TaskStatus.FAILED
        assert loaded.status.is_resumable()
        assert loaded.task_outcome == outcome
        from deepseek_tui.server.runtime import _task_record_to_dict, _task_summary_to_dict

        assert _task_record_to_dict(loaded)["task_outcome"] == outcome
        assert _task_summary_to_dict(loaded.summary())["task_outcome"] == outcome
        with pytest.raises(ToolError, match="Tasks panel"):
            await TaskCreateTool().execute(
                {"resume": record.id}, ToolContext(working_directory=tmp_path, task_manager=manager)
            )
        await manager.resume_task(record.id)
        assert record.status is TaskStatus.QUEUED
        assert record.task_outcome is None
    finally:
        await manager.shutdown()


def test_identical_wait_can_recover_with_a_longer_timeout():
    f = TurnFacts()
    f.record(
        "browser_use",
        {"action": "wait", "text": "Ready", "timeout_ms": 100},
        success=False,
        error="timed out",
    )
    f.record("browser_use", {"action": "wait", "text": "Ready", "timeout_ms": 500}, success=True)
    assert not f.failures


@pytest.mark.parametrize(
    "different_page,different_target", [(False, False), (True, False), (False, True)]
)
async def test_runtime_target_identity_survives_ref_changes(
    tmp_path, different_page, different_target
):
    run = SimpleNamespace(latest_observation={})

    class Browser:
        runs = {"thread": run}
        calls = 0

        async def action(self, thread, action, **kwargs):
            self.calls += 1
            # Post-action navigation must not change the identity of what was clicked.
            run.latest_observation = {"document_id": "after-action"}
            return {"success": self.calls > 1, "content": "done" if self.calls > 1 else "obscured"}

    context = ToolContext(
        working_directory=tmp_path,
        metadata={"browser_service": Browser(), "runtime_thread_id": "thread"},
    )
    facts = TurnFacts()
    for i in range(2):
        run.latest_observation = {
            "tab_id": "tab",
            "document_id": "other" if i and different_page else "doc",
            "elements": [
                {"ref": f"e{i}", "target_id": "other" if i and different_target else "node"}
            ],
        }
        args = {"action": "click", "ref": f"e{i}", "observation_id": f"obs{i}"}
        result = await BrowserUseTool().execute(args, context)
        facts.record(
            "browser_use",
            args,
            success=result.success,
            error=result.content,
            metadata=result.metadata,
        )
    assert bool(facts.failures) == (different_page or different_target)


def test_success_on_a_different_page_does_not_clear_wait():
    f = TurnFacts()
    for document, success in [("one", False), ("two", True)]:
        f.record(
            "browser_use",
            {"action": "wait", "text": "Ready"},
            success=success,
            metadata={"browser_before": {"document_id": document}},
        )
    assert f.failures
