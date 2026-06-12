"""Cycle/Seam capability adapter for Engine assembly."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from deepseek_tui.config.models import Config
from deepseek_tui.engine.cycle_manager import CycleConfig, archive_cycle, should_advance_cycle
from deepseek_tui.engine.seam_manager import SeamConfig, SeamManager
from deepseek_tui.host.engine_shell import EngineShell

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.protocol.messages import Message

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CycleRuntime:
    config: CycleConfig
    seam_manager: SeamManager | None
    session_id: str
    started_at: int


@dataclass(slots=True)
class CycleAdvanceResult:
    advanced: bool
    cycle_n: int
    started_at: int


def create_cycle_runtime(
    config: Config,
    *,
    client: LLMClient,
) -> CycleRuntime:
    seam_manager = None
    if bool(getattr(config, "seam_enabled", False)):
        seam_manager = SeamManager(
            flash_client=client,
            config=SeamConfig(enabled=True),
        )
    return CycleRuntime(
        config=CycleConfig(enabled=bool(getattr(config, "cycle_enabled", False))),
        seam_manager=seam_manager,
        session_id=uuid.uuid4().hex,
        started_at=int(time.time()),
    )


def attach_engine_cycle(
    shell: EngineShell,
    config: Config,
    *,
    client: LLMClient,
) -> CycleRuntime:
    """Wire cycle/seam runtime onto a materialized engine."""
    cycle_runtime = create_cycle_runtime(config, client=client)
    shell.cycle_config = cycle_runtime.config
    shell.seam_manager = cycle_runtime.seam_manager
    shell.cycle_session_id = cycle_runtime.session_id
    shell.cycle_started_at = cycle_runtime.started_at
    return cycle_runtime


async def apply_layered_context_checkpoint(
    *,
    seam_manager: object | None,
    messages: list[Message],
    working_set: object,
    workspace: object,
) -> None:
    if not isinstance(seam_manager, SeamManager) or not seam_manager.config.enabled:
        return
    from deepseek_tui.engine.context import estimated_input_tokens
    from deepseek_tui.protocol.messages import Message

    try:
        tokens = estimated_input_tokens(messages)
    except Exception:  # noqa: BLE001
        return
    highest = await seam_manager.highest_level()
    level = seam_manager.seam_level_for(tokens, highest)
    if level is None:
        return
    msg_count = len(messages)
    verbatim_start = seam_manager.verbatim_window_start(msg_count)
    if verbatim_start <= 0:
        return
    pinned_fn = getattr(working_set, "pinned_message_indices", None)
    if not callable(pinned_fn):
        return
    pinned = pinned_fn(messages, workspace)
    try:
        existing = await seam_manager.collect_seam_texts(messages)
        if existing:
            recent = messages[:verbatim_start]
            seam_text = await seam_manager.recompact(
                existing, recent, level, 0, verbatim_start
            )
        else:
            seam_text = await seam_manager.produce_soft_seam(
                messages,
                level,
                0,
                verbatim_start,
                pinned_indices=sorted(pinned),
            )
    except Exception as err:  # noqa: BLE001
        logger.warning("layered_context_checkpoint failed: %s", err)
        return
    if seam_text and seam_text.strip():
        messages.append(Message.assistant(seam_text))


async def advance_cycle_if_needed(
    *,
    messages: list[Message],
    model: str,
    config: CycleConfig,
    session_id: str,
    cycle_n: int,
    started_at: int,
) -> CycleAdvanceResult:
    """Archive a full cycle to disk and trim history when threshold crossed."""
    current = CycleAdvanceResult(
        advanced=False,
        cycle_n=cycle_n,
        started_at=started_at,
    )
    if not messages:
        return current
    from deepseek_tui.engine.context import estimated_input_tokens

    try:
        active_tokens = estimated_input_tokens(messages)
    except Exception:  # noqa: BLE001
        return current
    if not should_advance_cycle(
        active_tokens,
        reserved_headroom_tokens=8_000,
        model=model,
        config=config,
        in_flight=False,
    ):
        return current
    logger.info(
        "cycle_advance_triggered cycle_n=%d active_tokens=%d msg_count=%d",
        cycle_n,
        active_tokens,
        len(messages),
    )
    try:
        archive_path = archive_cycle(
            session_id=session_id,
            cycle_n=cycle_n,
            messages=list(messages),
            model=model,
            started=started_at,
        )
        logger.info("cycle_archived path=%s", archive_path)
    except OSError as exc:
        logger.warning("cycle_archive_failed error=%s", exc)
        return current

    keep = min(8, len(messages))
    seed = messages[-keep:]
    messages.clear()
    messages.extend(seed)
    return CycleAdvanceResult(
        advanced=True,
        cycle_n=cycle_n + 1,
        started_at=int(time.time()),
    )
