"""Sub-agent core types: constants, agent types/prompts, status and request models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _epoch_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


DEFAULT_MAX_STEPS = 100
DEFAULT_MAX_AGENTS = 10
DEFAULT_MAX_SPAWN_DEPTH = 3
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

    def system_prompt(self) -> str:
        """Return the system prompt for this agent type."""
        from deepseek_tui.engine.prompts import load_prompt

        output_contract = load_prompt("subagent_output_format")
        base = _SUBAGENT_PROMPTS.get(self.value, "")
        return f"{base}\n\n{output_contract}" if base else output_contract


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
        "Plan before you act. Use `checklist_write` for any multi-step task so your work\n"
        "is visible in the parent's sidebar. For complex initiatives, layer\n"
        "`update_plan` (strategy) above `checklist_write` (tactics)."
    ),
    "explore": (
        "You are an exploration sub-agent. Your job is to map the relevant region\n"
        "of the codebase fast and report what is there. You are read-only by\n"
        "convention — do not write, patch, or run side-effectful commands. If the\n"
        "task seems to require a write, stop and put it under BLOCKERS.\n\n"
        "Method:\n"
        "- Start with `list_dir` and `file_search` to orient.\n"
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
        "- Use `update_plan` to record the strategy and `checklist_write` for the backlog.\n\n"
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
        "- Prefer `edit_file` for narrow changes, `apply_patch` for multi-hunk.\n"
        "- After edits, run a quick verification (lint/test).\n"
        "- If tests are needed, write them alongside the implementation.\n\n"
        "CHANGES is the load-bearing section — list every file modified with a one-line summary."
    ),
    "verifier": (
        "You are a verification sub-agent. Your job is to run the project's\n"
        "test suite and report pass/fail with evidence. You are read-only —\n"
        "do not patch failing tests or modify code.\n\n"
        "Method:\n"
        "- Run the right gate: `run_tests`, or `exec_shell` for custom commands.\n"
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


def build_subagent_system_prompt(
    agent_type: SubAgentType, assignment: SubAgentAssignment
) -> str:
    """Build the sub-agent system prompt."""
    base = agent_type.system_prompt()
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
    fork_context: bool = False
    fork_messages: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | None = None
    auto_approve: bool | None = None
