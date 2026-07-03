"""Sub-agent spawning, communication, and delegation.

Split by responsibility:

- :mod:`.types`      — constants, SubAgentType/prompts, status + request models
- :mod:`.mailbox`    — lifecycle/progress event stream
- :mod:`.completion` — completion payloads and run-output types
- :mod:`.agent`      — SubAgent handle + executor plumbing
- :mod:`.manager`    — SubAgentManager + SubAgentRuntime
- :mod:`.loop`       — run_subagent_loop executor
- :mod:`.tools`      — the 10 agent_* tools registered with the ToolRegistry

``deepseek_tui.tools.subagent`` keeps re-exporting the public names.
"""

from deepseek_tui.tools.subagent.agent import (  # noqa: F401 — _stub_executor used by tests
    SubAgent,
    SubAgentExecutor,
    _stub_executor,
    get_real_subagent_executor,
)
from deepseek_tui.tools.subagent.completion import (
    AgentRunOutput,
    SubAgentCompletion,
    build_completion_payload,
    subagent_done_sentinel,
    summarize_subagent_result,
)
from deepseek_tui.tools.subagent.loop import run_subagent_loop
from deepseek_tui.tools.subagent.mailbox import (
    MAILBOX_MAX_ENVELOPES,
    Mailbox,
    MailboxEnvelope,
    MailboxMessage,
    MailboxMessageKind,
)
from deepseek_tui.tools.subagent.manager import SubAgentManager, SubAgentRuntime
from deepseek_tui.tools.subagent.tools import (
    AgentAssignTool,
    AgentCancelTool,
    AgentCloseTool,
    AgentListTool,
    AgentResultTool,
    AgentResumeTool,
    AgentSendInputTool,
    AgentSpawnTool,
    AgentWaitTool,
    DelegateToAgentTool,
)
from deepseek_tui.tools.subagent.types import (  # noqa: F401 — _MAX_CARD_RESULT_CHARS used by tests
    DEFAULT_MAX_AGENTS,
    DEFAULT_MAX_SPAWN_DEPTH,
    DEFAULT_MAX_STEPS,
    DEFAULT_RESULT_TIMEOUT_MS,
    MAX_RESULT_TIMEOUT_MS,
    MIN_WAIT_TIMEOUT_MS,
    SUBAGENT_RESTART_REASON,
    SUBAGENT_STATE_FILE,
    SUBAGENT_STATE_SCHEMA_VERSION,
    _MAX_CARD_RESULT_CHARS,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentResult,
    SubAgentStatus,
    SubAgentStatusKind,
    SubAgentType,
    build_subagent_system_prompt,
    whale_nickname_for_index,
)

__all__ = [
    "MAILBOX_MAX_ENVELOPES",
    "AgentAssignTool",
    "AgentCancelTool",
    "AgentCloseTool",
    "AgentListTool",
    "AgentResultTool",
    "AgentResumeTool",
    "AgentRunOutput",
    "AgentSendInputTool",
    "AgentSpawnTool",
    "AgentWaitTool",
    "DEFAULT_MAX_AGENTS",
    "DEFAULT_MAX_SPAWN_DEPTH",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_RESULT_TIMEOUT_MS",
    "DelegateToAgentTool",
    "MAX_RESULT_TIMEOUT_MS",
    "MIN_WAIT_TIMEOUT_MS",
    "Mailbox",
    "MailboxEnvelope",
    "MailboxMessage",
    "MailboxMessageKind",
    "SUBAGENT_RESTART_REASON",
    "SUBAGENT_STATE_FILE",
    "SUBAGENT_STATE_SCHEMA_VERSION",
    "SpawnRequest",
    "SubAgent",
    "SubAgentAssignment",
    "SubAgentCompletion",
    "SubAgentExecutor",
    "SubAgentManager",
    "SubAgentResult",
    "SubAgentRuntime",
    "SubAgentStatus",
    "SubAgentStatusKind",
    "SubAgentType",
    "build_completion_payload",
    "build_subagent_system_prompt",
    "get_real_subagent_executor",
    "run_subagent_loop",
    "subagent_done_sentinel",
    "summarize_subagent_result",
    "whale_nickname_for_index",
]
