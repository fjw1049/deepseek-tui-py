"""Dispatch + post-run delivery for automations (OpenHuman ``deliver_if_configured``)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from deepseek_tui.automation.delivery_format import (
    format_delivery_body,
    should_skip_delivery_for_error,
)
from deepseek_tui.automation.inbox import (
    build_digest_block,
    default_feishu_chat_id_from_config,
    email_send_text,
    feishu_send_text,
)
from deepseek_tui.automation.triage import TRIAGE_DEFER, TRIAGE_RUN, apply_triage
from deepseek_tui.automation.types import (
    DeliveryConfig,
    DigestConfig,
    cron_execution_prefix,
)

if TYPE_CHECKING:
    from deepseek_tui.app_server.thread_manager import RuntimeThreadManager
    from deepseek_tui.tools.automation_manager import AutomationRecord, AutomationRunRecord
    from deepseek_tui.tools.task_manager import TaskManager

logger = logging.getLogger(__name__)


def _skip_internal_failure_delivery(
    automation_id: str,
    automation_name: str,
    error: str | None,
) -> bool:
    """Mark delivery done without notifying user for internal failures."""
    if not should_skip_delivery_for_error(error):
        return False
    logger.info(
        "[automation][delivery] skipped internal failure automation=%s name=%s error=%s",
        automation_id,
        automation_name,
        (error or "").strip()[:120],
    )
    return True


class DeliverySink(Protocol):
    async def deliver(
        self,
        *,
        config: DeliveryConfig,
        automation_name: str,
        automation_id: str,
        summary: str,
    ) -> None: ...


class _SilentSink:
    async def deliver(self, **kwargs: object) -> None:
        return


class _LogSink:
    def __init__(self, thread_manager: RuntimeThreadManager | None = None) -> None:
        self._thread_manager = thread_manager

    async def deliver(
        self,
        *,
        config: DeliveryConfig,
        automation_name: str,
        automation_id: str,
        summary: str,
    ) -> None:
        target = config.chat_id or config.to or config.thread_id or "—"
        logger.info(
            "[automation][delivery][%s] automation=%s id=%s target=%s len=%d",
            "notify",
            automation_name,
            automation_id,
            target,
            len(summary),
        )
        if self._thread_manager is not None and config.thread_id:
            await self._thread_manager.append_automation_notice(
                config.thread_id,
                automation_name=automation_name,
                summary=summary,
            )


class _EmailSink:
    async def deliver(
        self,
        *,
        config: DeliveryConfig,
        automation_name: str,
        automation_id: str,
        summary: str,
    ) -> None:
        to_addr = config.to or config.chat_id
        if not to_addr:
            raise ValueError("delivery.mode=email requires to (recipient address)")
        subject = f"{automation_name} · 自动化摘要"
        await email_send_text(to_addr=to_addr, subject=subject, body=summary)


class _FeishuSink:
    async def deliver(
        self,
        *,
        config: DeliveryConfig,
        automation_name: str,
        automation_id: str,
        summary: str,
    ) -> None:
        chat_id = config.chat_id or config.to
        if not chat_id:
            chat_id = default_feishu_chat_id_from_config()
        if not chat_id:
            raise ValueError("delivery.mode=feishu requires chat_id or to")
        await feishu_send_text(receive_id=chat_id, text=summary)


def _sink_for_mode(
    mode: str,
    *,
    thread_manager: RuntimeThreadManager | None = None,
) -> DeliverySink:
    key = mode.strip().lower()
    if key in ("email", "mail", "smtp"):
        return _EmailSink()
    if key in ("feishu", "announce"):
        return _FeishuSink()
    if key in ("notify", "proactive"):
        return _LogSink(thread_manager)
    return _SilentSink()


def trigger_prompt_prefix(trigger_id: str) -> str:
    return f"[trigger:{trigger_id}] "


async def build_trigger_prompt(
    *,
    prompt: str,
    digest: dict[str, Any] | None = None,
    trigger_id: str | None = None,
) -> str:
    tid = trigger_id or uuid.uuid4().hex[:12]
    digest_cfg = DigestConfig.from_mapping(digest)
    block = await build_digest_block(digest_cfg)
    return trigger_prompt_prefix(tid) + block + prompt.strip()


async def build_final_prompt(automation: AutomationRecord) -> str:
    digest = DigestConfig.from_mapping(automation.digest)
    prefix = cron_execution_prefix(automation.id, automation.name)
    block = await build_digest_block(digest)
    return prefix + block + automation.prompt.strip()


async def enqueue_automation_task(
    automation: AutomationRecord,
    run: AutomationRunRecord,
    task_manager: TaskManager,
) -> None:
    """Enqueue task — same defaults as legacy ``_enqueue_run_task``."""
    from deepseek_tui.tools.automation_manager import AutomationRunStatus
    from deepseek_tui.tools.task_manager import NewTaskRequest, TaskStatus

    if run.task_id is not None:
        try:
            existing = await task_manager.get_task(run.task_id)
            if existing.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                return
        except Exception:  # noqa: BLE001
            pass

    workspace = automation.cwds[0] if automation.cwds else None
    new_task = NewTaskRequest(
        prompt=await build_final_prompt(automation),
        model=None,
        workspace=str(workspace) if workspace else None,
        mode="agent",
        allow_shell=False,
        trust_mode=False,
        auto_approve=True,
    )
    try:
        task = await task_manager.add_task(new_task)
        run.status = AutomationRunStatus.RUNNING
        from deepseek_tui.tools.automation_manager import _utc_now_iso

        run.started_at = _utc_now_iso()
        run.task_id = task.id
        run.thread_id = getattr(task, "thread_id", None)
        run.turn_id = getattr(task, "turn_id", None)
        run.error = None
    except Exception as exc:  # noqa: BLE001
        run.status = AutomationRunStatus.FAILED
        from deepseek_tui.tools.automation_manager import _utc_now_iso

        run.ended_at = _utc_now_iso()
        run.error = f"Failed to enqueue task: {exc}"


async def try_deliver_completed_run(
    automation: AutomationRecord,
    run: AutomationRunRecord,
    task_manager: TaskManager,
    *,
    thread_manager: RuntimeThreadManager | None = None,
) -> bool:
    """Deliver once when a run reaches a terminal state (completed or failed)."""
    from deepseek_tui.tools.automation_manager import AutomationRunStatus
    from deepseek_tui.tools.task_manager import TaskStatus

    if run.delivery_done:
        return False
    if run.status not in (
        AutomationRunStatus.COMPLETED,
        AutomationRunStatus.FAILED,
    ):
        return False

    delivery = DeliveryConfig.from_mapping(automation.delivery)
    if not delivery.is_active():
        return False

    summary: str | None = None
    failure_error: str | None = None

    if run.status is AutomationRunStatus.FAILED:
        task = None
        if run.task_id is not None:
            try:
                task = await task_manager.get_task(run.task_id)
            except Exception:
                logger.warning(
                    "[automation][delivery] task missing automation=%s run=%s task=%s",
                    automation.id,
                    run.id,
                    run.task_id,
                )
                return False
            if task.status is not TaskStatus.FAILED:
                return False
        failure_error = run.error or (task.error if task is not None else None)
        if _skip_internal_failure_delivery(
            automation.id, automation.name, failure_error
        ):
            run.delivery_done = True
            return True
        summary = format_delivery_body(
            succeeded=False,
            raw_summary=task.result_summary if task is not None else None,
            automation_name=automation.name,
            error=failure_error,
        )
    elif run.status is AutomationRunStatus.COMPLETED:
        if run.task_id is None:
            return False
        try:
            task = await task_manager.get_task(run.task_id)
        except Exception:
            logger.warning(
                "[automation][delivery] task missing automation=%s run=%s task=%s",
                automation.id,
                run.id,
                run.task_id,
            )
            return False
        if task.status is not TaskStatus.COMPLETED:
            return False
        summary = format_delivery_body(
            succeeded=True,
            raw_summary=task.result_summary,
            automation_name=automation.name,
        )

    if not summary:
        return False

    sink = _sink_for_mode(delivery.mode, thread_manager=thread_manager)
    try:
        await sink.deliver(
            config=delivery,
            automation_name=automation.name,
            automation_id=automation.id,
            summary=summary,
        )
    except Exception as exc:
        logger.warning(
            "[automation][delivery] failed automation=%s mode=%s: %s",
            automation.id,
            delivery.mode,
            exc,
        )
        if not delivery.best_effort:
            run.error = f"delivery failed: {exc}"
            return False
    run.delivery_done = True
    return True


async def deliver_when_task_completes(
    *,
    task_id: str,
    task_manager: TaskManager,
    delivery: dict[str, Any],
    label: str,
    label_id: str,
    thread_manager: RuntimeThreadManager | None = None,
    poll_s: float = 2.0,
    timeout_s: float = 600.0,
) -> None:
    """Poll task until COMPLETED/FAILED, then run ``DeliverySink`` once."""
    from deepseek_tui.tools.task_manager import TaskStatus

    delivery_cfg = DeliveryConfig.from_mapping(delivery)
    if not delivery_cfg.is_active():
        return
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        try:
            task = await task_manager.get_task(task_id)
        except Exception:
            logger.warning("[automation][delivery] task gone task_id=%s", task_id)
            return
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
            break
        await asyncio.sleep(poll_s)
    try:
        task = await task_manager.get_task(task_id)
    except Exception:
        return
    if task.status is not TaskStatus.COMPLETED:
        if task.status is TaskStatus.FAILED:
            if _skip_internal_failure_delivery(label_id, label, task.error):
                return
            summary = format_delivery_body(
                succeeded=False,
                raw_summary=task.result_summary,
                automation_name=label,
                error=task.error,
            )
        else:
            logger.warning(
                "[automation][delivery] skip delivery task_id=%s status=%s",
                task_id,
                task.status,
            )
            return
    else:
        summary = format_delivery_body(
            succeeded=True,
            raw_summary=task.result_summary,
            automation_name=label,
        )
    sink = _sink_for_mode(delivery_cfg.mode, thread_manager=thread_manager)
    try:
        await sink.deliver(
            config=delivery_cfg,
            automation_name=label,
            automation_id=label_id,
            summary=summary,
        )
    except Exception as exc:
        logger.warning("[automation][delivery] trigger delivery failed: %s", exc)


async def fire_http_trigger(
    *,
    prompt: str,
    task_manager: TaskManager,
    digest: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
    workspace: str | None = None,
    triage_policy: str | None = None,
    triage_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enqueue a one-shot background task from ``POST /v1/triggers``."""
    from deepseek_tui.tools.task_manager import NewTaskRequest

    decision = apply_triage(
        policy=triage_policy,
        prompt=prompt,
        metadata=triage_metadata,
    )
    if decision.action is TRIAGE_DEFER:
        logger.info(
            "[automation][trigger] deferred reason=%s",
            decision.reason,
        )
        return {"status": "deferred", "reason": decision.reason}

    if decision.action is not TRIAGE_RUN:
        return {"status": "deferred", "reason": decision.reason or "not runnable"}

    trigger_id = uuid.uuid4().hex[:12]
    final_prompt = await build_trigger_prompt(
        prompt=prompt,
        digest=digest,
        trigger_id=trigger_id,
    )
    task = await task_manager.add_task(
        NewTaskRequest(
            prompt=final_prompt,
            model=None,
            workspace=workspace,
            mode="agent",
            allow_shell=False,
            trust_mode=False,
            auto_approve=True,
        )
    )
    logger.info(
        "[automation][trigger] enqueued trigger_id=%s task_id=%s",
        trigger_id,
        task.id,
    )
    outcome: dict[str, Any] = {
        "status": "enqueued",
        "trigger_id": trigger_id,
        "task_id": task.id,
    }
    if delivery and DeliveryConfig.from_mapping(delivery).is_active():
        outcome["delivery"] = "scheduled"
    return outcome


def _claw_thread_title(chat_id: str, sender_id: str) -> str:
    chat = chat_id.strip() or "dm"
    return f"claw:feishu:{chat}:{sender_id}"


async def _find_claw_thread(
    mgr: RuntimeThreadManager,
    *,
    chat_id: str,
    sender_id: str,
) -> Any | None:
    title = _claw_thread_title(chat_id, sender_id)
    for thread in await mgr.list_threads():
        if (thread.title or "").strip() == title:
            return thread
    return None


async def _extract_turn_assistant_text(
    mgr: RuntimeThreadManager,
    *,
    thread_id: str,
    turn_id: str,
) -> str:
    from deepseek_tui.app_server.runtime_threads import TurnItemKind

    parts: list[str] = []
    for item in mgr.store.list_items_for_turn(turn_id):
        if item.kind is TurnItemKind.AGENT_MESSAGE and item.detail:
            parts.append(item.detail.strip())
    return "\n\n".join(parts).strip()


async def wait_thread_turn_text(
    mgr: RuntimeThreadManager,
    *,
    thread_id: str,
    timeout_s: float = 300.0,
    poll_s: float = 1.0,
) -> str:
    """Poll until the active turn finishes; return last agent message text."""
    from deepseek_tui.app_server.runtime_threads import RuntimeTurnStatus

    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        if not await mgr.is_thread_turn_active(thread_id):
            break
        await asyncio.sleep(poll_s)
    thread = await mgr.get_thread(thread_id)
    turn_id = thread.latest_turn_id
    if not turn_id:
        return ""
    turn = mgr.store.load_turn(turn_id)
    if turn.status not in (
        RuntimeTurnStatus.COMPLETED,
        RuntimeTurnStatus.FAILED,
        RuntimeTurnStatus.INTERRUPTED,
    ):
        logger.warning(
            "[automation][feishu] turn not settled thread=%s turn=%s status=%s",
            thread_id,
            turn_id,
            turn.status,
        )
    text = await _extract_turn_assistant_text(mgr, thread_id=thread_id, turn_id=turn_id)
    if text:
        return text
    if turn.error:
        return f"(turn error: {turn.error})"
    return "(no assistant reply)"


async def run_feishu_inbound_agent(
    *,
    thread_manager: RuntimeThreadManager,
    text: str,
    sender_id: str,
    sender_name: str,
    chat_id: str,
    reply_chat_id: str | None = None,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Run a full agent turn on a stable ``claw:feishu:…`` thread and reply."""
    from deepseek_tui.app_server.runtime_threads import CreateThreadRequest, StartTurnRequest

    title = _claw_thread_title(chat_id, sender_id)
    thread = await _find_claw_thread(thread_manager, chat_id=chat_id, sender_id=sender_id)
    if thread is None:
        thread = await thread_manager.create_thread(
            CreateThreadRequest(
                mode="agent",
                auto_approve=True,
                trust_mode=False,
            )
        )
        thread.title = title
        thread.updated_at = datetime.now(timezone.utc)
        thread_manager.store.save_thread(thread)

    display = sender_name or sender_id
    prompt = (
        f"[feishu inbound from {display}]\n{text.strip()}\n\n"
        "Reply concisely in the same language as the user."
    )
    turn = await thread_manager.start_turn(
        thread.id,
        StartTurnRequest(prompt=prompt, auto_approve=True),
    )
    summary = await wait_thread_turn_text(
        thread_manager,
        thread_id=thread.id,
        timeout_s=timeout_s,
    )
    receive_id = (reply_chat_id or chat_id or sender_id).strip()
    if receive_id:
        try:
            await feishu_send_text(receive_id=receive_id, text=summary)
        except Exception as exc:
            logger.warning("[automation][feishu] reply send failed: %s", exc)
            return {
                "ok": False,
                "thread_id": thread.id,
                "turn_id": turn.id,
                "summary": summary,
                "error": str(exc),
            }
    return {
        "ok": True,
        "thread_id": thread.id,
        "turn_id": turn.id,
        "summary": summary,
    }
