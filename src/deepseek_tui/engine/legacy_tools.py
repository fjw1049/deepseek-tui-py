"""Compatibility adapters for retired tool names and action shapes."""

import logging
from typing import Any

# Preserve the existing logger name for installed log collectors.
logger = logging.getLogger("deepseek_tui.engine.dispatch")


def normalize_legacy_tool_call(name: str, arguments: Any) -> tuple[str, Any]:
    mapped_name, mapped_args = _normalize_legacy_tool_call(name, arguments)
    if mapped_name != name or mapped_args is not arguments:
        logger.info("legacy_tool_used name=%s replacement=%s count=1", name, mapped_name)
    return mapped_name, mapped_args


def _normalize_legacy_tool_call(name: str, arguments: Any) -> tuple[str, Any]:
    """Fold retired tool names onto their merged successors (debug-logged).

    The schema only advertises the merged tools; the old names keep working
    at the execution layer for one deprecation cycle, forwarding to the same
    logic:

    - ``agent_resume {agent_id}`` → ``agent {resume: agent_id}``
    - ``agent(action=list)`` → ``task_list``; ``agent(action=result)`` →
      ``task_output``; ``agent(action=cancel)`` → ``task_stop`` (the merged
      task tools took over background-entity inspect/stop; ids and
      block/timeout_ms already share the target parameter names). A
      ``result`` call carrying ``agent_ids``/``wait_mode`` is **not**
      forwarded — it was never valid for ``result`` and the unknown-action
      error steers the model.
    - ``exec_shell_interact {process_id, input, close_stdin}`` →
      ``exec_shell`` with the same arguments (names already match the
      merged interact branch).
    - ``task_read`` → ``task_output``; ``task_cancel`` → ``task_stop``;
      ``task_resume {task_id}`` → ``task_create(resume=...)``;
      ``task_shell_wait`` → ``task_output(process_id=..., task_id=...)``
      (arguments pass through; names already match).
    - ``task_shell_start {command, pty}`` → ``exec_shell(command=...,
      background=true, pty=true)``. The old task_id → process_id ownership
      mapping (``task_shell_process_ids``) is dropped — the merged surface
      tracks background processes independently of durable tasks.
    - ``automation_create`` → ``cron_create`` (arguments pass through)
    - ``automation_list`` → ``cron_list``; ``automation_read`` →
      ``cron_list(automation_id=...)``
    - ``automation_delete`` → ``cron_delete``
    - ``automation_update`` → ``cron_update``; ``automation_pause`` /
      ``automation_resume`` → ``cron_update(paused=true/false)``

    ``task_gate_run`` is intentionally **not** forwarded: the gate heuristic
    survives only in the implementation layer (decision D3), so the
    unknown-tool error steers the model off the retired surface. Same for
    ``automation_run`` (run = ``cron_create(run_now=true)``).
    """
    if name == "agent_resume":
        logger.debug("legacy tool name 'agent_resume' used; forwarding to agent(resume=...)")
        args = dict(arguments) if isinstance(arguments, dict) else {}
        agent_id = args.pop("agent_id", None) or args.pop("id", None)
        if isinstance(agent_id, str) and agent_id and "resume" not in args:
            args["resume"] = agent_id
        return "agent", args
    if name == "agent" and isinstance(arguments, dict):
        action = arguments.get("action")
        if action == "list":
            logger.debug("legacy agent action 'list' used; forwarding to task_list")
            # include_archived has no equivalent on the merged surface.
            return "task_list", {}
        if action == "result":
            if "agent_ids" in arguments or "wait_mode" in arguments:
                # Multi-id wait_mode calls were never valid for 'result' —
                # leave them to the unknown-action steering error.
                return name, arguments
            logger.debug("legacy agent action 'result' used; forwarding to task_output")
            args = {
                k: v
                for k, v in arguments.items()
                if k in ("agent_id", "process_id", "id", "block", "timeout_ms")
            }
            return "task_output", args
        if action == "cancel":
            logger.debug("legacy agent action 'cancel' used; forwarding to task_stop")
            args = {k: v for k, v in arguments.items() if k in ("agent_id", "process_id", "id")}
            return "task_stop", args
        return name, arguments
    if name == "exec_shell_interact":
        logger.debug(
            "legacy tool name 'exec_shell_interact' used; forwarding to exec_shell(process_id=...)"
        )
        return "exec_shell", arguments
    if name == "task_read":
        logger.debug("legacy tool name 'task_read' used; forwarding to task_output")
        return "task_output", arguments
    if name == "task_cancel":
        logger.debug("legacy tool name 'task_cancel' used; forwarding to task_stop")
        return "task_stop", arguments
    if name == "task_resume":
        logger.debug("legacy tool name 'task_resume' used; forwarding to task_create(resume=...)")
        args = dict(arguments) if isinstance(arguments, dict) else {}
        task_id = args.pop("task_id", None) or args.pop("id", None)
        if isinstance(task_id, str) and task_id and "resume" not in args:
            args["resume"] = task_id
        return "task_create", args
    if name == "task_shell_wait":
        logger.debug(
            "legacy tool name 'task_shell_wait' used; forwarding to task_output(process_id=...)"
        )
        args = dict(arguments) if isinstance(arguments, dict) else {}
        # The old tool always blocked until the process exited.
        args.setdefault("block", True)
        return "task_output", args
    if name == "task_shell_start":
        logger.debug(
            "legacy tool name 'task_shell_start' used; forwarding to exec_shell(background=true)"
        )
        args = dict(arguments) if isinstance(arguments, dict) else {}
        # The task_id → process_id ownership mapping is dropped (see docstring).
        args.pop("task_id", None)
        args.pop("id", None)
        args["background"] = True
        args.setdefault("pty", True)
        return "exec_shell", args
    if name == "automation_create":
        logger.debug("legacy tool name 'automation_create' used; forwarding to cron_create")
        return "cron_create", arguments
    if name in ("automation_list", "automation_read"):
        logger.debug("legacy tool name %r used; forwarding to cron_list", name)
        return "cron_list", arguments
    if name == "automation_delete":
        logger.debug("legacy tool name 'automation_delete' used; forwarding to cron_delete")
        return "cron_delete", arguments
    if name in ("automation_update", "automation_pause", "automation_resume"):
        logger.debug("legacy tool name %r used; forwarding to cron_update", name)
        args = dict(arguments) if isinstance(arguments, dict) else {}
        if name != "automation_update":
            args = {
                "automation_id": args.get("automation_id") or args.get("id"),
                "paused": name == "automation_pause",
            }
        return "cron_update", args
    return name, arguments
