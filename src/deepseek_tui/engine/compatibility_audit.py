"""Read-only retirement evidence report; never removes an API or tool alias."""

import argparse
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

OBSERVATION_STARTED = date(2026, 11, 11)
ROUTES = {
    "agent_resume": "agent",
    "exec_shell_interact": "exec_shell",
    "task_read": "task_output",
    "task_cancel": "task_stop",
    "task_resume": "task_create",
    "task_shell_start": "exec_shell",
    "task_shell_wait": "task_output",
    "automation_create": "cron_create",
    "automation_list": "cron_list",
    "automation_read": "cron_list",
    "automation_update": "cron_update",
    "automation_pause": "cron_update",
    "automation_resume": "cron_update",
    "automation_delete": "cron_delete",
}
EVENT = re.compile(r"legacy_tool_used name=([\w]+) replacement=([\w]+) count=(\d+)")


def report(
    paths: list[Path],
    *,
    start: date | None = None,
    end: date | None = None,
    complete_coverage: bool = False,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    if start and end and (start > end or end > today):
        raise ValueError("Coverage dates must be ordered and cannot extend into the future")
    counts: Counter[tuple[str, str]] = Counter()
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if match := EVENT.search(line):
                    counts[(match[1], match[2])] += int(match[3])
    days = max(0, (end - max(start, OBSERVATION_STARTED)).days) if start and end else 0
    sufficient = bool(paths) and complete_coverage and days >= 30
    pairs = set(ROUTES.items()) | {
        ("agent", target) for target in ("task_list", "task_output", "task_stop")
    }
    return {
        "coverage_days": days,
        "complete_coverage_attested": complete_coverage,
        "automatic_removal": False,
        "routes": [
            {
                "name": old,
                "replacement": new,
                "calls": counts[(old, new)],
                "status": "used"
                if counts[(old, new)]
                else "eligible_for_manual_review"
                if sufficient
                else "insufficient_evidence",
            }
            for old, new in sorted(pairs)
        ],
        "note": (
            "Logs must cover the declared interval and all installations. "
            "Public APIs need a versioned migration; agent entries refer only to old actions."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="*", type=Path)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--complete-coverage", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            report(
                args.logs, start=args.start, end=args.end, complete_coverage=args.complete_coverage
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
