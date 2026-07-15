"""Workflow runtime and agent runner.
"""

from __future__ import annotations



# Execute Workflow IR.
import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

from deepseek_tui.tools.subagent import SubAgentManager
from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    FanoutStep,
    LoopStep,
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
    WorkflowStep,
    WorkflowStepError,
    WorkflowValidationError,
    evaluate_loop_until,
    make_step_output,
    render_template,
    resolve_fanout_items_from_output,
)
from typing import Protocol


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
    on_checkpoint: Callable[[WorkflowRunContext, WorkflowSnapshot, list[str]], None]
    | None = None,
    task: str = "",
    initial_outputs: dict[str, StepOutput] | None = None,
    skip_step_ids: set[str] | None = None,
) -> WorkflowRunResult:
    started = time.monotonic()
    if spec.policy.token_budget is not None and on_log is not None:
        on_log(
            "warning: policy.token_budget is set but not yet enforced; "
            "no cost cap will be applied"
        )
    ctx = WorkflowRunContext(task=task or "")
    if initial_outputs:
        ctx.outputs.update(initial_outputs)
    if skip_step_ids:
        ctx.completed_step_ids = sorted(skip_step_ids)
    snapshot = WorkflowSnapshot(
        name=spec.meta.name,
        description=spec.meta.description,
    )
    logs: list[str] = []
    skip = set(skip_step_ids or ())
    # Reserved-but-not-yet-registered spawn slots. ``ctx.spawned_agent_ids`` only
    # grows once ``runner.run()`` has actually spawned the agent (after an
    # ``await``), so concurrent fanout branches could otherwise all pass the
    # ``max_agents`` check below before any of them registers — oversubscribing
    # the cap. Incrementing this synchronously, right next to the check, closes
    # that race because asyncio only switches tasks at ``await`` points.
    reserved_agents = 0

    def log(msg: str) -> None:
        logs.append(msg)
        snapshot.logs.append(msg)
        if on_log:
            on_log(msg)

    def progress() -> None:
        if on_progress:
            on_progress(_recompute_snapshot(snapshot))

    def checkpoint() -> None:
        if not on_checkpoint:
            return
        try:
            on_checkpoint(ctx, _recompute_snapshot(snapshot), logs)
        except Exception as exc:  # noqa: BLE001 — never mask step failures
            msg = f"checkpoint callback failed: {exc}"
            _LOG.warning(msg, exc_info=True)
            log(msg)

    def check_cancel() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise WorkflowAbortedError("workflow cancelled")

    async def cancel_pending(tasks: set[asyncio.Task[StepOutput | None]]) -> None:
        for task_obj in tasks:
            if not task_obj.done():
                task_obj.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def gather_step_outputs(
        *,
        step_id: str,
        indexed_items: list[tuple[int, str]],
        worker: Callable[[str], Awaitable[StepOutput | None]],
        on_item_done: Callable[[str, StepOutput], None] | None = None,
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
                for task_obj in done:
                    idx, item = tasks[task_obj]
                    try:
                        result = task_obj.result()
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
                            raise WorkflowFailedError(f"{step_id}[{item}] failed")
                        continue
                    outputs[idx] = (item, result)
                    if on_item_done is not None:
                        on_item_done(item, result)
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
        nonlocal reserved_agents
        if len(ctx.spawned_agent_ids) + reserved_agents >= spec.policy.max_agents:
            raise WorkflowFailedError(
                f"max_agents limit ({spec.policy.max_agents}) reached at step {step_id}"
            )
        reserved_agents += 1
        slot_transferred = False
        try:
            label = cfg.label or (
                render_template(
                    cfg.label_template or "agent",
                    item=item,
                    task=ctx.task,
                    round=ctx.round,
                )
                if cfg.label_template
                else step_id
            )
            if cfg.prompt:
                prompt = render_template(
                    cfg.prompt,
                    item=item,
                    previous=previous,
                    outputs=ctx.outputs,
                    task=ctx.task,
                    round=ctx.round,
                )
            else:
                prompt = render_template(
                    cfg.prompt_template or "",
                    item=item,
                    previous=previous,
                    outputs=ctx.outputs,
                    task=ctx.task,
                    round=ctx.round,
                )
            if not prompt.strip():
                return None

            def _on_agent_id(aid: str) -> None:
                nonlocal reserved_agents, slot_transferred
                ctx.spawned_agent_ids.append(aid)
                # The agent now counts itself via spawned_agent_ids; release the
                # placeholder here instead of waiting for runner.run() to return
                # (which polls get_result for the whole turn, potentially tens
                # of seconds) — otherwise every in-flight agent is double
                # counted (reserved_agents + spawned_agent_ids) and max_agents
                # bites at roughly half its configured value under fanout.
                reserved_agents -= 1
                slot_transferred = True
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
                timeout_seconds=cfg.timeout_seconds,
            )
            if cancel_event is not None and cancel_event.is_set():
                raise WorkflowAbortedError("workflow cancelled")
            return out
        finally:
            if not slot_transferred:
                reserved_agents -= 1

    async def dispatch_step(step: WorkflowStep, phase_id: str) -> None:
        if step.id in skip and step.id in ctx.outputs:
            log(f"skip completed step {step.id}")
            return

        if step.type == "agent":
            assert isinstance(step, AgentStep)

            async def _agent_coro(
                s: AgentStep = step,
                pid: str = phase_id,
            ) -> StepOutput | None:
                return await run_agent_cfg(
                    AgentStepConfig(
                        label=s.label,
                        agent_type=s.agent_type,
                        model=s.model,
                        allowed_tools=s.allowed_tools,
                        prompt=s.prompt,
                        output_schema=s.output_schema,
                        timeout_seconds=s.timeout_seconds,
                    ),
                    phase_id=pid,
                    step_id=s.id,
                )

            out = await run_step(step.id, step.label, phase_id, _agent_coro())
            if out is not None:
                ctx.outputs[step.id] = out

        elif step.type == "fanout":
            assert isinstance(step, FanoutStep)

            async def _fanout_coro(
                s: FanoutStep = step,
                pid: str = phase_id,
            ) -> StepOutput | None:
                if s.items is not None:
                    fanout_items = list(s.items)
                else:
                    assert s.items_from is not None
                    source_out = ctx.outputs.get(s.items_from.step)
                    if source_out is None:
                        raise WorkflowValidationError(
                            f"fanout {s.id}: items_from step "
                            f"{s.items_from.step!r} has no output"
                        )
                    fanout_items = resolve_fanout_items_from_output(
                        source_out, s.items_from
                    )
                limit = min(
                    s.concurrency or spec.policy.concurrency,
                    spec.policy.concurrency,
                )
                sem = asyncio.Semaphore(limit)

                def _item_key(item: str) -> str:
                    return f"{s.id}:{item}"

                # Resume: skip items already checkpointed under ``{step}:{item}``.
                pending_indexed: list[tuple[int, str]] = []
                for idx, item in enumerate(fanout_items):
                    key = _item_key(item)
                    if key in ctx.outputs:
                        log(f"skip completed fanout item {key}")
                    else:
                        pending_indexed.append((idx, item))

                async def _fanout_item(item: str) -> StepOutput | None:
                    async with sem:
                        check_cancel()
                        return await run_agent_cfg(
                            s.agent,
                            item=item,
                            phase_id=pid,
                            step_id=_item_key(item),
                        )

                def _on_fanout_item_done(item: str, res: StepOutput) -> None:
                    ctx.outputs[_item_key(item)] = res
                    # Persist each finished branch so mid-fanout interrupt can resume.
                    checkpoint()
                    progress()

                new_results = await gather_step_outputs(
                    step_id=f"fanout {s.id}",
                    indexed_items=pending_indexed,
                    worker=_fanout_item,
                    on_item_done=_on_fanout_item_done,
                )
                # Merge preserved + new in original item order.
                by_item = {item: res for item, res in new_results}
                previews: list[str] = []
                for item in fanout_items:
                    key = _item_key(item)
                    res = ctx.outputs.get(key) or by_item.get(item)
                    if res is None:
                        continue
                    ctx.outputs[key] = res
                    previews.append(f"{item}: {res.preview}")
                if not previews:
                    return None
                return make_step_output("\n".join(previews))

            out = await run_step(step.id, step.id, phase_id, _fanout_coro())
            if out is not None:
                ctx.outputs[step.id] = out

        elif step.type == "pipeline":
            assert isinstance(step, PipelineStep)

            async def _pipeline_coro(
                s: PipelineStep = step,
                pid: str = phase_id,
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
                                phase_id=pid,
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

            out = await run_step(step.id, step.id, phase_id, _pipeline_coro())
            if out is not None:
                ctx.outputs[step.id] = out

        elif step.type == "synthesis":
            assert isinstance(step, SynthesisStep)
            ctx.synthesis_step_ids.append(step.id)
            prompt = render_template(
                step.prompt_template,
                outputs=ctx.outputs,
                task=ctx.task,
                round=ctx.round,
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
                    timeout_seconds=s.timeout_seconds,
                )

            out = await run_step(step.id, step.label, phase_id, _syn_coro())
            if out is not None:
                ctx.outputs[step.id] = out

        elif step.type == "loop":
            assert isinstance(step, LoopStep)

            async def _loop_coro(
                s: LoopStep = step,
                pid: str = phase_id,
            ) -> StepOutput | None:
                # Checkpoint granularity note: this whole step is only added to
                # ``ctx.completed_step_ids`` once every round below has run (see
                # the bottom of ``dispatch_step``). There is no per-round
                # checkpoint, so resuming a run that was interrupted mid-loop
                # re-executes rounds 1..N from scratch — see WorkflowTool's
                # description() for the user-facing callout.
                last: StepOutput | None = None
                for round_idx in range(1, s.max_rounds + 1):
                    check_cancel()
                    ctx.round = round_idx
                    log(f"loop {s.id}: round {round_idx}/{s.max_rounds}")
                    for body_step in s.steps:
                        # Body steps always re-run each round (not skipped).
                        await _dispatch_body(body_step, pid)
                    last = ctx.outputs.get(s.steps[-1].id) if s.steps else None
                    if s.until is not None and evaluate_loop_until(
                        s.until, outputs=ctx.outputs, body=s.steps
                    ):
                        log(f"loop {s.id}: until satisfied at round {round_idx}")
                        break
                ctx.round = None
                if last is None:
                    return None
                return make_step_output(last.text, last.structured)

            out = await run_step(step.id, step.id, phase_id, _loop_coro())
            if out is not None:
                ctx.outputs[step.id] = out
        else:
            raise WorkflowFailedError(f"unknown step type: {step.type}")

        if step.id not in ctx.completed_step_ids:
            ctx.completed_step_ids.append(step.id)
        checkpoint()

    async def _dispatch_body(step: WorkflowStep, phase_id: str) -> None:
        """Dispatch a loop body step, forcing a re-run each round.

        Body steps still go through the normal ``dispatch_step`` path (including
        per-step checkpoints) so mid-loop crashes keep the latest outputs.
        Skip-sets from outer resume are cleared for the body call so completed
        body step ids do not prevent re-execution on later rounds.
        Per-item fanout/pipeline outputs (``{step}:{item}``) are also cleared so
        each loop round re-executes branches instead of treating them as resume skips.
        """
        # Temporarily clear skip for body re-runs within a loop round.
        saved = set(skip)
        skip.clear()
        try:
            was_completed = step.id in ctx.completed_step_ids
            if was_completed:
                ctx.completed_step_ids = [x for x in ctx.completed_step_ids if x != step.id]
            prefix = f"{step.id}:"
            ctx.outputs = {
                k: v
                for k, v in ctx.outputs.items()
                if k != step.id and not k.startswith(prefix)
            }
            await dispatch_step(step, phase_id)
        finally:
            skip.update(saved)

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
                await dispatch_step(step, phase.id)

        result = _final_result(spec, ctx)
        _json_serializable(result)
        snapshot.result = result
        snapshot.duration_ms = int((time.monotonic() - started) * 1000)
        final_snapshot = _recompute_snapshot(snapshot)
        progress()
        checkpoint()
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
        checkpoint()
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
        checkpoint()
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
        checkpoint()
        raise



def _final_result(spec: WorkflowSpec, ctx: WorkflowRunContext) -> Any:
    if ctx.synthesis_step_ids:
        last_id = ctx.synthesis_step_ids[-1]
        out = ctx.outputs.get(last_id)
        if out is not None:
            if out.structured is not None:
                return out.structured
            return out.text
    # Prefer top-level step outputs; skip fanout/pipeline item keys (``step:item``).
    top = {
        sid: o.preview
        for sid, o in ctx.outputs.items()
        if ":" not in sid
    }
    return top if top else {sid: o.preview for sid, o in ctx.outputs.items()}


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


# DeepSeek SubAgentManager adapter for workflow steps.

from deepseek_tui.tools.subagent import (
    SpawnRequest,
    SubAgentAssignment,
    SubAgentRuntime,
    SubAgentStatusKind,
    SubAgentType,
)
from deepseek_tui.workflow.models import ANALYSIS_ONLY_TOOLS, WAIT_TIMEOUT_MS
from deepseek_tui.workflow.models import WorkflowPolicy


class WorkflowRunner(Protocol):
    async def run(
        self,
        *,
        prompt: str,
        label: str,
        agent_type: str,
        model: str | None,
        allowed_tools: list[str] | None,
        output_schema: dict[str, Any] | None,
        policy: WorkflowPolicy,
        cancel_event: asyncio.Event | None,
        on_agent_id: Any,
        timeout_seconds: float | None = None,
    ) -> StepOutput | None:
        ...


class DeepSeekAgentRunner:
    def __init__(
        self,
        manager: SubAgentManager,
        base_runtime: SubAgentRuntime,
        *,
        parent_depth: int = 0,
        register_spawned: Any = None,
        workspace: Path | None = None,
    ) -> None:
        self._manager = manager
        self._base_runtime = base_runtime
        self._parent_depth = parent_depth
        self._register_spawned = register_spawned
        self._workspace = workspace

    def _allowed_tools(
        self, policy: WorkflowPolicy, allowed: list[str] | None
    ) -> list[str] | None:
        if policy.approval_mode == "analysis_only":
            return sorted(ANALYSIS_ONLY_TOOLS)
        return allowed

    async def run(
        self,
        *,
        prompt: str,
        label: str,
        agent_type: str,
        model: str | None,
        allowed_tools: list[str] | None,
        output_schema: dict[str, Any] | None,
        policy: WorkflowPolicy,
        cancel_event: asyncio.Event | None,
        on_agent_id: Any = None,
        timeout_seconds: float | None = None,
    ) -> StepOutput | None:
        if cancel_event is not None and cancel_event.is_set():
            raise WorkflowAbortedError("workflow cancelled")
        parsed = SubAgentType.parse(agent_type) or SubAgentType.GENERAL
        auto_approve: bool | None = None
        if policy.approval_mode == "trusted_workflow":
            auto_approve = True
        elif policy.approval_mode == "strict":
            auto_approve = False
        else:
            auto_approve = True

        request = SpawnRequest(
            prompt=prompt,
            agent_type=parsed,
            assignment=SubAgentAssignment(objective=prompt, role=label),
            allowed_tools=self._allowed_tools(policy, allowed_tools),
            model=model,
            nickname=label,
            parent_depth=self._parent_depth,
            output_schema=output_schema,
            auto_approve=auto_approve,
            workspace=self._workspace,
        )
        snap = await self._manager.spawn(request)
        if on_agent_id is not None:
            on_agent_id(snap.agent_id)
        if self._register_spawned is not None:
            self._register_spawned(snap.agent_id)

        timeout_s = (
            timeout_seconds if timeout_seconds is not None else WAIT_TIMEOUT_MS / 1000
        )
        deadline = time.monotonic() + timeout_s
        final = snap
        async def _try_cancel() -> None:
            try:
                await self._manager.cancel(snap.agent_id)
            except KeyError:
                pass

        while True:
            if cancel_event is not None and cancel_event.is_set():
                await _try_cancel()
                raise WorkflowAbortedError("workflow cancelled")
            try:
                final = await self._manager.get_result(snap.agent_id)
            except KeyError:
                return None
            except Exception:
                await _try_cancel()
                return None
            if final.status.kind is not SubAgentStatusKind.RUNNING:
                break
            if time.monotonic() >= deadline:
                await _try_cancel()
                return None
            await asyncio.sleep(0.1)

        if final.status.kind in (
            SubAgentStatusKind.FAILED,
            SubAgentStatusKind.CANCELLED,
            SubAgentStatusKind.INTERRUPTED,
        ):
            if cancel_event is not None and cancel_event.is_set():
                raise WorkflowAbortedError("workflow cancelled")
            return None
        text = final.result or ""
        structured = final.structured
        return make_step_output(text, structured)
