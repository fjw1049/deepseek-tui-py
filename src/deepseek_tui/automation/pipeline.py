"""Automation pipeline and triage.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, replace
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from deepseek_tui.automation.delivery import (
    classify_task_error_for_user,
    format_delivery_body,
    sanitize_delivery_text,
    should_skip_delivery_for_error,
    delivery_target_fingerprint,
    sanitized_delivery_snapshot,
)
from deepseek_tui.automation.inbox import (
    build_digest_block,
    default_feishu_chat_id_from_config,
    email_send_text,
    feishu_send_text,
    wecom_webhook_send_text,
)
from deepseek_tui.automation.delivery import (
    DeliveryConfig,
    DeliveryNotSent,
    DigestConfig,
    cron_execution_prefix,
    strip_unattended_preamble,
    unattended_preamble,
)

if TYPE_CHECKING:
    from deepseek_tui.server.threads import RuntimeThreadManager
    from deepseek_tui.tools.automation import AutomationRecord, AutomationRunRecord
    from deepseek_tui.tools.task import TaskManager

logger = logging.getLogger(__name__)

# best_effort=false retries delivery on later ticks instead of giving up on
# the first failure. Bound that so a permanently-broken channel (Feishu/SMTP
# down, bad credentials) cannot re-hammer the endpoint every tick forever.
_MAX_DELIVERY_ATTEMPTS = 5
_DELIVERY_TIMEOUT_S = 30


def _definitely_not_sent(exc: Exception) -> bool:
    import httpx

    if isinstance(exc, (
        DeliveryNotSent, ConnectionRefusedError, httpx.ConnectError,
        httpx.ConnectTimeout, httpx.PoolTimeout,
    )):
        return True
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and 400 <= exc.response.status_code < 500
        and exc.response.status_code != 408
    )


def _mark_delivery_uncertain(run: AutomationRunRecord) -> None:
    run.delivery_state = "uncertain"
    run.delivery_done = False
    run.delivery_error = "Delivery outcome unknown; check the recipient before confirming receipt or retrying."


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
    def __init__(self, thread_manager: RuntimeThreadManager | None = None, delivery_id: str | None = None) -> None:
        self._thread_manager = thread_manager
        self._delivery_id = delivery_id

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
                item_id=f"automation_delivery_{self._delivery_id}" if self._delivery_id else None,
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
            raise DeliveryNotSent("delivery.mode=email requires to (recipient address)")
        from deepseek_tui.utils.user_text import user_text

        subject = user_text("email_subject", name=automation_name)
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
            raise DeliveryNotSent("delivery.mode=feishu requires chat_id or to")
        await feishu_send_text(receive_id=chat_id, text=summary)


class _WecomSink:
    async def deliver(
        self,
        *,
        config: DeliveryConfig,
        automation_name: str,
        automation_id: str,
        summary: str,
    ) -> None:
        webhook_key = config.to or config.chat_id
        await wecom_webhook_send_text(text=summary, webhook_key=webhook_key)


def _sink_for_mode(
    mode: str,
    *,
    thread_manager: RuntimeThreadManager | None = None,
    delivery_id: str | None = None,
) -> DeliverySink:
    key = mode.strip().lower()
    if key in ("email", "mail", "smtp"):
        return _EmailSink()
    if key in ("feishu", "announce"):
        return _FeishuSink()
    if key in ("wecom", "wecom_webhook", "wework"):
        return _WecomSink()
    if key in ("notify", "proactive"):
        return _LogSink(thread_manager, delivery_id)
    if key in ("silent", "none", ""):
        return _SilentSink()
    raise ValueError(f"Unknown delivery mode: {mode}")


def trigger_prompt_prefix(trigger_id: str) -> str:
    return f"[trigger:{trigger_id}] "


async def build_trigger_prompt(
    *,
    prompt: str,
    digest: dict[str, Any] | None = None,
    trigger_id: str | None = None,
    delivery_active: bool = False,
) -> str:
    tid = trigger_id or uuid.uuid4().hex[:12]
    digest_cfg = DigestConfig.from_mapping(digest)
    block = await asyncio.wait_for(build_digest_block(digest_cfg), timeout=30)
    # A trigger run is as unattended as a cron run.
    return (
        trigger_prompt_prefix(tid)
        + unattended_preamble(delivery_active=delivery_active)
        + block
        + prompt.strip()
    )


def _delivery_active(raw: dict[str, Any] | None) -> bool:
    try:
        return DeliveryConfig.from_mapping(raw).is_active()
    except ValueError:
        return False


async def build_final_prompt(automation: AutomationRecord) -> str:
    digest = DigestConfig.from_mapping(automation.digest)
    prefix = cron_execution_prefix(
        automation.id,
        automation.name,
        delivery_active=_delivery_active(automation.delivery),
    )
    block = await asyncio.wait_for(build_digest_block(digest), timeout=30)
    return prefix + block + automation.prompt.strip()


async def enqueue_automation_task(
    automation: AutomationRecord,
    run: AutomationRunRecord,
    task_manager: TaskManager,
    *,
    provider: str | None = None,
    model: str | None = None,
    browser_grant: dict[str, str] | None = None,
) -> None:
    """Read the current route at dispatch; only the resulting Task freezes it."""
    from deepseek_tui.tools.automation import AutomationRunStatus
    from deepseek_tui.tools.task import NewTaskRequest, TaskKind, TaskStatus

    if run.task_id is not None:
        try:
            existing = await task_manager.get_task(run.task_id)
            if existing.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                return
        except Exception:  # noqa: BLE001
            pass

    from deepseek_tui.utils import utc_now_iso as _utc_now_iso

    workspace = automation.cwds[0] if automation.cwds else None
    try:
        from pathlib import Path

        from deepseek_tui.config.loader import ConfigLoader
        from deepseek_tui.config.routing import config_for_model

        loaded = await asyncio.to_thread(
            ConfigLoader().load, workspace=Path(workspace) if workspace else None,
        )
        config = config_for_model(loaded, model, provider=provider)
        new_task = NewTaskRequest(
            idempotency_key=f"automation:{automation.id}:{run.id}",
            prompt=await build_final_prompt(automation),
            model=config.effective_provider_config().model,
            config=config,
            workspace=str(workspace) if workspace else None,
            mode="agent",
            allow_shell=True,
            trust_mode=False,
            auto_approve=True,
            kind=TaskKind.CRON,
            browser_grant=browser_grant,
        )
        task = await task_manager.add_task(new_task)
        run.status = AutomationRunStatus.QUEUED
        run.started_at = getattr(task, "started_at", None)
        run.task_id = task.id
        run.thread_id = getattr(task, "thread_id", None)
        run.turn_id = getattr(task, "turn_id", None)
        run.error = None
    except Exception as exc:  # noqa: BLE001
        run.status = AutomationRunStatus.FAILED
        run.ended_at = _utc_now_iso()
        run.error = f"Failed to enqueue task: {str(exc) or type(exc).__name__}"


async def try_write_run_result(
    automation: AutomationRecord,
    run: AutomationRunRecord,
    task_manager: TaskManager,
    *,
    thread_manager: RuntimeThreadManager | None = None,
) -> bool:
    """Persist a terminal result independently of external delivery."""
    from deepseek_tui.tools.automation import AutomationRunStatus
    from deepseek_tui.tools.task import TaskStatus

    if run.conversation_written or not run.conversation_thread_id or thread_manager is None:
        return False
    terminal_tasks = {
        AutomationRunStatus.COMPLETED: (TaskStatus.COMPLETED,),
        AutomationRunStatus.FAILED: (TaskStatus.FAILED, TaskStatus.TIMED_OUT),
        AutomationRunStatus.CANCELED: (TaskStatus.CANCELED,),
    }
    if run.status not in terminal_tasks:
        return False
    from deepseek_tui.utils.user_text import user_text

    try:
        task = await task_manager.get_task(run.task_id) if run.task_id else None
        if task is not None and task.status not in terminal_tasks[run.status]:
            return False
        if task is None and run.status is AutomationRunStatus.COMPLETED:
            return False
        error = (task.error if task is not None else None) or run.error
        summary = format_delivery_body(
            succeeded=run.status is AutomationRunStatus.COMPLETED,
            raw_summary=task.result_summary if task is not None else None,
            automation_name=automation.name,
            error=error,
        )
        if run.status is AutomationRunStatus.CANCELED:
            summary = f"⏹ {user_text('error_canceled')}"
        elif run.status is AutomationRunStatus.FAILED:
            summary = f"❌ {classify_task_error_for_user(error or '')}"
        prompt = getattr(task, "prompt", None) if task is not None else None
        if isinstance(prompt, str):
            prompt = sanitize_delivery_text(strip_unattended_preamble(prompt))
        await thread_manager.append_automation_result(
            run.conversation_thread_id,
            automation_id=automation.id,
            automation_name=automation.name,
            prompt=prompt if isinstance(prompt, str) else automation.prompt,
            run_id=run.id,
            task_id=run.task_id,
            ended_at=run.ended_at,
            status=run.status.value,
            summary=summary,
        )
    except FileNotFoundError:
        # The chat was deleted, so retrying every tick can never succeed.
        # Discussing the run later opens a fresh chat instead.
        logger.info(
            "automation_result_thread_gone run=%s thread=%s",
            run.id,
            run.conversation_thread_id,
        )
        run.conversation_thread_id = None
        return True
    except Exception:
        # A busy chat or failed write is retried on the next reconcile tick.
        logger.debug("automation_result_write_pending run=%s", run.id, exc_info=True)
        return False
    run.conversation_written = True
    return True


async def try_deliver_completed_run(
    automation: AutomationRecord,
    run: AutomationRunRecord,
    task_manager: TaskManager,
    *,
    thread_manager: RuntimeThreadManager | None = None,
    save_run: Callable[[AutomationRunRecord], None] | None = None,
) -> bool:
    """Deliver once when a run reaches a terminal state (completed or failed)."""
    from deepseek_tui.tools.automation import AutomationRunStatus
    from deepseek_tui.tools.task import TaskStatus

    if run.delivery_done:
        return False
    if run.delivery_state == "uncertain":
        return False
    if run.delivery_state == "sending":
        # Previous process stopped after recording intent. The receiver may
        # already have the message; never automatically replay this attempt.
        old_config = (run.delivery_snapshot or {}).get("config") or run.delivery or automation.delivery
        if str((old_config or {}).get("mode", "")).lower() != "notify":
            _mark_delivery_uncertain(run)
            return True
        run.delivery_state = "pending"  # Local writes use a stable item id.
    if run.status not in (
        AutomationRunStatus.COMPLETED,
        AutomationRunStatus.FAILED,
    ):
        return False

    # HTTP-trigger runs carry their own per-request delivery config.
    snapshot = run.delivery_snapshot
    refresh_config = snapshot is not None and bool(snapshot.get("refresh_config"))
    try:
        delivery = DeliveryConfig.from_mapping(
            snapshot["config"] if snapshot is not None and not refresh_config else
            run.delivery if run.delivery is not None else automation.delivery
        )
    except (DeliveryNotSent, ValueError) as exc:
        # Missing local credentials must never fall back to another destination.
        run.delivery_error = str(exc)
        return True
    if snapshot is not None and not refresh_config and not delivery.credential_ref and snapshot.get("target_fingerprint"):
        current = DeliveryConfig.from_mapping(
            run.delivery if run.delivery is not None else automation.delivery
        )
        if current.mode == "wecom" and not (current.to or current.chat_id):
            from deepseek_tui.automation.inbox import default_wecom_webhook_key_from_config

            current = replace(current, to=default_wecom_webhook_key_from_config())
        if (current.mode != "wecom" or
                delivery_target_fingerprint(current) != snapshot["target_fingerprint"]):
            _mark_delivery_uncertain(run)
            run.delivery_error = "Original delivery target changed; restore it before retrying this message."
            return True
        delivery = replace(delivery, to=current.to, chat_id=current.chat_id)
    if not delivery.is_active():
        return False

    summary: str | None = snapshot["summary"] if snapshot is not None else None
    delivery_name = snapshot["automation_name"] if snapshot is not None else automation.name
    failure_error: str | None = None

    if snapshot is not None:
        pass  # A retry uses the recorded body even if the task was removed or changed.
    elif run.status is AutomationRunStatus.FAILED:
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
            if task.status not in (TaskStatus.FAILED, TaskStatus.TIMED_OUT):
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

    if snapshot is None or refresh_config:
        if delivery.mode == "feishu" and not (delivery.chat_id or delivery.to):
            delivery = replace(delivery, chat_id=default_feishu_chat_id_from_config())
        elif delivery.mode == "wecom" and not (delivery.chat_id or delivery.to):
            from deepseek_tui.automation.inbox import default_wecom_webhook_key_from_config

            delivery = replace(delivery, to=default_wecom_webhook_key_from_config())
        run.delivery_snapshot = sanitized_delivery_snapshot({
            "config": asdict(delivery), "summary": summary, "automation_name": delivery_name,
            "delivery_id": uuid.uuid4().hex,
        })
    sink = _sink_for_mode(delivery.mode, thread_manager=thread_manager,
                         delivery_id=(run.delivery_snapshot or {}).get("delivery_id") or run.id)
    run.delivery_state = "sending"
    run.delivery_attempts += 1
    if save_run is not None:
        # A failed journal write must prevent the external side effect.
        save_run(run)
    try:
        await asyncio.wait_for(sink.deliver(
            config=delivery,
            automation_name=delivery_name,
            automation_id=automation.id,
            summary=summary,
        ), timeout=_DELIVERY_TIMEOUT_S)
    except asyncio.CancelledError:
        if delivery.mode == "notify":
            run.delivery_state = "pending"
        else:
            _mark_delivery_uncertain(run)
        if save_run is not None:
            save_run(run)
        raise
    except Exception as exc:
        import httpx

        # HTTP exception strings may contain the credential-bearing webhook URL.
        detail = (f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError)
                  else str(exc) if isinstance(exc, DeliveryNotSent) else type(exc).__name__)
        logger.warning(
            "[automation][delivery] failed automation=%s mode=%s: %s",
            automation.id,
            delivery.mode,
            detail,
        )
        if delivery.mode != "notify" and not _definitely_not_sent(exc):
            _mark_delivery_uncertain(run)
            return True
        run.delivery_state = "failed"
        # A repaired destination must be usable after a definite rejection.
        if delivery.mode != "notify":
            assert run.delivery_snapshot is not None
            run.delivery_snapshot["refresh_config"] = True
        if not delivery.best_effort:
            if run.delivery_attempts < _MAX_DELIVERY_ATTEMPTS:
                # Retry on a later tick. Note the failure without clobbering
                # the task's own result/error — the run's terminal status is
                # unchanged, only delivery is still pending.
                run.delivery_state = "pending"
                return True
            # Out of retries: stop re-hammering the channel and record why.
            run.delivery_done = True
            run.delivery_error = detail
            # Keep a failed run's execution error; delivery_error carries this one.
            if not run.error:
                run.error = (
                    f"delivery failed after {run.delivery_attempts} attempts: {detail}"
                )
            logger.warning(
                "[automation][delivery] giving up automation=%s mode=%s attempts=%d",
                automation.id,
                delivery.mode,
                run.delivery_attempts,
            )
            return True
        # best_effort: one shot, mark done regardless — but not as sent.
        run.delivery_error = detail
    else:
        run.delivery_state = "sent"
        run.delivery_error = None
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
    timeout_s: float | None = None,
) -> None:
    """Legacy standalone helper: poll, then send once without restart recovery.

    App integrations should pass an AutomationManager to fire_http_trigger
    so delivery uses the persistent journal and human confirmation workflow.
    Retained for callers that own their own task/poller lifecycle.
    """
    from deepseek_tui.tools.task import RUN_POLICIES, TaskKind, TaskStatus

    if timeout_s is None:
        # Outlive the task's own wall clock, plus time spent queued.
        timeout_s = RUN_POLICIES[TaskKind.TRIGGER].wall_clock_secs + 1800.0
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
        if task.status.is_terminal():
            break
        await asyncio.sleep(poll_s)
    try:
        task = await task_manager.get_task(task_id)
    except Exception:
        return
    if task.status is not TaskStatus.COMPLETED:
        if task.status in (TaskStatus.FAILED, TaskStatus.TIMED_OUT):
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
        await asyncio.wait_for(sink.deliver(
            config=delivery_cfg,
            automation_name=label,
            automation_id=label_id,
            summary=summary,
        ), timeout=_DELIVERY_TIMEOUT_S)
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
    automation_manager: Any | None = None,
) -> dict[str, Any]:
    """Enqueue a one-shot background task from ``POST /v1/triggers``.

    When an automation manager is available and delivery is configured, the
    run is persisted under :data:`HTTP_TRIGGER_RUNS_KEY` so the scheduler's
    reconcile loop owns delivery — surviving restarts and retrying failed
    channels like any cron run. Without a manager the response still reports
    delivery "scheduled" and the HTTP layer falls back to its poller.
    """
    from deepseek_tui.tools.task import NewTaskRequest, TaskKind

    decision = apply_triage(
        policy=triage_policy,
        prompt=prompt,
        metadata=triage_metadata,
    )
    if decision.action != TRIAGE_RUN:
        status = "deferred" if decision.action == TRIAGE_DEFER else "dropped"
        logger.info("[automation][trigger] %s reason=%s", status, decision.reason)
        # Nothing is stored for later: a deferred trigger must be sent again.
        return {"status": status, "queued": False, "reason": decision.reason}

    # Reject a bad delivery mode before enqueueing, or the caller sees an
    # error for a task that is already running (and retries into a duplicate).
    delivery_cfg = DeliveryConfig.from_mapping(delivery)
    trigger_id = uuid.uuid4().hex[:12]
    final_prompt = await build_trigger_prompt(
        prompt=prompt,
        digest=digest,
        trigger_id=trigger_id,
        delivery_active=delivery_cfg.is_active(),
    )
    from pathlib import Path

    from deepseek_tui.config.loader import ConfigLoader

    config = await asyncio.to_thread(
        ConfigLoader().load, workspace=Path(workspace) if workspace else None,
    )
    task = await task_manager.add_task(
        NewTaskRequest(
            prompt=final_prompt,
            model=config.effective_provider_config().model,
            config=config,
            workspace=workspace,
            mode="agent",
            allow_shell=False,
            trust_mode=False,
            auto_approve=True,
            kind=TaskKind.TRIGGER,
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
    if delivery and delivery_cfg.is_active():
        outcome["delivery"] = "scheduled"
        if automation_manager is not None:
            # Persist the run so reconcile (not a one-shot poller) owns
            # delivery: restart-safe, retry-capable, same as cron runs.
            from deepseek_tui.tools.automation import (
                HTTP_TRIGGER_RUNS_KEY,
                AutomationRunRecord,
                AutomationRunStatus,
            )
            from deepseek_tui.utils import utc_now_iso as _utc_now_iso

            automation_manager.save_run(
                AutomationRunRecord(
                    id=trigger_id,
                    automation_id=HTTP_TRIGGER_RUNS_KEY,
                    scheduled_for=_utc_now_iso(),
                    status=AutomationRunStatus.RUNNING,
                    created_at=_utc_now_iso(),
                    task_id=task.id,
                    delivery=delivery,
                )
            )
            # Reconcile walks every stored run each tick; trigger runs have
            # no scheduler tick to prune them.
            automation_manager.prune_runs(HTTP_TRIGGER_RUNS_KEY)
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
    from deepseek_tui.server.threads import TurnItemKind

    parts: list[str] = []
    for item in mgr.store.list_items_for_turn(turn_id):
        if item.kind is TurnItemKind.AGENT_MESSAGE and item.detail:
            parts.append(item.detail.strip())
    return "\n\n".join(parts).strip()


async def wait_thread_turn_text(
    mgr: RuntimeThreadManager,
    *,
    thread_id: str,
    turn_id: str | None = None,
    timeout_s: float = 300.0,
    poll_s: float = 1.0,
) -> str:
    """Poll until the active turn finishes; return last agent message text."""
    from deepseek_tui.server.threads import RuntimeTurnStatus

    if turn_id is None:
        turn_id = (await mgr.get_thread(thread_id)).latest_turn_id
    if not turn_id:
        return ""
    settled = (
        RuntimeTurnStatus.COMPLETED,
        RuntimeTurnStatus.FAILED,
        RuntimeTurnStatus.INTERRUPTED,
        RuntimeTurnStatus.CANCELED,
    )
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        turn = mgr.store.load_turn(turn_id)
        if turn.status in settled:
            break
        await asyncio.sleep(poll_s)
    turn = mgr.store.load_turn(turn_id)
    if turn.status not in settled:
        logger.warning(
            "[automation][feishu] turn not settled thread=%s turn=%s status=%s",
            thread_id,
            turn_id,
            turn.status,
        )
        # Whatever was written so far is a fragment, not the answer; the
        # turn keeps running, often on an approval only Workbench can give.
        from deepseek_tui.utils.user_text import user_text

        return user_text("turn_still_running")
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
    from deepseek_tui.server.threads import CreateThreadRequest, StartTurnRequest

    title = _claw_thread_title(chat_id, sender_id)
    thread = await _find_claw_thread(thread_manager, chat_id=chat_id, sender_id=sender_id)
    if thread is None:
        thread = await thread_manager.create_thread(
            CreateThreadRequest(
                mode="agent",
                auto_approve=False,
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
        StartTurnRequest(prompt=prompt, auto_approve=False),
    )
    summary = await wait_thread_turn_text(
        thread_manager,
        thread_id=thread.id,
        turn_id=turn.id,
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


TRIAGE_SKIP = "skip"
TRIAGE_RUN = "run"
TRIAGE_DEFER = "defer"
TRIAGE_DROP = "drop"


@dataclass(frozen=True, slots=True)
class TriageDecision:
    action: str
    reason: str = ""


def apply_triage(
    *,
    policy: str | None,
    prompt: str,
    metadata: dict[str, Any] | None = None,
) -> TriageDecision:
    """Decide whether an HTTP trigger should enqueue work.

    Scheduled cron jobs never call this — only ``POST /v1/triggers`` and similar.
    Default policy is ``skip`` (always run).
    """
    key = (policy or TRIAGE_SKIP).strip().lower()
    meta = metadata or {}

    if key in ("", TRIAGE_SKIP, "none", "off"):
        return TriageDecision(TRIAGE_RUN, "policy=skip")

    if key in ("run", "always", "allow"):
        return TriageDecision(TRIAGE_RUN, f"policy={key}")

    if key in ("defer", "hold", "queue"):
        return TriageDecision(TRIAGE_DEFER, f"policy={key}")

    if key in ("deny", "block", "drop"):
        return TriageDecision(TRIAGE_DROP, f"policy={key}")

    if key == "keyword":
        blocked = tuple(str(x).lower() for x in meta.get("block_keywords", ()))
        lowered = prompt.lower()
        for token in blocked:
            if token and token in lowered:
                logger.info("[automation][triage] blocked keyword=%s", token)
                return TriageDecision(TRIAGE_DROP, f"blocked keyword: {token}")
        return TriageDecision(TRIAGE_RUN, "keyword pass")

    # A typo in a blocking policy must not silently let everything through.
    raise ValueError(f"Unknown triage policy: {policy}")
