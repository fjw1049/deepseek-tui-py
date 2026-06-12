"""Automation trigger pipeline (cron → task → optional delivery).

Kept small on purpose: types + pipeline only. Scheduler persistence stays
in ``tools.automation_manager``.
"""

from deepseek_tui.automation.inbox import append_feishu_inbound, feishu_send_text
from deepseek_tui.automation.pipeline import (
    build_final_prompt,
    build_trigger_prompt,
    enqueue_automation_task,
    fire_http_trigger,
    run_feishu_inbound_agent,
    try_deliver_completed_run,
)
from deepseek_tui.automation.pipeline import apply_triage
from deepseek_tui.automation.delivery import DeliveryConfig, DigestConfig

__all__ = [
    "DeliveryConfig",
    "DigestConfig",
    "append_feishu_inbound",
    "apply_triage",
    "build_final_prompt",
    "build_trigger_prompt",
    "enqueue_automation_task",
    "feishu_send_text",
    "fire_http_trigger",
    "run_feishu_inbound_agent",
    "try_deliver_completed_run",
]
