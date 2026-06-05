"""Execute Workflow IR."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from deepseek_tui.tools.subagent.manager import SubAgentManager
from deepseek_tui.workflow.agent_runner import WorkflowRunner
from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    FanoutStep,
    PipelineStep,
    StepOutput,
    SynthesisStep,
    WorkflowAbortedError,
    WorkflowAgentRun,
    WorkflowFailedError,
    WorkflowRunContext,
    WorkflowRunResult,
    WorkflowSnapshot,
    WorkflowSpec,
    WorkflowStepError,
)
from deepseek_tui.workflow.template import make_step_output, render_template


def _recompute_snapshot(snapshot: WorkflowSnapshot) -> WorkflowSnapshot:
    running = sum(1 for a in snapshot.agents if a.status == "running")
    done = sum(1 for a in snapshot.agents if a.status == "done")
    errors = sum(1 for a in snapshot.agents if a.status == "error")
    return replace(
        snapshot,
        agent_count=len(snapshot.agents),
        running_count=running,
        done_count=done,
        error_count=errors,
    )


def _json_serializable(value: Any) -> None:
    json.dumps(value)


def _collect_errors(snapshot: WorkflowSnapshot) -> list[WorkflowStepError]:
    return [
        WorkflowStepError(step_id=a.step_id, error=a.error or "unknown")
        for a in snapshot.agents
        if a.status == "error"
    ]


async def _cancel_spawned(manager: SubAgentManager, agent_ids: list[str]) -> None:
    for agent_id in list(agent_ids):
        try:
            await manager.cancel(agent_id)
        except KeyError:
            pass


async def run_workflow(
    spec: WorkflowSpec,
    *,
    runner: WorkflowRunner,
    cancel_event: asyncio.Event | None = None,
    manager: SubAgentManager | None = None,
    on_log: Callable[[str], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
    on_progress: Callable[[WorkflowSnapshot], None] | None = None,
) -> WorkflowRunResult:
    started = time.monotonic()
    ctx = WorkflowRunContext()
    snapshot = WorkflowSnapshot(
        name=spec.meta.name,
        description=spec.meta.description,
    )
    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(msg)
        snapshot.logs.append(msg)
        if on_log:
            on_log(msg)

    def progress() -> None:
        if on_progress:
            on_progress(_recompute_snapshot(snapshot))

    def check_cancel() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise WorkflowAbortedError("workflow cancelled")

    async def cancel_pending(tasks: set[asyncio.Task[StepOutput | None]]) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def gather_step_outputs(
        *,
        step_id: str,
        indexed_items: list[tuple[int, str]],
        worker: Callable[[str], Awaitable[StepOutput | None]],
    ) -> list[tuple[str, StepOutput]]:
        tasks: dict[asyncio.Task[StepOutput | None], tuple[int, str]] = {
            asyncio.create_task(worker(item)): (idx, item)
            for idx, item in indexed_items
        }
        pending: set[asyncio.Task[StepOutput | None]] = set(tasks)
        outputs: dict[int, tuple[str, StepOutput]] = {}

        def _suppress_unretreived() -> None:
            for t in tasks:
                if t.done() and not t.cancelled():
                    try:
                        t.exception()
                    except (asyncio.CancelledError, BaseException):
                        pass

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    idx, item = tasks[task]
                    try:
                        result = task.result()
                    except asyncio.CancelledError:
                        raise WorkflowAbortedError("workflow cancelled") from None
                    except WorkflowAbortedError:
                        await cancel_pending(pending)
                        raise
                    except Exception as exc:  # noqa: BLE001
                        log(f"{step_id}[{item}]: {exc}")
                        if spec.policy.on_error == "fail_fast":
                            await cancel_pending(pending)
                            raise WorkflowFailedError(
                                f"{step_id}[{item}] failed: {exc}"
                            ) from exc
                        continue
                    if result is None:
                        log(f"{step_id}[{item}]: agent failed")
                        if spec.policy.on_error == "fail_fast":
                            await cancel_pending(pending)
                            raise WorkflowFailedError(
                                f"{step_id}[{item}] failed"
                            )
                        continue
                    outputs[idx] = (item, result)
        except BaseException:
            await cancel_pending(pending)
            _suppress_unretreived()
            raise
        return [outputs[idx] for idx in sorted(outputs)]

    async def run_step(
        step_id: str,
        label: str,
        phase_id: str,
        coro: Awaitable[StepOutput | None],
    ) -> StepOutput | None:
        check_cancel()
        run = WorkflowAgentRun(
            step_id=step_id,
            label=label,
            phase_id=phase_id,
            status="running",
        )
        snapshot.agents.append(run)
        progress()
        try:
            out = await coro
        except WorkflowAbortedError:
            run.status = "skipped"
            run.error = "aborted"
            progress()
            raise
        except Exception as exc:  # noqa: BLE001
            run.status = "error"
            run.error = str(exc)
            log(f"step {step_id} failed: {exc}")
            progress()
            if spec.policy.on_error == "fail_fast":
                raise WorkflowFailedError(str(exc)) from exc
            return None
        if out is None:
            run.status = "error"
            run.error = "agent failed"
            progress()
            if spec.policy.on_error == "fail_fast":
                raise WorkflowFailedError(f"step {step_id} failed")
            return None
        run.status = "done"
        run.result_preview = out.preview
        progress()
        return out

    async def run_agent_cfg(
        cfg: AgentStepConfig,
        *,
        item: str | None = None,
        previous: StepOutput | None = None,
        phase_id: str,
        step_id: str,
    ) -> StepOutput | None:
        if len(ctx.spawned_agent_ids) >= spec.policy.max_agents:
            raise WorkflowFailedError(
                f"max_agents limit ({spec.policy.max_agents}) reached at step {step_id}"
            )
        label = cfg.label or (
            render_template(cfg.label_template or "agent", item=item)
            if cfg.label_template
            else step_id
        )
        prompt = cfg.prompt or render_template(
            cfg.prompt_template or "",
            item=item,
            previous=previous,
            outputs=ctx.outputs,
        )
        if not prompt.strip():
            return None
        def _on_agent_id(aid: str) -> None:
            ctx.spawned_agent_ids.append(aid)
            for run in reversed(snapshot.agents):
                if run.step_id == step_id and run.agent_id is None:
                    run.agent_id = aid
                    break

        out = await runner.run(
            prompt=prompt,
            label=label,
            agent_type=cfg.agent_type,
            model=cfg.model,
            allowed_tools=cfg.allowed_tools,
            output_schema=cfg.output_schema,
            policy=spec.policy,
            cancel_event=cancel_event,
            on_agent_id=_on_agent_id,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise WorkflowAbortedError("workflow cancelled")
        return out

    try:
        for phase in spec.phases:
            check_cancel()
            if phase.id not in snapshot.phases:
                snapshot.phases.append(phase.id)
            snapshot.current_phase = phase.title
            if on_phase:
                on_phase(phase.title)
            progress()

            for step in phase.steps:
                check_cancel()
                if step.type == "agent":
                    assert isinstance(step, AgentStep)

                    async def _agent_coro(
                        s: AgentStep = step,
                        phase_id: str = phase.id,
                    ) -> StepOutput | None:
                        return await run_agent_cfg(
                            AgentStepConfig(
                                label=s.label,
                                agent_type=s.agent_type,
                                model=s.model,
                                allowed_tools=s.allowed_tools,
                                prompt=s.prompt,
                                output_schema=s.output_schema,
                            ),
                            phase_id=phase_id,
                            step_id=s.id,
                        )

                    out = await run_step(step.id, step.label, phase.id, _agent_coro())
                    if out is not None:
                        ctx.outputs[step.id] = out

                elif step.type == "fanout":
                    assert isinstance(step, FanoutStep)

                    async def _fanout_coro(
                        s: FanoutStep = step,
                        phase_id: str = phase.id,
                    ) -> StepOutput | None:
                        limit = min(
                            s.concurrency or spec.policy.concurrency,
                            spec.policy.concurrency,
                        )
                        sem = asyncio.Semaphore(limit)

                        async def _fanout_item(item: str) -> StepOutput | None:
                            async with sem:
                                check_cancel()
                                return await run_agent_cfg(
                                    s.agent,
                                    item=item,
                                    phase_id=phase_id,
                                    step_id=f"{s.id}:{item}",
                                )

                        results = await gather_step_outputs(
                            step_id=f"fanout {s.id}",
                            indexed_items=list(enumerate(s.items)),
                            worker=_fanout_item,
                        )
                        previews: list[str] = []
                        for item, res in results:
                            ctx.outputs[f"{s.id}:{item}"] = res
                            previews.append(f"{item}: {res.preview}")
                        if not previews:
                            return None
                        return make_step_output("\n".join(previews))

                    out = await run_step(step.id, step.id, phase.id, _fanout_coro())
                    if out is not None:
                        ctx.outputs[step.id] = out

                elif step.type == "pipeline":
                    assert isinstance(step, PipelineStep)

                    async def _pipeline_coro(
                        s: PipelineStep = step,
                        phase_id: str = phase.id,
                    ) -> StepOutput | None:
                        sem = asyncio.Semaphore(spec.policy.concurrency)

                        async def _pipeline_item(item: str) -> StepOutput | None:
                            async with sem:
                                prev: StepOutput | None = None
                                for stage in s.stages:
                                    check_cancel()
                                    stage_out = await run_agent_cfg(
                                        AgentStepConfig(
                                            label_template=stage.label_template,
                                            agent_type=stage.agent_type,
                                            model=stage.model,
                                            prompt_template=stage.prompt_template,
                                        ),
                                        item=item,
                                        previous=prev,
                                        phase_id=phase_id,
                                        step_id=f"{s.id}:{item}",
                                    )
                                    if stage_out is None:
                                        return None
                                    prev = stage_out
                                return prev

                        pipe_results = await gather_step_outputs(
                            step_id=f"pipeline {s.id}",
                            indexed_items=list(enumerate(s.items)),
                            worker=_pipeline_item,
                        )
                        lines = []
                        for item, res in pipe_results:
                            ctx.outputs[f"{s.id}:{item}"] = res
                            lines.append(f"{item}: {res.preview}")
                        if not lines:
                            return None
                        return make_step_output("\n".join(lines))

                    out = await run_step(step.id, step.id, phase.id, _pipeline_coro())
                    if out is not None:
                        ctx.outputs[step.id] = out

                elif step.type == "synthesis":
                    assert isinstance(step, SynthesisStep)
                    ctx.synthesis_step_ids.append(step.id)
                    prompt = render_template(
                        step.prompt_template,
                        outputs=ctx.outputs,
                    )

                    async def _syn_coro(
                        s: SynthesisStep = step,
                        rendered_prompt: str = prompt,
                    ) -> StepOutput | None:
                        def _on_syn_aid(aid: str) -> None:
                            ctx.spawned_agent_ids.append(aid)
                            for run in reversed(snapshot.agents):
                                if run.step_id == s.id and run.agent_id is None:
                                    run.agent_id = aid
                                    break

                        return await runner.run(
                            prompt=rendered_prompt,
                            label=s.label,
                            agent_type=s.agent_type,
                            model=s.model,
                            allowed_tools=s.allowed_tools,
                            output_schema=s.output_schema,
                            policy=spec.policy,
                            cancel_event=cancel_event,
                            on_agent_id=_on_syn_aid,
                        )

                    out = await run_step(step.id, step.label, phase.id, _syn_coro())
                    if out is not None:
                        ctx.outputs[step.id] = out

        result = _final_result(spec, ctx)
        _json_serializable(result)
        snapshot.result = result
        snapshot.duration_ms = int((time.monotonic() - started) * 1000)
        final_snapshot = _recompute_snapshot(snapshot)
        progress()
        return WorkflowRunResult(
            meta=spec.meta,
            result=result,
            snapshot=final_snapshot,
            logs=logs,
            duration_ms=snapshot.duration_ms or 0,
            errors=_collect_errors(final_snapshot),
        )
    except WorkflowAbortedError:
        if manager is not None:
            await _cancel_spawned(manager, ctx.spawned_agent_ids)
        for agent in snapshot.agents:
            if agent.status == "running":
                agent.status = "skipped"
                agent.error = "aborted"
        snapshot.duration_ms = int((time.monotonic() - started) * 1000)
        progress()
        raise
    except WorkflowFailedError:
        if manager is not None:
            await _cancel_spawned(manager, ctx.spawned_agent_ids)
        for agent in snapshot.agents:
            if agent.status == "running":
                agent.status = "error"
                agent.error = "failed"
        snapshot.duration_ms = int((time.monotonic() - started) * 1000)
        progress()
        raise
    except Exception:
        if manager is not None:
            await _cancel_spawned(manager, ctx.spawned_agent_ids)
        for agent in snapshot.agents:
            if agent.status == "running":
                agent.status = "error"
                agent.error = "failed"
        snapshot.duration_ms = int((time.monotonic() - started) * 1000)
        progress()
        raise


def _final_result(spec: WorkflowSpec, ctx: WorkflowRunContext) -> Any:
    if ctx.synthesis_step_ids:
        last_id = ctx.synthesis_step_ids[-1]
        out = ctx.outputs.get(last_id)
        if out is not None:
            if out.structured is not None:
                return out.structured
            return out.text
    return {sid: o.preview for sid, o in ctx.outputs.items()}


def render_workflow_text(snapshot: WorkflowSnapshot, *, completed: bool = False) -> str:
    header = "Workflow completed" if completed else "Workflow running"
    state = ""
    if snapshot.error_count:
        state = f", {snapshot.error_count} errors"
    elif snapshot.running_count:
        state = f", {snapshot.running_count} running"
    lines = [
        header,
        f"◆ Workflow: {snapshot.name} ({snapshot.done_count}/{snapshot.agent_count} done{state})",
    ]
    for phase_id in snapshot.phases:
        agents = [a for a in snapshot.agents if a.phase_id == phase_id]
        if not agents:
            continue
        done = sum(1 for a in agents if a.status == "done")
        lines.append(f"  ✓ {phase_id} {done}/{len(agents)}")
        for agent in agents[-6:]:
            icon = {"running": "●", "done": "✓", "error": "✗", "skipped": "-"}.get(
                agent.status, "○"
            )
            lines.append(f"    {icon} {agent.label}")
    for log in snapshot.logs[-2:]:
        lines.append(f"  log: {log}")
    return "\n".join(lines)
