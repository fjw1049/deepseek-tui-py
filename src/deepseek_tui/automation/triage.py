"""Optional webhook triage (OpenHuman ``run_triage`` subset; cron always skips)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

TRIAGE_SKIP = "skip"
TRIAGE_RUN = "run"
TRIAGE_DEFER = "defer"


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

    Cron / RRULE jobs never call this — only ``POST /v1/triggers`` and similar.
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
        return TriageDecision(TRIAGE_DEFER, f"policy={key}")

    if key == "keyword":
        blocked = tuple(str(x).lower() for x in meta.get("block_keywords", ()))
        lowered = prompt.lower()
        for token in blocked:
            if token and token in lowered:
                logger.info("[automation][triage] blocked keyword=%s", token)
                return TriageDecision(TRIAGE_DEFER, f"blocked keyword: {token}")
        return TriageDecision(TRIAGE_RUN, "keyword pass")

    logger.warning("[automation][triage] unknown policy=%s — treating as skip", key)
    return TriageDecision(TRIAGE_RUN, "unknown policy fallback")
