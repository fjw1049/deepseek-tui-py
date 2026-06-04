"""Sub-agent runtime package.

Mirrors Rust ``crates/tui/src/tools/subagent/``.
"""

from deepseek_tui.tools.subagent.mailbox import (
    Mailbox,
    MailboxEnvelope,
    MailboxMessage,
    MailboxMessageKind,
)
from deepseek_tui.tools.subagent.output import AgentRunOutput
from deepseek_tui.tools.subagent.manager import (
    DEFAULT_MAX_AGENTS,
    DEFAULT_MAX_SPAWN_DEPTH,
    DEFAULT_MAX_STEPS,
    DEFAULT_RESULT_TIMEOUT_MS,
    MAX_RESULT_TIMEOUT_MS,
    MIN_WAIT_TIMEOUT_MS,
    SUBAGENT_RESTART_REASON,
    SUBAGENT_STATE_FILE,
    SpawnRequest,
    SubAgent,
    SubAgentAssignment,
    SubAgentExecutor,
    SubAgentManager,
    SubAgentResult,
    SubAgentRuntime,
    SubAgentStatus,
    SubAgentStatusKind,
    SubAgentType,
)

__all__ = [
    "AgentRunOutput",
    "DEFAULT_MAX_AGENTS",
    "DEFAULT_MAX_SPAWN_DEPTH",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_RESULT_TIMEOUT_MS",
    "MAX_RESULT_TIMEOUT_MS",
    "MIN_WAIT_TIMEOUT_MS",
    "Mailbox",
    "MailboxEnvelope",
    "MailboxMessage",
    "MailboxMessageKind",
    "SUBAGENT_RESTART_REASON",
    "SUBAGENT_STATE_FILE",
    "SpawnRequest",
    "SubAgent",
    "SubAgentAssignment",
    "SubAgentExecutor",
    "SubAgentManager",
    "SubAgentResult",
    "SubAgentRuntime",
    "SubAgentStatus",
    "SubAgentStatusKind",
    "SubAgentType",
]
