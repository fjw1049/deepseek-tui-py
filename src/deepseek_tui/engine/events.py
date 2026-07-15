"""Engine event types and stream batching.

Consolidates events.py and streaming.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from deepseek_tui.policy.approval import ApprovalRequest
from deepseek_tui.protocol.messages import ContentBlock, Message, Role, TextBlock, ThinkingBlock
from deepseek_tui.protocol.responses import ToolCall, Usage

if TYPE_CHECKING:
    from deepseek_tui.tools.subagent import MailboxMessage


@dataclass(frozen=True, slots=True)
class StatusEvent:
    message: str


@dataclass(frozen=True, slots=True)
class TurnStartedEvent:
    user_text: str


@dataclass(frozen=True, slots=True)
class TextDeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class ThinkingDeltaEvent:
    thinking: str


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    tool_call: ToolCall


@dataclass(frozen=True, slots=True)
class AgentRoundCompleteEvent:
    """One LLM round finished; ``tool_calls`` empty means terminal round."""

    round_idx: int
    tool_calls: tuple[ToolCall, ...] = ()
    preface_text: str | None = None
    round_thinking: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    tool_call_id: str
    tool_name: str
    content: str
    success: bool
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ApprovalRequiredEvent:
    tool_call_id: str
    request: ApprovalRequest


@dataclass(frozen=True, slots=True)
class ApprovalResolvedEvent:
    tool_call_id: str
    approved: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SandboxDeniedEvent:
    tool_call_id: str
    tool_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ElevationRequiredEvent:
    """L3 sandbox: OS policy blocked the shell call; user may elevate once."""

    tool_call_id: str
    tool_name: str
    reason: str
    elevation_kind: str
    command_preview: str = ""


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class TurnCancelledEvent:
    reason: str


@dataclass(frozen=True, slots=True)
class SubAgentMailboxEvent:
    """Structured sub-agent progress."""

    seq: int
    message: MailboxMessage


@dataclass(frozen=True, slots=True)
class WorkflowProgressEvent:
    """Workflow orchestration progress while the ``workflow`` tool runs."""

    tool_call_id: str
    thread_id: str | None
    workflow_name: str
    snapshot: object
    completed: bool = False
    status: str = "running"
    run_id: str | None = None


@dataclass(frozen=True, slots=True)
class SessionActivityEvent:
    """Background work snapshot (sub-agents + durable tasks)."""

    running_subagents: int
    running_tasks: int
    message: str = ""


@dataclass(frozen=True, slots=True)
class TurnCompleteEvent:
    assistant_message: Message | None
    usage: Usage | None = None
    # False when the turn ended in a failure outcome (stream timeout,
    # context overflow, ...). Consumers must not mark the turn as
    # completed-successfully in that case.
    success: bool = True
    error_message: str | None = None
    # Cumulative session cost (USD) — populated when ``Engine`` knows
    # how to price the model. ``None`` when pricing is unknown (off-
    # platform providers, unrecognised model) so the UI can hide rather
    # than show a misleading zero.
    session_cost_usd: float | None = None
    session_cost_cny: float | None = None
    # Convenience snapshot so the UI can render the cache-hit chip
    # without having to keep state of its own. Both default to 0 when
    # the provider didn't return cache details.
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    # Non-blocking background work still running after this turn ends.
    running_subagents: int = 0
    running_tasks: int = 0


@dataclass(frozen=True, slots=True)
class UserInputRequiredEvent:
    tool_call_id: str
    questions: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class PluginMountEvent:
    """Session-level plugin mount/unmount state change.

    Emitted when the user mounts (``@plugin:<name>``) or unmounts
    (``@plugin:off``) a plugin. ``name is None`` means unmounted. The server
    persists the structured fields as turn-item metadata (``active_plugin``)
    so the UI can render a persistent chip that survives reload; ``message``
    is the human line shown in the transcript.
    """

    name: str | None
    version: str = ""
    path: str = ""
    scope: str = ""
    trusted: bool = False
    permissions: tuple[str, ...] = ()
    mcp_active: bool = False
    message: str = ""



@dataclass(frozen=True, slots=True)
class SessionStartedEvent:
    session_id: str


@dataclass(frozen=True, slots=True)
class SessionEndedEvent:
    session_id: str
    turns: int


EngineEvent = (
    StatusEvent
    | TurnStartedEvent
    | TextDeltaEvent
    | ThinkingDeltaEvent
    | ToolCallEvent
    | AgentRoundCompleteEvent
    | ToolResultEvent
    | ApprovalRequiredEvent
    | ApprovalResolvedEvent
    | SandboxDeniedEvent
    | ElevationRequiredEvent
    | ErrorEvent
    | TurnCancelledEvent
    | TurnCompleteEvent
    | SubAgentMailboxEvent
    | WorkflowProgressEvent
    | SessionActivityEvent
    | UserInputRequiredEvent
    | PluginMountEvent
    | SessionStartedEvent
    | SessionEndedEvent
)


# Fake-wrapper filtering.
# Some models try to forge tool calls in plain text instead of using the
# structured tool channel. We strip those wrappers so they don't pollute
# the visible transcript.

TOOL_CALL_START_MARKERS: tuple[str, ...] = (
    "[TOOL_CALL]",
    "<deepseek:tool_call",
    "<tool_call",
    "<invoke ",
    "<function_calls>",
)

TOOL_CALL_END_MARKERS: tuple[str, ...] = (
    "[/TOOL_CALL]",
    "</deepseek:tool_call>",
    "</tool_call>",
    "</invoke>",
    "</function_calls>",
)

FAKE_WRAPPER_NOTICE = (
    "Stripped non-API tool-call wrapper from model output "
    "(use the API tool channel)"
)


def contains_fake_tool_wrapper(text: str) -> bool:
    """Return True if *text* contains any known fake-wrapper start marker."""
    return any(m in text for m in TOOL_CALL_START_MARKERS)


def _find_first_marker(text: str, markers: tuple[str, ...]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for marker in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        if best is None or idx < best[0]:
            best = (idx, len(marker))
    return best


@dataclass(slots=True)
class FakeWrapperFilter:
    """Stateful filter that strips fake tool-call wrappers across stream deltas.

    The ``in_tool_call`` flag persists across calls so a wrapper that spans
    chunk boundaries still gets stripped.
    """

    in_tool_call: bool = False

    def filter(self, delta: str) -> str:
        if not delta:
            return ""

        out: list[str] = []
        rest = delta
        while True:
            if self.in_tool_call:
                hit = _find_first_marker(rest, TOOL_CALL_END_MARKERS)
                if hit is None:
                    break
                idx, length = hit
                rest = rest[idx + length:]
                self.in_tool_call = False
            else:
                hit = _find_first_marker(rest, TOOL_CALL_START_MARKERS)
                if hit is None:
                    out.append(rest)
                    break
                idx, length = hit
                out.append(rest[:idx])
                rest = rest[idx + length:]
                self.in_tool_call = True
        return "".join(out)


@dataclass(slots=True)
class AssistantResponseBuffer:
    text_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)

    def append_text(self, text: str) -> None:
        self.text_parts.append(text)

    def append_thinking(self, thinking: str) -> None:
        self.thinking_parts.append(thinking)

    def has_output(self) -> bool:
        return bool(self.text_parts or self.thinking_parts)

    def build_message(self) -> Message | None:
        if not self.text_parts and not self.thinking_parts:
            return None
        blocks: list[ContentBlock] = []
        if self.thinking_parts:
            blocks.append(ThinkingBlock(thinking="".join(self.thinking_parts)))
        if self.text_parts:
            blocks.append(TextBlock(text="".join(self.text_parts)))
        return Message(role=Role.ASSISTANT, content=blocks)
