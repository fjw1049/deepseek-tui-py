"""Engine orchestrator package.

The former single-file orchestrator is split by responsibility:

- :mod:`.helpers`     — module-level locale/mode/summary helpers
- :mod:`.tooling`     — ToolExecutionMixin (dispatch, approval, elevation)
- :mod:`.maintenance` — SessionMaintenanceMixin (checkpoints, compaction, cycles)
- :mod:`.lifecycle`   — LifecycleLspMixin (hooks + LSP diagnostics)
- :mod:`.core`        — the Engine class itself

``deepseek_tui.engine.orchestrator`` keeps re-exporting the public names.
"""

from deepseek_tui.engine.orchestrator.core import Engine
from deepseek_tui.engine.orchestrator.helpers import (  # noqa: F401 — used by server routes/tests
    _summarize_call_args,
)

__all__ = ["Engine"]
