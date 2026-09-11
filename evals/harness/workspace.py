"""Real Engine loop with production file tools in a disposable, bounded workspace.

This target measures file-task outcomes, not shell execution, desktop lifecycle,
MCP or subagents. No fixture assertions or reference outputs enter the workspace.
"""

from __future__ import annotations

import asyncio
import dataclasses
import difflib
import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.engine.events import EngineEvent, ThinkingDeltaEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.prompts import AppMode, build_system_prompt
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.file import EditFileTool, ReadFileTool, WriteFileTool
from deepseek_tui.tools.registry import ToolContext, ToolRegistry
from evals.harness.budget import BudgetedClient
from evals.schema import EvalCase, EvalObservation

if TYPE_CHECKING:
    from evals.harness import HarnessContext


class FixtureContext(ToolContext):
    def resolve_path(self, path: str, *, allow_read_roots: bool = False) -> Path:
        # Even read-only spillover/user-data exceptions are inappropriate here.
        resolved = super().resolve_path(path, allow_read_roots=False)
        if not resolved.is_relative_to(self.working_directory.resolve()):
            raise ValueError("eval tools may only access the trial workspace")
        return resolved


class RecordingHandle(EngineHandle):
    def __init__(self, context: HarnessContext) -> None:
        super().__init__()
        self.context = context

    async def emit(self, event: EngineEvent) -> None:
        self.try_emit(event)

    def try_emit(self, event: EngineEvent) -> bool:
        if not isinstance(event, ThinkingDeltaEvent):
            payload = json.loads(
                json.dumps(
                    dataclasses.asdict(event),
                    default=lambda x: (
                        x.model_dump(mode="json") if hasattr(x, "model_dump") else str(x)
                    ),
                )
            )
            self.context.trace.append({"type": type(event).__name__, **payload})
        return True


def verify_files(case: EvalCase, files: dict[str, str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for path, expected in case.expect.get("json_files", {}).items():
        try:
            actual = json.loads(files[path])
        except (KeyError, ValueError):
            actual = None
        checks.append(
            {
                "name": f"JSON 内容：{path}",
                "passed": actual == expected,
                "expected": expected,
                "actual": actual,
            }
        )
    for path in case.expect.get("unchanged", []):
        checks.append(
            {"name": f"保留原文件：{path}", "passed": files.get(path) == case.setup["files"][path]}
        )
    allowed = set(case.setup["files"]) | set(case.expect.get("json_files", {}))
    checks.append(
        {
            "name": "没有额外文件",
            "passed": not (set(files) - allowed),
            "actual": sorted(set(files) - allowed),
        }
    )
    return checks


def snapshot_files(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in root.rglob("*")
        if p.is_file()
    }


async def run_workspace_task(case: EvalCase, context: HarnessContext) -> EvalObservation:
    if not case.setup.get("files") or not case.expect.get("json_files"):
        raise ValueError("workspace task needs fixture files and independent JSON assertions")
    cfg = ConfigLoader().load(
        provider=context.provider,
        model=context.model,
        workspace=Path(context.workspace),
        no_project_config=True,
    )
    client = BudgetedClient(build_llm_client(cfg), context)
    try:
        with tempfile.TemporaryDirectory(prefix="deepseek-eval-task-") as tmp:
            root = Path(tmp)
            tool_context = FixtureContext(working_directory=root)
            for name, content in case.setup["files"].items():
                path = tool_context.resolve_path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            registry = ToolRegistry()
            registry.register_all([ReadFileTool(), WriteFileTool(), EditFileTool()])
            handle = RecordingHandle(context)
            engine = Engine(
                handle=handle,
                client=client,
                tool_registry=registry,
                tool_context=tool_context,
                max_tool_round_trips=12,
                default_model=cfg.model or cfg.default_text_model,
                default_temperature=0.0,
            )
            prompt = build_system_prompt(
                mode=AppMode.AGENT, workspace=root, project_context_enabled=False
            )
            if context.prompt_suffix:
                prompt += "\n\n" + context.prompt_suffix
            messages = [Message.user(str(case.input["prompt"]))]
            # Use the production conversation/dispatch/compaction loop without
            # desktop persistence, user hooks, plugin discovery or background jobs.
            result = await engine._run_conversation(
                messages, engine.default_model, prompt, context.max_output_tokens
            )
            files = await asyncio.to_thread(snapshot_files, root)
            checks = verify_files(case, files)
            checks.append({"name": "Agent 正常结束", "passed": result.outcome.value == "success"})
            diffs = {}
            for filename in sorted(set(case.setup["files"]) | set(files)):
                before = case.setup["files"].get(filename, "")
                after = files.get(filename, "")
                if before != after:
                    diffs[filename] = "".join(
                        difflib.unified_diff(
                            before.splitlines(keepends=True),
                            after.splitlines(keepends=True),
                            fromfile=f"before/{filename}",
                            tofile=f"after/{filename}",
                        )
                    )
            return EvalObservation(
                data={
                    "checks": checks,
                    "files": files,
                    "diffs": diffs,
                    "assistant_text": result.assistant_message.text_content()
                    if result.assistant_message
                    else "",
                    "target": "restricted_file_engine",
                },
                evidence=["真实 Engine 工具循环；独立文件验收；临时工作区；仅文件工具"],
            )
    finally:
        await client.close()
