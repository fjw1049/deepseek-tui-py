"""Ready-set DAG scheduler for workflow execution."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Protocol

from deepseek_tui.tools.subagent import SubAgentManager
from deepseek_tui.workflow.dag import CompiledGraph, compile_workflow_graph
from deepseek_tui.workflow.dynamic import (
    DECISION_SCHEMA,
    apply_decision_actions,
    build_controller_prompt,
    parse_nested_spec,
    validate_decision,
)
from deepseek_tui.workflow.store import has_stop_intent, write_stop_intent
from deepseek_tui.workflow.helpers import run_support_helper
from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    DagStep,
    DynamicStep,
    FanoutStep,
    LoopStep,
    PipelineStep,
    ReduceStep,
    StepOutput,
    SupportStep,
    SynthesisStep,
    WorkflowAbortedError,
    WorkflowAgentRun,
    WorkflowFailedError,
    WorkflowNodeSnapshot,
    WorkflowRunContext,
    WorkflowRunResult,
    WorkflowSnapshot,
    WorkflowSpec,
    WorkflowStep,
    WorkflowStepError,
    WorkflowValidationError,
    ANALYSIS_ONLY_TOOLS,
    evaluate_loop_until,
    make_step_output,
    render_template,
    resolve_fanout_items_from_output,
)

_LOG = logging.getLogger(__name__)


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
        policy: Any,
        cancel_event: asyncio.Event | None,
        on_agent_id: Any,
        timeout_seconds: float | None = None,
    ) -> StepOutput | None:
        ...


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


def _estimate_tokens(text: str) -> int:
    # Rough char/4 heuristic; honest enforcement without a tokenizer.
    return max(1, len(text) // 4) if text else 0


def _refresh_graph_snapshot(snapshot: WorkflowSnapshot, graph: CompiledGraph, ctx: WorkflowRunContext) -> None:
    running_ids = {
        a.step_id for a in snapshot.agents if a.status == "running"
    }
    # Dynamic controllers are running for the whole decision loop.
    for dyn_id, state in ctx.dynamic_states.items():
        if isinstance(state, dict) and state.get("status") == "running":
            running_ids.add(dyn_id)
    nodes: list[WorkflowNodeSnapshot] = []
    for nid, step in graph.nodes.items():
        if nid in ctx.completed_step_ids:
            status = "done"
        elif nid in ctx.failed_step_ids:
            status = "error"
        elif nid in ctx.skipped_step_ids:
            status = "skipped"
        elif nid in running_ids:
            status = "running"
        else:
            status = "queued"
        label = getattr(step, "label", None) or nid
        nodes.append(
            WorkflowNodeSnapshot(
                id=nid,
                type=step.type,
                status=status,  # type: ignore[arg-type]
                generated=nid in ctx.generated_node_ids,
                predecessors=sorted(graph.predecessors.get(nid, ())),
                label=label if isinstance(label, str) else nid,
            )
        )
    snapshot.nodes = nodes
    snapshot.edges = [
        {"from": e.from_id, "to": e.to_id} for e in graph.edges[:200]
    ]
    snapshot.dynamic_rounds = {
        k: int(v.get("round", 0))
        for k, v in ctx.dynamic_states.items()
        if isinstance(v, dict)
    }


async def schedule_workflow(
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
    cwd: Any = None,
    initial_graph: CompiledGraph | None = None,
    nested_dynamic_depth: int = 0,
    run_id: str | None = None,
) -> WorkflowRunResult:
    started = time.monotonic()
    graph = initial_graph or compile_workflow_graph(spec)

    if spec.policy.token_budget is not None and on_log is not None:
        on_log(
            f"policy.token_budget={spec.policy.token_budget} enforced via char/4 estimate"
        )

    ctx = WorkflowRunContext(task=task or "", nested_dynamic_depth=nested_dynamic_depth)
    if initial_outputs:
        ctx.outputs.update(initial_outputs)
    if skip_step_ids:
        ctx.completed_step_ids = sorted(skip_step_ids)
    # Optional resume bags (attached by tools/workflow from run.json).
    resume_bag = getattr(spec, "_resume_ctx", None)
    if isinstance(resume_bag, dict):
        for sid in resume_bag.get("skipped_step_ids") or []:
            if isinstance(sid, str) and sid not in ctx.skipped_step_ids:
                ctx.skipped_step_ids.append(sid)
        for sid in resume_bag.get("failed_step_ids") or []:
            if isinstance(sid, str) and sid not in ctx.failed_step_ids:
                ctx.failed_step_ids.append(sid)
        dyn = resume_bag.get("dynamic_states")
        if isinstance(dyn, dict):
            ctx.dynamic_states.update(dyn)
        budgets = resume_bag.get("budgets_used")
        if isinstance(budgets, dict):
            ctx.budgets_used.update(
                {str(k): int(v) for k, v in budgets.items() if isinstance(v, int)}
            )
        gen = resume_bag.get("generated_node_ids")
        if isinstance(gen, list):
            ctx.generated_node_ids = [str(x) for x in gen if isinstance(x, str)]
        if isinstance(resume_bag.get("estimated_tokens_used"), int):
            ctx.estimated_tokens_used = resume_bag["estimated_tokens_used"]

    snapshot = WorkflowSnapshot(
        name=spec.meta.name,
        description=spec.meta.description,
        phases=list(graph.phase_titles.keys()) or ["graph"],
    )
    logs: list[str] = []
    reserved_agents = 0
    skip = set(skip_step_ids or ())

    def log(msg: str) -> None:
        logs.append(msg)
        snapshot.logs.append(msg)
        if on_log:
            on_log(msg)

    def progress() -> None:
        _refresh_graph_snapshot(snapshot, graph, ctx)
        if on_progress:
            on_progress(_recompute_snapshot(snapshot))

    def checkpoint() -> None:
        if not on_checkpoint:
            return
        try:
            ctx.runtime_graph = graph.to_dict()
            _refresh_graph_snapshot(snapshot, graph, ctx)
            on_checkpoint(ctx, _recompute_snapshot(snapshot), logs)
        except Exception as exc:  # noqa: BLE001
            msg = f"checkpoint callback failed: {exc}"
            _LOG.warning(msg, exc_info=True)
            log(msg)

    def check_cancel() -> None:
        # Durable stop-intent (cross-crash) takes precedence; also persist
        # in-memory cancel so a crash mid-abort still leaves a stop file.
        if run_id and has_stop_intent(run_id, workspace=cwd):
            if cancel_event is not None:
                cancel_event.set()
            raise WorkflowAbortedError("workflow cancelled")
        if cancel_event is not None and cancel_event.is_set():
            if run_id:
                try:
                    write_stop_intent(run_id, workspace=cwd)
                except OSError:
                    pass
            raise WorkflowAbortedError("workflow cancelled")

    def check_token_budget(extra_text: str = "") -> None:
        if spec.policy.token_budget is None:
            return
        ctx.estimated_tokens_used += _estimate_tokens(extra_text)
        if ctx.estimated_tokens_used > spec.policy.token_budget:
            raise WorkflowFailedError(
                f"token_budget exceeded ({ctx.estimated_tokens_used} > {spec.policy.token_budget})"
            )

    def check_wall_clock() -> None:
        # Enforce policy.wall_clock_seconds as a hard wall-clock budget.
        # Checked alongside check_cancel() at every ready-set iteration so a
        # long-running step is caught on the next drain tick.
        limit = spec.policy.wall_clock_seconds
        if limit and limit > 0 and (time.monotonic() - started) > limit:
            raise WorkflowFailedError(
                f"wall_clock_seconds exceeded ({int(time.monotonic() - started)}s > {limit}s)"
            )

    async def cancel_pending(tasks: set[asyncio.Task[Any]]) -> None:
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
        on_item_failed: Callable[[str], None] | None = None,
    ) -> list[tuple[str, StepOutput]]:
        tasks: dict[asyncio.Task[StepOutput | None], tuple[int, str]] = {
            asyncio.create_task(worker(item)): (idx, item)
            for idx, item in indexed_items
        }
        pending: set[asyncio.Task[StepOutput | None]] = set(tasks)
        outputs: dict[int, tuple[str, StepOutput]] = {}

        def _suppress_unretrieved() -> None:
            for t in tasks:
                if t.done() and not t.cancelled():
                    try:
                        t.exception()
                    except (asyncio.CancelledError, BaseException):
                        pass

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
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
                    except Exception as e:  # noqa: BLE001
                        log(f"{step_id}[{item}]: {e}")
                        if on_item_failed is not None:
                            on_item_failed(item)
                        if spec.policy.on_error == "fail_fast":
                            await cancel_pending(pending)
                            if manager is not None:
                                await _cancel_spawned(manager, ctx.spawned_agent_ids)
                            raise WorkflowFailedError(
                                f"{step_id}[{item}] failed: {e}"
                            ) from e
                        continue
                    if result is None:
                        log(f"{step_id}[{item}]: agent failed")
                        if on_item_failed is not None:
                            on_item_failed(item)
                        if spec.policy.on_error == "fail_fast":
                            await cancel_pending(pending)
                            if manager is not None:
                                await _cancel_spawned(manager, ctx.spawned_agent_ids)
                            raise WorkflowFailedError(f"{step_id}[{item}] failed")
                        continue
                    outputs[idx] = (item, result)
                    if on_item_done is not None:
                        on_item_done(item, result)
        except BaseException:
            await cancel_pending(pending)
            _suppress_unretrieved()
            raise
        return [outputs[idx] for idx in sorted(outputs)]

    async def run_step_record(
        step_id: str,
        label: str,
        phase_id: str,
        coro: Awaitable[StepOutput | None],
        *,
        track_agent: bool = True,
    ) -> StepOutput | None:
        """Track a step's lifecycle on the live snapshot.

        ``track_agent=False`` is for composite wrappers (fanout / pipeline)
        whose workers record their own ``WorkflowAgentRun`` rows — avoids a
        shell parent row that steals ``agent_id`` attach.
        """
        check_cancel()
        run: WorkflowAgentRun | None = None
        if track_agent:
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
            if run is not None:
                run.status = "skipped"
                run.error = "aborted"
                progress()
            raise
        except WorkflowFailedError:
            # Hard budget/policy failures (token_budget, wall_clock, max_agents,
            # reduce source_policy=success) must propagate even under
            # on_error=continue - otherwise the budget is silently swallowed
            # as an ordinary step failure and the workflow keeps running.
            if run is not None:
                run.status = "error"
                run.error = "policy failure"
                progress()
            raise
        except Exception as exc:  # noqa: BLE001
            if run is not None:
                run.status = "error"
                run.error = str(exc)
            log(f"step {step_id} failed: {exc}")
            progress()
            if spec.policy.on_error == "fail_fast":
                raise WorkflowFailedError(str(exc)) from exc
            return None
        if out is None:
            if run is not None:
                run.status = "error"
                run.error = "agent failed"
                progress()
            if spec.policy.on_error == "fail_fast":
                raise WorkflowFailedError(f"step {step_id} failed")
            return None
        if run is not None:
            run.status = "done"
            run.result_preview = out.preview
        check_token_budget(out.text)
        progress()
        return out

    async def run_agent_cfg(
        cfg: AgentStepConfig,
        *,
        item: str | None = None,
        previous: StepOutput | None = None,
        phase_id: str,
        step_id: str,
        record_worker: bool = False,
    ) -> StepOutput | None:
        """Spawn one agent.

        ``record_worker=True`` creates a dedicated snapshot row under
        ``step_id`` (the DAG node id) so fanout/pipeline workers get live
        ``agent_id`` join keys for the ProcessTray tool-step UI.
        """
        nonlocal reserved_agents
        if len(ctx.spawned_agent_ids) + reserved_agents >= spec.policy.max_agents:
            raise WorkflowFailedError(
                f"max_agents limit ({spec.policy.max_agents}) reached at step {step_id}"
            )
        reserved_agents += 1
        slot_transferred = False
        worker_run: WorkflowAgentRun | None = None
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
            check_token_budget(prompt)

            if record_worker:
                worker_run = WorkflowAgentRun(
                    step_id=step_id,
                    label=label,
                    phase_id=phase_id,
                    status="running",
                )
                snapshot.agents.append(worker_run)
                progress()

            def _on_agent_id(aid: str) -> None:
                nonlocal reserved_agents, slot_transferred
                ctx.spawned_agent_ids.append(aid)
                reserved_agents -= 1
                slot_transferred = True
                if worker_run is not None:
                    worker_run.agent_id = aid
                else:
                    for run in reversed(snapshot.agents):
                        if run.step_id == step_id and run.agent_id is None:
                            run.agent_id = aid
                            break
                # Emit immediately so the UI can join mailbox tool steps
                # while the agent is still running (not only at completion).
                progress()

            try:
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
            except WorkflowAbortedError:
                if worker_run is not None:
                    worker_run.status = "skipped"
                    worker_run.error = "aborted"
                    progress()
                raise
            except Exception as exc:  # noqa: BLE001
                if worker_run is not None:
                    worker_run.status = "error"
                    worker_run.error = str(exc)
                    progress()
                raise
            if cancel_event is not None and cancel_event.is_set():
                if worker_run is not None:
                    worker_run.status = "skipped"
                    worker_run.error = "aborted"
                    progress()
                raise WorkflowAbortedError("workflow cancelled")
            if worker_run is not None:
                if out is None:
                    worker_run.status = "error"
                    worker_run.error = "agent failed"
                else:
                    worker_run.status = "done"
                    worker_run.result_preview = out.preview
                progress()
            return out
        finally:
            if not slot_transferred:
                reserved_agents -= 1

    async def execute_node(step: WorkflowStep, phase_id: str) -> StepOutput | None:
        if step.id in skip and step.id in ctx.outputs:
            log(f"skip completed step {step.id}")
            return ctx.outputs[step.id]

        if step.type == "agent":
            assert isinstance(step, AgentStep)

            async def _agent_coro() -> StepOutput | None:
                return await run_agent_cfg(
                    AgentStepConfig(
                        label=step.label,
                        agent_type=step.agent_type,
                        model=step.model,
                        allowed_tools=step.allowed_tools,
                        prompt=step.prompt,
                        output_schema=step.output_schema,
                        timeout_seconds=step.timeout_seconds,
                    ),
                    phase_id=phase_id,
                    step_id=step.id,
                )

            return await run_step_record(step.id, step.label, phase_id, _agent_coro())

        if step.type == "fanout":
            assert isinstance(step, FanoutStep)

            async def _fanout_coro() -> StepOutput | None:
                if step.items is not None:
                    fanout_items = list(step.items)
                else:
                    assert step.items_from is not None
                    source_out = ctx.outputs.get(step.items_from.step)
                    if source_out is None:
                        raise WorkflowValidationError(
                            f"fanout {step.id}: items_from step "
                            f"{step.items_from.step!r} has no output"
                        )
                    fanout_items = resolve_fanout_items_from_output(
                        source_out, step.items_from
                    )
                limit = min(
                    step.concurrency or spec.policy.concurrency,
                    spec.policy.concurrency,
                )
                sem = asyncio.Semaphore(limit)

                def _item_key(item: str) -> str:
                    return f"{step.id}:{item}"

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
                        # Record each worker under the fanout node id so the
                        # ProcessTray can join mailbox steps by agent_id.
                        return await run_agent_cfg(
                            step.agent,
                            item=item,
                            phase_id=phase_id,
                            step_id=step.id,
                            record_worker=True,
                        )

                def _on_fanout_item_done(item: str, res: StepOutput) -> None:
                    ctx.outputs[_item_key(item)] = res
                    checkpoint()
                    progress()

                def _on_fanout_item_failed(item: str) -> None:
                    key = _item_key(item)
                    if key not in ctx.failed_step_ids:
                        ctx.failed_step_ids.append(key)
                    progress()

                new_results = await gather_step_outputs(
                    step_id=f"fanout {step.id}",
                    indexed_items=pending_indexed,
                    worker=_fanout_item,
                    on_item_done=_on_fanout_item_done,
                    on_item_failed=_on_fanout_item_failed,
                )
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

            # Parent row keeps the node "running" while workers each record
            # their own agent_id-bearing rows under the same step id.
            return await run_step_record(step.id, step.id, phase_id, _fanout_coro())

        if step.type == "pipeline":
            assert isinstance(step, PipelineStep)

            async def _pipeline_coro() -> StepOutput | None:
                sem = asyncio.Semaphore(spec.policy.concurrency)

                async def _pipeline_item(item: str) -> StepOutput | None:
                    async with sem:
                        prev: StepOutput | None = None
                        for stage in step.stages:
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
                                step_id=step.id,
                                record_worker=True,
                            )
                            if stage_out is None:
                                return None
                            prev = stage_out
                        return prev

                def _on_pipe_item_failed(item: str) -> None:
                    key = f"{step.id}:{item}"
                    if key not in ctx.failed_step_ids:
                        ctx.failed_step_ids.append(key)
                    progress()

                pipe_results = await gather_step_outputs(
                    step_id=f"pipeline {step.id}",
                    indexed_items=list(enumerate(step.items)),
                    worker=_pipeline_item,
                    on_item_failed=_on_pipe_item_failed,
                )
                lines = []
                for item, res in pipe_results:
                    ctx.outputs[f"{step.id}:{item}"] = res
                    lines.append(f"{item}: {res.preview}")
                if not lines:
                    return None
                return make_step_output("\n".join(lines))

            return await run_step_record(step.id, step.id, phase_id, _pipeline_coro())

        if step.type in ("synthesis", "reduce"):
            if step.type == "reduce":
                assert isinstance(step, ReduceStep)
                if step.source_policy == "success":
                    for pred in step.from_steps:
                        if pred in ctx.failed_step_ids:
                            raise WorkflowFailedError(
                                f"reduce {step.id}: predecessor {pred} failed"
                            )
                ctx.synthesis_step_ids.append(step.id)
                prompt = render_template(
                    step.prompt_template,
                    outputs=ctx.outputs,
                    task=ctx.task,
                    round=ctx.round,
                )
                label = step.label
                agent_type = step.agent_type
                model = step.model
                allowed = step.allowed_tools
                schema = step.output_schema
                timeout = step.timeout_seconds
            else:
                assert isinstance(step, SynthesisStep)
                if step.source_policy == "success":
                    for pred in graph.predecessors.get(step.id, ()):
                        if pred in ctx.failed_step_ids:
                            raise WorkflowFailedError(
                                f"synthesis {step.id}: predecessor {pred} failed"
                            )
                ctx.synthesis_step_ids.append(step.id)
                prompt = render_template(
                    step.prompt_template,
                    outputs=ctx.outputs,
                    task=ctx.task,
                    round=ctx.round,
                )
                label = step.label
                agent_type = step.agent_type
                model = step.model
                allowed = step.allowed_tools
                schema = step.output_schema
                timeout = step.timeout_seconds

            async def _syn_coro() -> StepOutput | None:
                def _on_syn_aid(aid: str) -> None:
                    ctx.spawned_agent_ids.append(aid)
                    for run in reversed(snapshot.agents):
                        if run.step_id == step.id and run.agent_id is None:
                            run.agent_id = aid
                            break
                    progress()

                return await runner.run(
                    prompt=prompt,
                    label=label,
                    agent_type=agent_type,
                    model=model,
                    allowed_tools=allowed,
                    output_schema=schema,
                    policy=spec.policy,
                    cancel_event=cancel_event,
                    on_agent_id=_on_syn_aid,
                    timeout_seconds=timeout,
                )

            return await run_step_record(step.id, label, phase_id, _syn_coro())

        if step.type == "support":
            assert isinstance(step, SupportStep)

            async def _support_coro() -> StepOutput | None:
                inputs = {
                    sid: ctx.outputs[sid]
                    for sid in step.from_steps
                    if sid in ctx.outputs
                }
                return run_support_helper(step.uses, inputs, step.options)

            return await run_step_record(step.id, step.uses, phase_id, _support_coro())

        if step.type == "loop":
            assert isinstance(step, LoopStep)

            async def _loop_coro() -> StepOutput | None:
                last: StepOutput | None = None
                for round_idx in range(1, step.max_rounds + 1):
                    check_cancel()
                    ctx.round = round_idx
                    log(f"loop {step.id}: round {round_idx}/{step.max_rounds}")
                    for body_step in step.steps:
                        await _dispatch_body(body_step, phase_id)
                    last = ctx.outputs.get(step.steps[-1].id) if step.steps else None
                    if step.until is not None and evaluate_loop_until(
                        step.until, outputs=ctx.outputs, body=step.steps
                    ):
                        log(f"loop {step.id}: until satisfied at round {round_idx}")
                        break
                ctx.round = None
                if last is None:
                    return None
                return make_step_output(last.text, last.structured)

            return await run_step_record(step.id, step.id, phase_id, _loop_coro())

        if step.type == "dag":
            assert isinstance(step, DagStep)
            from deepseek_tui.workflow.dag import GraphEdge, build_adjacency, assert_acyclic

            async def _dag_coro() -> StepOutput | None:
                child_nodes = {s.id: s for s in step.nodes}
                edges = [GraphEdge(from_id=a, to_id=b) for a, b in step.edges]
                child_graph = build_adjacency(child_nodes, edges)
                assert_acyclic(child_graph)
                # Run nested ready-set until child nodes done
                child_done: set[str] = set()
                child_failed: set[str] = set()
                child_skipped: set[str] = set()
                while len(child_done | child_failed | child_skipped) < len(child_nodes):
                    check_cancel()
                    ready = child_graph.ready_ids(child_done, child_failed, child_skipped)
                    if not ready:
                        break
                    batch = ready[: spec.policy.concurrency]
                    # Run the ready batch concurrently (not a sequential
                    # for-await loop, which ignored concurrency and ran
                    # children one at a time).
                    batch_tasks = [
                        asyncio.create_task(execute_node(child_nodes[cid], phase_id))
                        for cid in batch
                    ]
                    try:
                        results = await asyncio.gather(*batch_tasks)
                    except BaseException:
                        # Cancel and drain siblings before propagating, so a
                        # fail_fast/abort child doesn't leave orphans running.
                        await cancel_pending(set(batch_tasks))
                        for _t in batch_tasks:
                            if _t.done() and not _t.cancelled():
                                try:
                                    _t.exception()
                                except (asyncio.CancelledError, BaseException):
                                    pass
                        raise
                    for cid, cout in zip(batch, results):
                        if cout is not None:
                            ctx.outputs[cid] = cout
                            child_done.add(cid)
                        elif spec.policy.on_error == "fail_fast":
                            child_failed.add(cid)
                            raise WorkflowFailedError(f"dag child {cid} failed")
                        else:
                            child_failed.add(cid)
                out_id = step.output_from or (step.nodes[-1].id if step.nodes else None)
                if out_id and out_id in ctx.outputs:
                    return ctx.outputs[out_id]
                return make_step_output(f"dag {step.id} completed")

            return await run_step_record(step.id, step.id, phase_id, _dag_coro())

        if step.type == "dynamic":
            assert isinstance(step, DynamicStep)
            return await _run_dynamic(step, phase_id)

        raise WorkflowFailedError(f"unknown step type: {step.type}")

    async def _dispatch_body(body_step: WorkflowStep, phase_id: str) -> None:
        saved = set(skip)
        skip.clear()
        try:
            if body_step.id in ctx.completed_step_ids:
                ctx.completed_step_ids = [
                    x for x in ctx.completed_step_ids if x != body_step.id
                ]
            prefix = f"{body_step.id}:"
            ctx.outputs = {
                k: v
                for k, v in ctx.outputs.items()
                if k != body_step.id and not k.startswith(prefix)
            }
            out = await execute_node(body_step, phase_id)
            if out is not None:
                ctx.outputs[body_step.id] = out
                if body_step.id not in ctx.completed_step_ids:
                    ctx.completed_step_ids.append(body_step.id)
        finally:
            skip.update(saved)

    async def _run_dynamic(step: DynamicStep, phase_id: str) -> StepOutput | None:
        state = ctx.dynamic_states.setdefault(
            step.id, {"round": 0, "mutations": [], "status": "running"}
        )
        start_round = int(state.get("round") or 0) + 1

        async def _dyn_coro() -> StepOutput | None:
            last_notes = ""
            for round_idx in range(start_round, step.budget.max_decision_rounds + 1):
                check_cancel()
                state["round"] = round_idx
                snapshot.dynamic_rounds[step.id] = round_idx
                prompt = build_controller_prompt(
                    step,
                    task=ctx.task,
                    graph=graph,
                    ctx=ctx,
                    round_idx=round_idx,
                )
                check_token_budget(prompt)

                # The controller is an orchestrator, not a worker. Track its
                # agent_id separately so it does not consume the worker budget
                # (DynamicBudget.max_agents) nor inflate agents_left accounting.
                controller_agent_ids: list[str] = state.setdefault(
                    "controller_agent_ids", []
                )

                def _on_ctrl(aid: str) -> None:
                    if aid not in controller_agent_ids:
                        controller_agent_ids.append(aid)

                # Enforce allow_write_tools: when False (default), intersect
                # the controller's declared tools with the read-only allowlist
                # so a controller cannot escalate to write tools by declaration.
                if step.permissions.allow_write_tools:
                    ctrl_tools = step.controller_allowed_tools
                else:
                    declared = step.controller_allowed_tools or []
                    ctrl_tools = [t for t in declared if t in ANALYSIS_ONLY_TOOLS] or list(ANALYSIS_ONLY_TOOLS)

                decision_out = await runner.run(
                    prompt=prompt,
                    label=f"dynamic:{step.id}:r{round_idx}",
                    agent_type=step.controller_agent_type,
                    model=step.controller_model,
                    allowed_tools=ctrl_tools,
                    output_schema=DECISION_SCHEMA,
                    policy=spec.policy,
                    cancel_event=cancel_event,
                    on_agent_id=_on_ctrl,
                    timeout_seconds=min(600, step.budget.wall_clock_seconds),
                )
                if decision_out is None or decision_out.structured is None:
                    raise WorkflowFailedError(
                        f"dynamic {step.id}: controller returned no structured decision"
                    )
                check_token_budget(decision_out.text or "")
                decision = decision_out.structured
                if not isinstance(decision, dict):
                    raise WorkflowFailedError("dynamic decision must be an object")
                last_notes = str(decision.get("notes") or "")
                prev_sigs = [
                    str(s)
                    for s in (state.get("decision_signatures") or [])
                    if isinstance(s, str)
                ]
                try:
                    signature = validate_decision(
                        decision,
                        step=step,
                        previous_signatures=prev_sigs,
                    )
                except WorkflowValidationError as exc:
                    raise WorkflowFailedError(
                        f"dynamic {step.id}: invalid decision: {exc}"
                    ) from exc
                state.setdefault("decision_signatures", []).append(signature)
                flags = apply_decision_actions(
                    step,
                    decision,
                    graph=graph,
                    ctx=ctx,
                    round_idx=round_idx,
                    parent_id=step.id,
                )
                state.setdefault("mutations", []).append(
                    {"round": round_idx, "actions": decision.get("actions")}
                )

                if flags.get("replan"):
                    dropped = set(flags.get("replan_dropped") or [])
                    log(
                        f"dynamic {step.id}: replan dropped {len(dropped)} pending node(s)"
                    )
                    cancel_ids = [
                        a.agent_id
                        for a in snapshot.agents
                        if a.step_id in dropped
                        and a.agent_id
                        and a.status == "running"
                    ]
                    if manager is not None and cancel_ids:
                        await _cancel_spawned(manager, cancel_ids)
                    for agent in snapshot.agents:
                        if agent.step_id in dropped and agent.status == "running":
                            agent.status = "skipped"
                            agent.error = "replan"

                checkpoint()
                progress()

                # Soul of dynamic: run every newly ready generated node to
                # completion *before* the next decision round, so round N+1
                # observes real outputs (not pending stubs).
                await _drain_ready(exclude={step.id})

                for nested in flags.get("nested_specs") or []:
                    nested_spec = parse_nested_spec(nested, cwd=cwd)
                    ctx.nested_dynamic_depth += 1
                    try:
                        nested_result = await schedule_workflow(
                            nested_spec,
                            runner=runner,
                            cancel_event=cancel_event,
                            manager=manager,
                            on_log=on_log,
                            on_progress=on_progress,
                            task=ctx.task,
                            cwd=cwd,
                            nested_dynamic_depth=ctx.nested_dynamic_depth,
                            run_id=run_id,
                        )
                        nid = f"dyn/{step.id}/nested/{round_idx}"
                        ctx.outputs[nid] = make_step_output(
                            json.dumps(nested_result.result, ensure_ascii=False)
                            if not isinstance(nested_result.result, str)
                            else nested_result.result,
                            nested_result.result
                            if isinstance(nested_result.result, (dict, list))
                            else None,
                        )
                    finally:
                        ctx.nested_dynamic_depth -= 1

                if flags.get("stop"):
                    if not flags.get("stop_success", True):
                        raise WorkflowFailedError(
                            f"dynamic {step.id} stopped with failure: {last_notes}"
                        )
                    # Final drain for same-batch synthesize/reduce that may have
                    # been waiting on workers finished above.
                    await _drain_ready(exclude={step.id})
                    syn_ids = flags.get("synthesize_ids") or []
                    if syn_ids and syn_ids[-1] in ctx.outputs:
                        return ctx.outputs[syn_ids[-1]]
                    return make_step_output(
                        last_notes or f"dynamic {step.id} completed",
                        {"notes": last_notes, "round": round_idx},
                    )
                # replan / continue: next decision round sees updated graph+outputs.
            raise WorkflowFailedError(
                f"dynamic {step.id}: max_decision_rounds exhausted"
            )

        return await run_step_record(step.id, step.id, phase_id, _dyn_coro())

    async def _drain_ready(*, exclude: set[str] | None = None) -> None:
        exclude = exclude or set()
        while True:
            check_cancel()
            check_wall_clock()
            completed = set(ctx.completed_step_ids)
            failed = set(ctx.failed_step_ids)
            skipped = set(ctx.skipped_step_ids)
            ready = [
                nid
                for nid in graph.ready_ids(completed, failed, skipped)
                if nid not in exclude and nid not in skip
            ]
            # Also allow skip-set completed
            ready = [
                nid
                for nid in ready
                if not (nid in skip and nid in ctx.outputs)
            ]
            if not ready:
                return
            batch = ready[: spec.policy.concurrency]
            async def _run_one(nid: str) -> None:
                step = graph.nodes[nid]
                phase_id = graph.phase_of.get(nid, "graph")
                snapshot.current_phase = graph.phase_titles.get(phase_id, phase_id)
                if on_phase:
                    on_phase(snapshot.current_phase)
                try:
                    out = await execute_node(step, phase_id)
                except WorkflowFailedError:
                    ctx.failed_step_ids.append(nid)
                    _mark_successors_skipped(nid)
                    raise
                if out is not None:
                    ctx.outputs[nid] = out
                    if nid not in ctx.completed_step_ids:
                        ctx.completed_step_ids.append(nid)
                else:
                    ctx.failed_step_ids.append(nid)
                    if spec.policy.on_error == "fail_fast":
                        _mark_successors_skipped(nid)
                        raise WorkflowFailedError(f"step {nid} failed")
                    # continue: skip non-partial successors (they can never
                    # become ready once a pred failed); partial joins are
                    # preserved by _mark_successors_skipped for ready_ids.
                    _mark_successors_skipped(nid)
                checkpoint()
                progress()

            batch_tasks = [asyncio.create_task(_run_one(nid)) for nid in batch]
            try:
                await asyncio.gather(*batch_tasks)
            except BaseException:
                # A sibling raised (fail_fast / abort / unexpected). Plain
                # ``asyncio.gather`` propagates the first exception but leaves
                # the other batch tasks running as orphans: they keep mutating
                # ctx/snapshot, checkpointing, and spawning agents while the
                # outer error handler runs ``_cancel_spawned``. Cancel and
                # drain them first so the error handler sees a quiescent run.
                await cancel_pending(set(batch_tasks))
                for _t in batch_tasks:
                    if _t.done() and not _t.cancelled():
                        try:
                            _t.exception()
                        except (asyncio.CancelledError, BaseException):
                            pass
                raise

    def _mark_successors_skipped(nid: str) -> None:
        # Skip successors of a failed node. Partial joins (reduce/synthesis
        # with source_policy=partial) are left for ``ready_ids`` to admit -
        # they may still run on the remaining completed predecessors. Other
        # successors have no recovery path and must be marked skipped so the
        # ready-set is not blocked waiting on a predecessor that will never
        # complete.
        stack = list(graph.successors.get(nid, ()))
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            cur_step = graph.nodes.get(cur)
            is_partial = (
                isinstance(cur_step, (ReduceStep, SynthesisStep))
                and cur_step.source_policy == "partial"
            )
            if is_partial:
                # A partial join may still fire on other completed preds;
                # do not force-skip it. Its own non-partial successors will
                # be visited if/when it is skipped later.
                continue
            if (
                cur not in ctx.completed_step_ids
                and cur not in ctx.failed_step_ids
                and cur not in ctx.skipped_step_ids
            ):
                ctx.skipped_step_ids.append(cur)
            stack.extend(graph.successors.get(cur, ()))

    try:
        # Seed phase list for UI
        for pid, title in graph.phase_titles.items():
            if pid not in snapshot.phases:
                snapshot.phases.append(pid)
            if on_phase:
                on_phase(title)
        progress()
        await _drain_ready()

        # Ensure all non-skipped nodes attempted
        remaining = [
            nid
            for nid in graph.nodes
            if nid not in ctx.completed_step_ids
            and nid not in ctx.failed_step_ids
            and nid not in ctx.skipped_step_ids
        ]
        if remaining:
            # Partial joins may become ready only after a continue-mode failure.
            await _drain_ready()
            remaining = [
                nid
                for nid in graph.nodes
                if nid not in ctx.completed_step_ids
                and nid not in ctx.failed_step_ids
                and nid not in ctx.skipped_step_ids
            ]
        if remaining:
            completed = set(ctx.completed_step_ids)
            failed = set(ctx.failed_step_ids)
            skipped = set(ctx.skipped_step_ids)
            still_ready = set(graph.ready_ids(completed, failed, skipped))
            for nid in remaining:
                if nid in still_ready:
                    continue
                preds = graph.predecessors.get(nid, set())
                if preds & failed:
                    ctx.skipped_step_ids.append(nid)
                elif not preds <= (completed | skipped):
                    ctx.skipped_step_ids.append(nid)

        result = _final_result(spec, ctx)
        _json_serializable(result)
        snapshot.result = result
        # Normalize leftover running agent rows so tray progress can reach 100%.
        for agent in snapshot.agents:
            if agent.status == "running":
                agent.status = "done"
        snapshot.duration_ms = int((time.monotonic() - started) * 1000)
        final_snapshot = _recompute_snapshot(snapshot)
        _refresh_graph_snapshot(final_snapshot, graph, ctx)
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
    top = {sid: o.preview for sid, o in ctx.outputs.items() if ":" not in sid}
    return top if top else {sid: o.preview for sid, o in ctx.outputs.items()}
