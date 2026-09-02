"""Upcoming-goal queue. Invisible to the model until promoted."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from deepseek_tui.goal.state import validate_objective
from deepseek_tui.goal.types import GoalError, GoalQueueItem


@dataclass(slots=True)
class GoalQueue:
    items: list[GoalQueueItem] = field(default_factory=list)

    def add(self, objective: str) -> GoalQueueItem:
        item = GoalQueueItem(item_id=str(uuid.uuid4()), objective=validate_objective(objective))
        self.items.append(item)
        return item

    def peek_next(self) -> GoalQueueItem | None:
        return self.items[0] if self.items else None

    def remove_item(self, item_id: str) -> GoalQueueItem | None:
        if not self.items or self.items[0].item_id != item_id:
            return None
        return self.items.pop(0)

    def remove(self, index: int) -> GoalQueueItem:
        if index < 1 or index > len(self.items):
            raise GoalError("queue_index", f"No upcoming goal at #{index}")
        return self.items.pop(index - 1)

    def move(self, src: int, dest: int) -> None:
        if src < 1 or src > len(self.items) or dest < 1 or dest > len(self.items):
            raise GoalError("queue_index", "Upcoming-goal index out of range")
        item = self.items.pop(src - 1)
        self.items.insert(dest - 1, item)

    def to_list(self) -> list[dict[str, str]]:
        return [item.to_dict() for item in self.items]


def item_from_dict(data: dict[str, object]) -> GoalQueueItem | None:
    objective = data.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        return None
    item_id = data.get("item_id")
    return GoalQueueItem(
        item_id=str(item_id) if item_id else str(uuid.uuid4()),
        objective=objective.strip(),
    )
