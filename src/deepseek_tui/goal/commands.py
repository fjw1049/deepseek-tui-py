"""Shared `/goal` grammar for TUI and HTTP."""

from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.goal.types import MAX_GOAL_OBJECTIVE_LENGTH

CONTROL_SUBCOMMANDS = frozenset({"pause", "resume", "cancel", "reopen"})


@dataclass(frozen=True, slots=True)
class ParsedGoalCommand:
    kind: str
    objective: str = ""
    replace: bool = False
    index: int | None = None
    dest: int | None = None
    message: str = ""
    severity: str = "error"
    token_budget: int | None = None
    turn_budget: int | None = None
    wall_clock_budget_ms: int | None = None


def _positive_integer(raw: str) -> int | None:
    # Bound parsing work and accept only the ASCII decimal command grammar.
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 18:
        return None
    value = int(raw)
    return value if value > 0 else None


def parse_goal_command(raw_args: str) -> ParsedGoalCommand:
    args = raw_args.strip()
    if not args or args == "status":
        return ParsedGoalCommand(kind="status")

    tokens = args.split()
    first = tokens[0]
    if first == "budget":
        fields = {
            "tokens": "token_budget",
            "turns": "turn_budget",
            "seconds": "wall_clock_budget_ms",
        }
        values: dict[str, int] = {}
        if len(tokens) < 3 or len(tokens) % 2 != 1:
            return ParsedGoalCommand(
                kind="error", message="Use /goal budget tokens N turns N seconds N"
            )
        for unit, value in zip(tokens[1::2], tokens[2::2], strict=True):
            if unit not in fields or _positive_integer(value) is None:
                return ParsedGoalCommand(
                    kind="error", message="Budget limits must be positive integers"
                )
            values[fields[unit]] = int(value) * (1000 if unit == "seconds" else 1)
        return ParsedGoalCommand(kind="budget", **values)
    if first == "next":
        return _parse_next(tokens)
    if first in CONTROL_SUBCOMMANDS and len(tokens) == 1:
        return ParsedGoalCommand(kind=first)

    index = 0
    replace = False
    if tokens[index] == "replace":
        replace = True
        index += 1
    if index < len(tokens) and tokens[index] == "--":
        index += 1
    objective = " ".join(tokens[index:]).strip()
    if not objective:
        return ParsedGoalCommand(
            kind="error",
            message="Provide a goal objective, e.g. `/goal Ship feature X`.",
            severity="hint",
        )
    if len(objective) > MAX_GOAL_OBJECTIVE_LENGTH:
        return ParsedGoalCommand(
            kind="error",
            message=f"Goal objective is too long (max {MAX_GOAL_OBJECTIVE_LENGTH} characters).",
        )
    return ParsedGoalCommand(kind="create", objective=objective, replace=replace)


def _parse_next(tokens: list[str]) -> ParsedGoalCommand:
    if len(tokens) == 1:
        return ParsedGoalCommand(
            kind="error",
            message=(
                "Provide an upcoming goal, e.g. `/goal next Ship feature X`, "
                "or `/goal next manage`."
            ),
            severity="hint",
        )
    if tokens[1] == "manage":
        if len(tokens) == 2:
            return ParsedGoalCommand(kind="next-manage")
        rest = tokens[2:]
        if rest[0] == "delete" and len(rest) == 2 and _positive_integer(rest[1]) is not None:
            return ParsedGoalCommand(kind="next-delete", index=int(rest[1]))
        if rest[0] == "move" and len(rest) == 3 and _positive_integer(rest[1]) is not None and _positive_integer(rest[2]) is not None:
            return ParsedGoalCommand(kind="next-move", index=int(rest[1]), dest=int(rest[2]))
        return ParsedGoalCommand(
            kind="error",
            message=(
                "Use `/goal next manage`, `/goal next manage delete N`, "
                "or `/goal next manage move FROM TO`."
            ),
            severity="hint",
        )
    index = 1
    if tokens[index] == "--":
        index += 1
    objective = " ".join(tokens[index:]).strip()
    if not objective:
        return ParsedGoalCommand(
            kind="error",
            message="Provide an upcoming goal objective, e.g. `/goal next Ship feature X`.",
            severity="hint",
        )
    if len(objective) > MAX_GOAL_OBJECTIVE_LENGTH:
        return ParsedGoalCommand(
            kind="error",
            message=f"Goal objective is too long (max {MAX_GOAL_OBJECTIVE_LENGTH} characters).",
        )
    return ParsedGoalCommand(kind="next-add", objective=objective)
