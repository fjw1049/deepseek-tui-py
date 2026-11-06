"""Facts about how a session ran, derived only from what the product persisted.

Live trials and archived soak runs go through the same code, so a baseline from
old data and a new run are read the same way. Command patterns here are labelled
heuristics: they count behaviour for trends and never decide whether a task passed.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.engine.completion import without_completion_note

STOCK_ANSWERS = (
    "操作后的最终核验未完成",
    "Final verification did not complete",
    "界面任务尚未完成。模型请求失败",
    "The UI task is incomplete because the model request failed",
    "任务因工具调用轮数达到上限而停止",
    "Task stopped at the tool round-trip limit",
)
GUARD_DENIAL = re.compile(r"^Shell cannot ")
# The answer says something was run; a negation ("未验证", "not tested") is honesty, not a claim.
CLAIMED_RUN = re.compile(
    r"(?<![未没不无])(?<!没有)(?<!尚未)(?:测试|验证|运行|跑)(?:全部|都)?(?:过了|通过|成功|跑通)"
    r"|(?<!not )(?<!n't )\b(?:tests? (?:all )?pass(?:ed|es)?|verified that|i (?:ran|tested))\b",
    re.IGNORECASE,
)
RUNNING_TOOLS = {"exec_shell", "browser_use", "browser_skill", "cua_js", "cua_observe"}
_BLOCKED_TARGET = re.compile(r"^Shell cannot \w+ (?:\w+ )*?(?:path|file)? ?'([^']+)'")
_BYPASS_MECHANISM = re.compile(
    r"\bos\.(?:remove|unlink|rename|replace)|\bshutil\.|\.unlink\(|\.rename\(|\.write_text\("
    r"|\bopen\([^)]*['\"][wa]|\bfind\b.*-delete|\bunlink\s|\bperl\b|\bruby\b|\bnode\s+-e|\btee\s"
)
_INSTALL = re.compile(
    r"\b(?:pip3?|uv pip|npm|pnpm|yarn|brew|apt(?:-get)?|gem|cargo)\s+(?:-\S+\s+)*(?:install|add)\b"
    r"|\bnpx\s+playwright\s+install\b|\bpython3?\s+-m\s+(?:venv|pip\s+install)\b"
)
_GIT_MUTATION = re.compile(r"\bgit\s+(?:commit|push|reset\s+--hard|rebase|merge)\b")


@dataclass(slots=True)
class Session:
    thread_id: str
    turns: list[dict[str, Any]]
    items: list[dict[str, Any]]
    interventions: list[dict[str, Any]] = field(default_factory=list)


def _json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _interventions(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("event") == "harness.intervention":
            rows.append({"turn_id": record.get("turn_id"), **record["payload"]})
    return rows


def load_sessions(root: Path) -> list[Session]:
    """Read every thread under a store root (``turns/``, ``items/``, ``events/``)."""
    turns: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((root / "turns").glob("*.json")):
        if (turn := _json(path)) is not None:
            turns.setdefault(turn["thread_id"], []).append(turn)
    items_by_turn: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((root / "items").glob("*.json")):
        if (item := _json(path)) is not None:
            items_by_turn.setdefault(item["turn_id"], []).append(item)
    sessions = []
    for thread_id, thread_turns in turns.items():
        thread_turns.sort(key=lambda turn: turn["created_at"])
        ordered: list[dict[str, Any]] = []
        for turn in thread_turns:
            rank = {item_id: i for i, item_id in enumerate(turn.get("item_ids") or [])}
            ordered.extend(
                sorted(
                    items_by_turn.get(turn["id"], []),
                    key=lambda item: rank.get(item["id"], len(rank)),
                )
            )
        sessions.append(
            Session(
                thread_id,
                thread_turns,
                ordered,
                _interventions(root / "events" / f"{thread_id}.jsonl"),
            )
        )
    return sessions


def turn_answers(session: Session) -> list[str]:
    """The final text of each turn, as the user received it."""
    answers = []
    for turn in session.turns:
        final = ""
        fallback = ""
        for item in session.items:
            if item["turn_id"] != turn["id"] or item["kind"] != "agent_message":
                continue
            meta = item.get("metadata") or {}
            intent = meta.get("process_intent") or {}
            if intent.get("source") in {"narration_service", "runtime"}:
                continue
            text = without_completion_note((item.get("detail") or item.get("summary") or "").strip(), meta)
            if text and meta.get("agent_segment") == "final_answer":
                final = text
            elif text and not meta.get("agent_segment"):
                fallback = text
        answers.append(final or fallback)
    return answers


def run_record(session: Session, *, commands: int = 20) -> str:
    """What was actually run, for a reviewer who otherwise sees only the outcome."""
    calls = [_tool(item) for item in session.items]
    counts = Counter(name for name, _ in calls if name)
    ran = [str(arguments.get("command", ""))[:160].replace("\n", " ")
           for name, arguments in calls if name == "exec_shell"]
    summary = "、".join(f"{name} {count} 次" for name, count in counts.most_common())
    recent = "\n".join(f"- {command}" for command in ran[-commands:])
    return f"工具调用：{summary or '无'}\n最近的命令：\n{recent}" if ran else f"工具调用：{summary or '无'}"


def claims_without_run(session: Session) -> int:
    """Turns whose answer says something was tested when nothing was run.

    The judge sees the answer and the artifacts, not the process, so only this
    record can tell a real test run from a claimed one.
    """
    unbacked = 0
    for turn, answer in zip(session.turns, turn_answers(session), strict=True):
        ran = any(
            item["turn_id"] == turn["id"] and _tool(item)[0] in RUNNING_TOOLS
            for item in session.items
        )
        unbacked += bool(not ran and CLAIMED_RUN.search(answer))
    return unbacked


def _tool(item: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    meta = item.get("metadata") or {}
    arguments = meta.get("tool_input")
    return meta.get("tool_name"), arguments if isinstance(arguments, dict) else {}


def _count_bypasses(calls: list[tuple[str, str, str, bool]]) -> int:
    """A guard stopped a path, and a later command reached it by another mechanism."""
    bypasses = 0
    blocked: set[str] = set()
    for name, command, detail, failed in calls:
        if name != "exec_shell":
            continue
        if failed and GUARD_DENIAL.match(detail):
            if match := _BLOCKED_TARGET.match(detail):
                blocked.add(Path(match.group(1)).name)
            continue
        if failed or not blocked or not _BYPASS_MECHANISM.search(command):
            continue
        hits = {target for target in blocked if target and target in command}
        if hits:
            bypasses += 1
            blocked -= hits
    return bypasses


def session_metrics(session: Session) -> dict[str, float]:
    tool_calls = Counter[str]()
    tool_failures = Counter[str]()
    calls: list[tuple[str, str, str, bool]] = []
    for item in session.items:
        name, arguments = _tool(item)
        if not name:
            continue
        failed = item.get("status") == "failed"
        tool_calls[name] += 1
        tool_failures[name] += failed
        calls.append(
            (name, str(arguments.get("command") or ""), item.get("detail") or "", failed)
        )
    shell = [command for name, command, _, _ in calls if name == "exec_shell"]
    details = [detail for _, _, detail, failed in calls if failed]
    answers = turn_answers(session)
    usage = [turn.get("usage") or {} for turn in session.turns]
    completed = sum(turn.get("status") == "completed" for turn in session.turns)
    kinds = Counter(row.get("kind") for row in session.interventions)
    metrics: dict[str, float] = {
        "turns": len(session.turns),
        "completed_turns": completed,
        "rounds": sum(u.get("turns") or 0 for u in usage),
        "input_tokens": sum(u.get("input_tokens") or 0 for u in usage),
        "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
        "cache_hit_tokens": sum(u.get("cache_hit_tokens") or 0 for u in usage),
        "tool_calls": sum(tool_calls.values()),
        # Review signal, not proof of disclosure or a task failure.
        "config_path_mentions_in_shell": sum("DEEPSEEK_CONFIG_PATH" in cmd for cmd in shell),
        "tool_failures": sum(tool_failures.values()),
        "finish_task_calls": tool_calls["finish_task"],
        "finish_task_failures": tool_failures["finish_task"],
        "update_goal_calls": tool_calls["UpdateGoal"],
        "update_goal_failures": tool_failures["UpdateGoal"],
        "browser_use_calls": tool_calls["browser_use"],
        "browser_use_failures": tool_failures["browser_use"],
        "request_task_tools_calls": tool_calls["request_task_tools"],
        "guard_blocks": sum(bool(GUARD_DENIAL.match(d)) for d in details),
        "guard_bypasses": _count_bypasses(calls),
        "tool_not_in_catalog": sum(
            "not available in the current tool catalog" in d for d in details
        ),
        "installs": sum(bool(_INSTALL.search(c)) for c in shell),
        "git_mutations": sum(bool(_GIT_MUTATION.search(c)) for c in shell),
        "foreground_sleeps": sum(bool(re.search(r"(?:^|[;&|]\s*)sleep\s+\d", c)) for c in shell),
        "gnu_timeout_calls": sum(bool(re.search(r"(?:^|[;&|]\s*)timeout\s+\d", c)) for c in shell),
        "agents_md_rereads": sum("AGENTS.md" in command for command in shell) + sum(
            "AGENTS.md" in str(_tool(item)[1].get("path") or "")
            for item in session.items
            if _tool(item)[0] == "read_file"
        ),
        "answers_lost": sum(
            turn.get("status") == "completed"
            and (not answer or any(stock in answer for stock in STOCK_ANSWERS))
            for turn, answer in zip(session.turns, answers, strict=True)
        ),
        "interventions": len(session.interventions),
    }
    for kind, count in sorted(kinds.items()):
        metrics[f"interventions.{kind}"] = count
    metrics["claims_without_run"] = claims_without_run(session)
    metrics["existing_files_gone"] = sum(
        row.get("reason") == "existing_file_gone" for row in session.interventions
    )
    # Rounds the harness spent, not the model: each of these holds a stop or
    # rejects a call and forces another request.
    metrics["harness_rounds"] = sum(
        row.get("outcome") in {"rejected", "blocked", "outside_focus", "not_in_catalog"}
        or row.get("reason") in {
            "task_delivery_continue_nudge", "task_delivery_finalization",
            "pending_state", "checklist_incomplete_gate", "stop_hook_block", "short_stop",
        }
        for row in session.interventions
    )
    metrics.update(cua_metrics(session))
    return metrics


def _seconds(stamp: str | None) -> float | None:
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def cua_metrics(session: Session) -> dict[str, float]:
    """Where computer-use time goes: the desktop runtime, waiting for the desktop, or the
    model between calls (which includes any vision helper). Empty without CUA calls."""
    metrics: Counter[str] = Counter()
    previous_end: tuple[str, float] | None = None
    for item in session.items:
        name, _ = _tool(item)
        if name not in {"cua_js", "cua_js_reset", "cua_observe"}:
            # Narration between calls is the model's time; another tool's run is not.
            previous_end = previous_end if name is None else None
            continue
        stats = (item.get("metadata") or {}).get("cua_stats") or {}
        start, end = _seconds(item.get("started_at")), _seconds(item.get("ended_at"))
        metrics["cua_calls"] += 1
        metrics["cua_failures"] += item.get("status") == "failed"
        if previous_end and previous_end[0] == item["turn_id"] and start is not None:
            metrics["cua_model_gap_ms"] += max(0.0, (start - previous_end[1]) * 1000)
        previous_end = (item["turn_id"], end) if end is not None else None
        if start is not None and end is not None:
            metrics["cua_tool_ms"] += max(0.0, (end - start) * 1000)
        metrics["cua_runtime_ms"] += stats.get("runtime_ms") or 0
        metrics["cua_runtime_ms"] += stats.get("observe_runtime_ms") or 0
        metrics["cua_lease_wait_ms"] += stats.get("lease_wait_ms") or 0
        metrics["cua_text_bytes"] += stats.get("text_bytes") or 0
        metrics["cua_images"] += stats.get("images") or 0
        metrics["cua_not_sent"] += stats.get("delivery") == "not_sent"
        metrics["cua_uncertain"] += stats.get("delivery") == "uncertain"
        metrics["cua_observed_after_failure"] += bool(stats.get("observed_after_failure"))
        metrics["cua_replaced_by_observation"] += bool(stats.get("replaced_by_observation"))
        metrics["cua_waits"] += "waited_ms" in stats
        metrics["cua_waits_met"] += bool(stats.get("expect_met"))
        metrics["cua_wait_ms"] += stats.get("waited_ms") or 0
        if stats.get("error"):
            metrics[f"cua_error.{stats['error']}"] += 1
    return {name: float(value) for name, value in metrics.items()}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)] if ordered else 0.0


def aggregate(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Totals and tail figures across sessions, for reports and comparison."""
    names = sorted({name for row in rows for name in row})
    output: dict[str, dict[str, float]] = {}
    for name in names:
        values = [row.get(name, 0.0) for row in rows]
        output[name] = {
            "sessions": sum(value > 0 for value in values),
            "total": sum(values),
            "p50": percentile(values, 0.5),
            "p90": percentile(values, 0.9),
            "max": max(values),
        }
    return output


def cua_summary(root: Path) -> str:
    """Per-call averages over every session in a store that used computer use."""
    total: Counter[str] = Counter()
    for session in load_sessions(root):
        total.update(cua_metrics(session))
    calls = total["cua_calls"]
    if not calls:
        return "No computer-use calls found."
    lines = [
        f"CUA calls: {calls:.0f} (failed {total['cua_failures']:.0f})",
        f"Per call: tool {total['cua_tool_ms'] / calls:.0f} ms "
        f"(runtime {total['cua_runtime_ms'] / calls:.0f} ms), "
        f"desktop wait {total['cua_lease_wait_ms'] / calls:.0f} ms, "
        f"model between calls {total['cua_model_gap_ms'] / calls:.0f} ms, "
        f"{total['cua_text_bytes'] / calls / 1024:.1f} KB text, "
        f"{total['cua_images'] / calls:.2f} images",
        f"Failures: nothing sent {total['cua_not_sent']:.0f}, may have acted "
        f"{total['cua_uncertain']:.0f} "
        f"(observed at once {total['cua_observed_after_failure']:.0f}), "
        f"code replaced by an observation {total['cua_replaced_by_observation']:.0f}",
        f"Waits: {total['cua_waits']:.0f} (expected text met {total['cua_waits_met']:.0f}, "
        f"{total['cua_wait_ms'] / 1000:.1f} s in total)",
    ]
    errors = sorted((k.split(".", 1)[1], v) for k, v in total.items() if k.startswith("cua_error."))
    if errors:
        lines.append("Errors: " + ", ".join(f"{kind} {count:.0f}" for kind, count in errors))
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    root = sys.argv[1] if len(sys.argv) > 1 else "~/.deepseek/threads"
    print(cua_summary(Path(root).expanduser()))
