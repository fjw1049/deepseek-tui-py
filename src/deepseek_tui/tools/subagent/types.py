"""Sub-agent core types: constants, agent types/prompts, status and request models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def _epoch_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


DEFAULT_MAX_STEPS = 100
DEFAULT_MAX_AGENTS = 10
DEFAULT_MAX_SPAWN_DEPTH = 3
# Per-round LLM output caps for the sub-agent loop. Read-heavy types stay
# smaller; write/general types need headroom for patches and long reports.
SUBAGENT_MAX_TOKENS_READ = 8_192
SUBAGENT_MAX_TOKENS_WRITE = 16_384
_MAX_TERMINAL_AGENTS_IN_MEMORY = 30
# Upper bound for the final result we surface on the Workbench sub-agent card.
# The previous 500-char cap chopped real reports mid-sentence; the card detail
# dialog is the user's only window onto a sub-agent's deliverable, so keep it
# generous while still bounding pathological outputs.
_MAX_CARD_RESULT_CHARS = 16_000
DEFAULT_RESULT_TIMEOUT_MS = 180_000
MIN_WAIT_TIMEOUT_MS = 30_000
MAX_RESULT_TIMEOUT_MS = 3_600_000
SUBAGENT_STATE_SCHEMA_VERSION = 1
SUBAGENT_STATE_FILE = "subagents.v1.json"
SUBAGENT_RESTART_REASON = "Interrupted by process restart"


class SubAgentType(str, Enum):
    GENERAL = "general"
    EXPLORE = "explore"
    PLAN = "plan"
    REVIEW = "review"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    CUSTOM = "custom"

    @staticmethod
    def parse(raw: str) -> SubAgentType | None:
        """Accepts aliases (general_purpose, worker, etc.)."""
        key = raw.strip().lower().replace("-", "_")
        aliases: dict[str, SubAgentType] = {
            "general": SubAgentType.GENERAL,
            "general_purpose": SubAgentType.GENERAL,
            "worker": SubAgentType.GENERAL,
            "default": SubAgentType.GENERAL,
            "explore": SubAgentType.EXPLORE,
            "exploration": SubAgentType.EXPLORE,
            "explorer": SubAgentType.EXPLORE,
            "plan": SubAgentType.PLAN,
            "planning": SubAgentType.PLAN,
            "awaiter": SubAgentType.PLAN,
            "review": SubAgentType.REVIEW,
            "code_review": SubAgentType.REVIEW,
            "reviewer": SubAgentType.REVIEW,
            "implementer": SubAgentType.IMPLEMENTER,
            "implement": SubAgentType.IMPLEMENTER,
            "implementation": SubAgentType.IMPLEMENTER,
            "builder": SubAgentType.IMPLEMENTER,
            "verifier": SubAgentType.VERIFIER,
            "verify": SubAgentType.VERIFIER,
            "verification": SubAgentType.VERIFIER,
            "validator": SubAgentType.VERIFIER,
            "tester": SubAgentType.VERIFIER,
            "custom": SubAgentType.CUSTOM,
        }
        return aliases.get(key)

    def type_prompt(self) -> str:
        """Persona / method body for this agent type (no output contract)."""
        return _SUBAGENT_PROMPTS.get(self.value, "")

    def system_prompt(self) -> str:
        """Return the system prompt for this agent type (with markdown report)."""
        from deepseek_tui.engine.prompts import load_prompt

        output_contract = load_prompt("sub_output")
        base = self.type_prompt()
        return f"{base}\n\n{output_contract}" if base else output_contract

    def allowed_tools(self) -> frozenset[str] | None:
        """Default tool allowlist for this type, or None to keep the full registry.

        Enforced at spawn via ``ToolRegistry.filter_by_names``: filtered tools
        are removed from the sub-agent's registry, so the model never sees them
        and they cannot be reached at execute time. ``None`` (GENERAL, CUSTOM)
        means "do not filter"; CUSTOM still requires the caller to pass an
        explicit ``allowed_tools`` list.
        """
        return _TYPE_ALLOWLIST.get(self)

    def max_tokens(self) -> int:
        """Per-round ``max_tokens`` for this agent type's LLM requests."""
        return max_tokens_for_subagent_type(self)


def max_tokens_for_subagent_type(agent_type: SubAgentType) -> int:
    """Return the sub-agent loop output token cap for *agent_type*."""
    if agent_type in (
        SubAgentType.EXPLORE,
        SubAgentType.PLAN,
        SubAgentType.REVIEW,
        SubAgentType.VERIFIER,
    ):
        return SUBAGENT_MAX_TOKENS_READ
    return SUBAGENT_MAX_TOKENS_WRITE


# Tool groups for type-based allowlists (see ``SubAgentType.allowed_tools``).
# Intentionally stricter than focus bases (``FOCUS_PLUGIN_BASE`` / deprecated
# alias ``FOCUS_READ_BASE`` include write/shell/agent) — cannot serve read-only.
_SUBAGENT_READ_TOOLS = frozenset({
    "read_file", "grep_files", "file_search",
    "web_search", "fetch_url",
    "note",
})
_SUBAGENT_PLAN_TOOLS = _SUBAGENT_READ_TOOLS | frozenset({
    "update_plan", "checklist",
})
_SUBAGENT_WRITE_TOOLS = frozenset({"write_file", "edit_file"})
_SUBAGENT_EXEC_TOOLS = frozenset({"exec_shell"})

_TYPE_ALLOWLIST: dict[SubAgentType, frozenset[str] | None] = {
    SubAgentType.GENERAL: None,
    SubAgentType.EXPLORE: _SUBAGENT_READ_TOOLS,
    SubAgentType.PLAN: _SUBAGENT_PLAN_TOOLS,
    SubAgentType.REVIEW: _SUBAGENT_READ_TOOLS,
    SubAgentType.IMPLEMENTER: (
        _SUBAGENT_READ_TOOLS
        | _SUBAGENT_WRITE_TOOLS
        | _SUBAGENT_EXEC_TOOLS
        | frozenset({"update_plan", "checklist"})
    ),
    SubAgentType.VERIFIER: _SUBAGENT_READ_TOOLS | _SUBAGENT_EXEC_TOOLS,
    SubAgentType.CUSTOM: None,
}


def resolve_subagent_model(agent_type: SubAgentType, cfg: Any) -> str | None:
    """Resolve a per-type model override from ``cfg.subagents``.

    Priority: ``subagents.models[type.value]`` overrides the type-specific
    fields (explorer/worker/review/custom_model). Returns None when no
    override is set so the caller falls back to ``default_model`` /
    ``default_text_model``.
    """
    sub = getattr(cfg, "subagents", None)
    if sub is None:
        return None
    overrides = getattr(sub, "models", None) or {}
    explicit = overrides.get(agent_type.value)
    if explicit:
        return explicit
    field = {
        SubAgentType.EXPLORE: "explorer_model",
        SubAgentType.REVIEW: "review_model",
        SubAgentType.IMPLEMENTER: "worker_model",
        SubAgentType.VERIFIER: "worker_model",
        SubAgentType.PLAN: "explorer_model",
        SubAgentType.CUSTOM: "custom_model",
    }.get(agent_type)
    if field is None:
        return None
    value = getattr(sub, field, None)
    return value or None


_SUBAGENT_PROMPTS: dict[str, str] = {
    "general": (
        "You are a general-purpose sub-agent spawned to handle a specific task autonomously.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Your scope is exactly what the parent assigned to you. Do not expand the\n"
        "objective — if you discover related work that needs doing, surface it under\n"
        "RISKS or BLOCKERS rather than starting it. Work autonomously: the parent is\n"
        "not available to answer questions mid-run.\n\n"
        "Plan before you act. Use `checklist` for any multi-step task so your work\n"
        "is visible in the parent's sidebar. For complex initiatives, layer\n"
        "`update_plan` (strategy) above `checklist` (tactics)."
    ),
    "explore": (
        "You are an exploration sub-agent. Your job is to map the relevant region\n"
        "of the codebase fast and report what is there. You are read-only by\n"
        "convention — do not write, patch, or run side-effectful commands. If the\n"
        "task seems to require a write, stop and put it under BLOCKERS.\n\n"
        "Method:\n"
        "- Start with `file_search` and `grep_files` to orient.\n"
        "- Use `grep_files` (NOT `exec_shell rg`) to find call sites, type defs,\n"
        "  and string literals. Prefer narrow, structured queries over broad scans.\n"
        "- Read each candidate file with `read_file`. Skim, then quote line ranges.\n"
        "- Stop reading once you have enough evidence — exhaustive sweeps are not\n"
        "  the goal. The parent will spawn a follow-up explorer if needed.\n\n"
        "EVIDENCE is the load-bearing section for explorers. Cite every file you\n"
        "read with `path:line-range` and one line per finding.\n\n"
        "CHANGES will almost always be \"None.\" for an explorer."
    ),
    "plan": (
        "You are a planning sub-agent. Your job is to take an objective and\n"
        "produce a prioritized, executable plan — not to execute it. Keep writes\n"
        "to a minimum (notes and plan artifacts only); avoid patches and shell\n"
        "side effects.\n\n"
        "Method:\n"
        "- Read enough of the codebase to ground the plan in reality.\n"
        "- Decompose the objective into ordered, verifiable steps.\n"
        "- Surface trade-offs explicitly. If two approaches are viable, name both\n"
        "  and pick one with a reason.\n"
        "- Use `update_plan` to record the strategy and `checklist` for the backlog.\n\n"
        "Prioritization: order todos by dependency graph first, then by risk/effort ratio.\n"
        "Tag each item with `[P0]` / `[P1]` / `[P2]`."
    ),
    "review": (
        "You are a code review sub-agent. Your job is to read the code under\n"
        "review and emit a severity-scored list of findings. You are read-only by\n"
        "convention — do not patch the code.\n\n"
        "For each finding, score severity: BLOCKER / MAJOR / MINOR / NIT.\n"
        "Order EVIDENCE bullets by severity, BLOCKER first.\n\n"
        "CHANGES will almost always be \"None.\" for a reviewer."
    ),
    "implementer": (
        "You are an implementation sub-agent. Your job is to land the change\n"
        "the parent assigned — write the code, modify the files, satisfy the\n"
        "contract — with the minimum surrounding edit. Do not refactor adjacent code.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Method:\n"
        "- Read target file(s) end-to-end before editing.\n"
        "- Prefer `edit_file` for narrow changes, `write_file` for new files or full rewrites.\n"
        "- Never mutate source via exec_shell (sed/python/heredoc); use edit tools.\n"
        "- After edits, run a quick verification (lint/test).\n"
        "- If tests are needed, write them alongside the implementation.\n\n"
        "CHANGES is the load-bearing section — list every file modified with a one-line summary."
    ),
    "verifier": (
        "You are a verification sub-agent. Your job is to run the project's\n"
        "test suite and report pass/fail with evidence. You are read-only —\n"
        "do not patch failing tests or modify code.\n\n"
        "Method:\n"
        "- Run the right gate with `exec_shell` (the project's test command).\n"
        "- Capture the exact failing assertion plus stack trace in EVIDENCE.\n\n"
        "OUTCOME goes at the top of SUMMARY: PASS / FAIL / FLAKY.\n\n"
        "CHANGES will almost always be \"None.\" for a verifier."
    ),
    "custom": (
        "You are a custom sub-agent. The parent has given you a narrowed tool\n"
        "registry — only the tools you see at runtime are available. Do not try\n"
        "to reach for a tool that is not registered; if the task needs one, put\n"
        "the gap under BLOCKERS and stop.\n\n"
        "CRITICAL: File operations are sandboxed to the workspace directory.\n"
        "- ALWAYS use relative paths (e.g., 'script.py', './src/utils.py', 'bubble_sort.py')\n"
        "- NEVER use absolute paths (e.g., '/tmp/...', '/Users/...', '~/...', '/var/...')\n"
        "- If the parent's prompt mentions an absolute path like '/tmp/file.py', ignore the path\n"
        "  and use just the filename 'file.py' instead\n"
        "- All file operations are relative to the workspace root\n\n"
        "Stay tightly scoped to the assigned objective."
    ),
}


_WHALE_NICKNAMES: tuple[str, ...] = (
    "Blue",
    "Humpback",
    "Sperm",
    "Orca",
    "Beluga",
    "Narwhal",
    "Pilot",
    "Minke",
)


def whale_nickname_for_index(index: int) -> str:
    base = _WHALE_NICKNAMES[index % len(_WHALE_NICKNAMES)]
    if index < len(_WHALE_NICKNAMES):
        return base
    return f"{base} {index // len(_WHALE_NICKNAMES) + 1}"


_LOCALE_PROSE: dict[str, str] = {
    "zh": "Simplified Chinese",
    "en": "English",
}


def subagent_environment_block(locale_tag: str | None = None) -> str:
    """Render the sub-agent ``## Environment`` block.

    Children never inherit the parent's Environment block, so the date
    (read-only types carry ``web_search`` / ``fetch_url``, where a wrong
    "today" skews freshness judgements), the locale, and the platform
    (``exec_shell`` portability) have to be restated here.

    Every field is process-constant, so sibling sub-agents of the same type
    get a byte-identical system prefix and keep their KV cache hits. Per-spawn
    values — notably the child's workspace — deliberately stay out: tools
    already resolve relative
    paths against ``agent.workspace``, so the path is enforced structurally
    rather than described in the prompt.
    """
    import sys

    from deepseek_tui.engine.prompts import process_today

    lines = [f"- today: {process_today()}"]
    if (locale_tag or "").strip().lower() in _LOCALE_PROSE:
        lines.append(f"- lang: {locale_tag}")
    lines.append(f"- platform: {sys.platform}")
    body = "\n".join(lines)
    return (
        f"## Environment\n\n{body}\n\n"
        "`today` is captured at process start and can be stale in a long "
        "run; when freshness actually matters and you have a shell tool, "
        "read the real time with `date`."
    )


def language_directive(locale_tag: str | None) -> str | None:
    """User-visible-language directive injected into sub-agent prompts.

    Sub-agents never see the parent's system prompt or its ``## Environment``
    block, so the session locale must be stated here explicitly — inferring
    it from the assignment's language proved unreliable (children narrate in
    English when the rest of their prompt is English).
    """
    name = _LOCALE_PROSE.get((locale_tag or "").strip().lower())
    if name is None:
        return None
    return (
        "## Language\n\n"
        f"Write ALL user-visible natural language in {name} "
        f"(lang: {locale_tag}): your reasoning, progress notes between tool "
        "calls, checklist item texts, and the report body. This applies "
        "regardless of the language of this prompt or of the assignment. "
        "Code, file paths, identifiers, tool names, flags, log lines, and "
        "machine-parsed structural markers (e.g. the ### SUMMARY / EVIDENCE "
        "/ CHANGES / RISKS / BLOCKERS report headings) stay in their "
        "original form."
    )


def build_subagent_system_prompt(
    agent_type: SubAgentType,
    assignment: SubAgentAssignment,
    base_override: str | None = None,
    *,
    include_markdown_report_contract: bool = True,
    locale_tag: str | None = None,
) -> str:
    """Build the sub-agent system prompt.

    ``base_override`` supplies the persona body for a plugin agent
    (Claude Code ``agents/<name>.md``). When set it replaces the built-in
    type prompt.

    ``include_markdown_report_contract`` attaches the shared five-section
    Output contract. Set it False when the run uses ``structured_output``
    (JSON schema) so only one final-delivery contract is in force.

    ``locale_tag`` (``zh`` / ``en``) feeds the child's own ``## Environment``
    block plus an explicit user-visible-language directive; children inherit
    nothing from the parent's system prompt.
    """
    if base_override is not None and base_override.strip():
        base = base_override.strip()
    else:
        base = agent_type.type_prompt()

    if include_markdown_report_contract:
        from deepseek_tui.engine.prompts import load_prompt

        output_contract = load_prompt("sub_output")
        base = f"{base}\n\n{output_contract}" if base else output_contract

    environment = subagent_environment_block(locale_tag)
    base = f"{base}\n\n{environment}" if base else environment

    directive = language_directive(locale_tag)
    if directive:
        base = f"{base}\n\n{directive}"

    role = (assignment.role or "").strip()
    if role:
        return f"{base}\n\nYou are operating in the role of `{role}`."
    return base

class SubAgentStatusKind(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True, frozen=True)
class SubAgentStatus:
    kind: SubAgentStatusKind
    message: str | None = None

    @staticmethod
    def running() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.RUNNING)

    @staticmethod
    def completed() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.COMPLETED)

    @staticmethod
    def interrupted(msg: str) -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.INTERRUPTED, msg)

    @staticmethod
    def failed(msg: str) -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.FAILED, msg)

    @staticmethod
    def cancelled() -> SubAgentStatus:
        return SubAgentStatus(SubAgentStatusKind.CANCELLED)

    def is_terminal(self) -> bool:
        return self.kind is not SubAgentStatusKind.RUNNING

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind.value}
        if self.message is not None:
            out["message"] = self.message
        return out

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SubAgentStatus:
        return SubAgentStatus(
            SubAgentStatusKind(data["kind"]), data.get("message")
        )


@dataclass(slots=True)
class SubAgentAssignment:
    objective: str
    role: str | None = None


@dataclass(slots=True)
class SubAgentResult:
    agent_id: str
    agent_type: SubAgentType
    assignment: SubAgentAssignment
    model: str
    nickname: str | None
    status: SubAgentStatus
    result: str | None
    steps_taken: int
    duration_ms: int
    from_prior_session: bool = False
    structured: Any | None = None


@dataclass(slots=True)
class SpawnRequest:
    prompt: str
    agent_type: SubAgentType
    assignment: SubAgentAssignment
    allowed_tools: list[str] | None = None
    model: str | None = None
    nickname: str | None = None
    parent_depth: int = 0
    # When set (nested spawn), mailbox emits child_spawned(parent, child).
    parent_agent_id: str | None = None
    fork_context: bool = False
    fork_messages: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | None = None
    auto_approve: bool | None = None
    # Persona system prompt for a plugin agent (overrides the built-in
    # ``agent_type`` prompt). ``None`` keeps the standard type prompt.
    system_prompt: str | None = None
    # Optional per-spawn workspace override.
    workspace: Path | None = None
    # When True, the parent turn does NOT block on this agent's completion
    # (handoff skips it). Completion still injects via
    # ``<deepseek:subagent.done>`` — during an active turn at the next handoff,
    # or via a hidden follow-up turn when the parent is already idle.
    background: bool = False
