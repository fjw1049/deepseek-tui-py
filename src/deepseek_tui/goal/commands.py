"""Shared `/goal` grammar for TUI and HTTP."""

from __future__ import annotations

from dataclasses import dataclass

from deepseek_tui.goal.types import MAX_GOAL_OBJECTIVE_LENGTH

CONTROL_SUBCOMMANDS = frozenset({"pause", "resume", "cancel"})


@dataclass(frozen=True, slots=True)
class ParsedGoalCommand:
    kind: str
    objective: str = ""
    replace: bool = False
    index: int | None = None
    dest: int | None = None
    message: str = ""
    severity: str = "error"


def parse_goal_command(raw_args: str) -> ParsedGoalCommand:
    args = raw_args.strip()
    if not args or args == "status":
        return ParsedGoalCommand(kind="status")

    tokens = args.split()
    first = tokens[0]
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
        if rest[0] == "delete" and len(rest) == 2 and rest[1].isdigit():
            return ParsedGoalCommand(kind="next-delete", index=int(rest[1]))
        if rest[0] == "move" and len(rest) == 3 and rest[1].isdigit() and rest[2].isdigit():
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
