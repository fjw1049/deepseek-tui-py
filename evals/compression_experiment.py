"""Opt-in compression A/B settings for isolated product evaluations.

Set EVAL_COMPRESSION_CAP=30000 (and optionally EVAL_COMPRESSION_BASELINE to a
saved capacity.py from the baseline revision). Both arms use the same trigger
and retention settings so the comparison isolates the summary algorithm.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def configure_compression() -> None:
    cap = os.environ.get("EVAL_COMPRESSION_CAP")
    if not cap:
        return
    from deepseek_tui.engine import capacity
    from deepseek_tui.engine.orchestrator import core, maintenance

    threshold = int(cap)
    if threshold <= 0:
        raise ValueError("EVAL_COMPRESSION_CAP must be positive")
    core.CompactionConfig = lambda: capacity.CompactionConfig(
        max_input_tokens=threshold,
        keep_recent_tokens=2000,
    )
    baseline = os.environ.get("EVAL_COMPRESSION_BASELINE")
    if baseline:
        spec = importlib.util.spec_from_file_location("eval_baseline_capacity", Path(baseline))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        maintenance.compact_messages_safe = module.compact_messages_safe
