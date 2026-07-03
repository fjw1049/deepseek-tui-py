"""Automation delivery formatting and types.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from dataclasses import dataclass
from typing import Any

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message

_DELIVERY_MAX_CHARS = 3500

# Internal recovery errors — not user-actionable; do not push to Feishu/email.
_SKIP_DELIVERY_MARKERS = (
    "stale after restart",
    "task interrupted (stale",
)

# Process narration — not for end users.
_PROCESS_LINE = re.compile(
    r"^\s*(?:"
    r"我来|让我|现在我来|好的[，,]|首先|接下来|然后|"
    r"I(?:'ll|\s+will|\s+am going to)\s|Let me\s|Now let me\s|"
    r"I need to (?:find|check|get|ask)|"
    r"(?:报告|消息|摘要)(?:已生成|已通过|已经).*(?:发送|推送|投递)|"
    r"(?:Feishu|飞书|Lark).*(?:sent|发送|推送).*(?:success|成功)|"
    r"Do NOT|Please (?:provide|tell me)|"
    r"如果你(?:希望|想)|请问你(?:希望|想)|"
    r"以下(?:是)?本次摘要"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_CRON_PREFIX = re.compile(r"^\[cron:[^\]]+\]\s*", re.MULTILINE)
_PLAYBOOK_HEADER = re.compile(
    r"\[Cron execution playbook\][\s\S]*?(?=\n\n|\Z)",
    re.IGNORECASE,
)
_TOOL_ERROR = re.compile(r"\[tool error\][^\n]*", re.IGNORECASE)
_DIGEST_BLOCK = re.compile(
    r"<automation_digest>[\s\S]*?</automation_digest>\s*",
    re.IGNORECASE,
)


def assistant_message_text(message: Message | None) -> str:
    """Extract visible assistant text (exclude thinking / tool blocks)."""
    if message is None:
        return ""
    from deepseek_tui.protocol.messages import TextBlock

    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock) and block.text.strip():
            parts.append(block.text)
    return "\n".join(parts).strip()


def should_skip_delivery_for_error(error: str | None) -> bool:
    """True when failure is internal (restart recovery) — no channel notify."""
    if not error or not error.strip():
        return False
    lower = error.strip().lower()
    return any(marker in lower for marker in _SKIP_DELIVERY_MARKERS)


def classify_task_error_for_user(error: str) -> str:
    """Map internal task errors to canned user-facing copy (no raw leaks)."""
    lower = error.strip().lower()
    if not lower:
        return "自动化任务未能完成。请稍后重试，或在 Workbench 查看任务详情。"

    if "stale after restart" in lower or "task interrupted (stale" in lower:
        return "服务重启中断了正在运行的后台任务。下次调度时会自动重试。"

    if (
        "tool round-trip limit" in lower
        or "max tool" in lower
        or "maximum tool iterations" in lower
        or "too many tool" in lower
    ):
        return (
            "任务步骤过多已自动停止。请简化自动化描述，或检查工具是否陷入重复调用。"
        )

    if "web_search failed" in lower or (
        "web_search" in lower and "not configured" in lower
    ):
        return (
            "网络搜索失败。请检查 ANYSEARCH_API_KEY / TAVILY_API_KEY "
            "或 config.toml 中的 anysearch_api_key / tavily_api_key 后重启服务。"
        )

    if "canceled" in lower or "cancelled" in lower:
        return "任务已取消。"

    if "timeout" in lower or "timed out" in lower:
        return "任务执行超时。请缩小任务范围或稍后重试。"

    if "delivery failed" in lower:
        return "任务已完成，但消息投递失败。请检查飞书/邮件配置。"

    if "failed to enqueue" in lower:
        return "任务未能启动。请稍后重试。"

    return "自动化任务未能完成。请稍后重试，或在 Workbench 查看任务详情。"


def _strip_internal_markup(text: str) -> str:
    out = text.strip()
    out = _DIGEST_BLOCK.sub("", out)
    out = _PLAYBOOK_HEADER.sub("", out)
    out = _CRON_PREFIX.sub("", out)
    out = _TOOL_ERROR.sub("", out)
    return out.strip()


def _drop_process_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if _PROCESS_LINE.match(line):
            continue
        if line.strip().lower().startswith("[cron execution playbook]"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _pick_report_section(text: str) -> str:
    """Prefer the last markdown-heavy block when preamble looks like narration."""
    if not text:
        return text
    sections = re.split(r"\n-{3,}\n", text)
    if len(sections) <= 1:
        return text
    for candidate in reversed(sections):
        stripped = candidate.strip()
        if not stripped:
            continue
        if re.search(r"(?:^|\n)(?:#+\s|\*\*|📱|TOP\s*\d|热搜|简报)", stripped, re.I):
            return stripped
    return sections[-1].strip() or text.strip()


def sanitize_delivery_text(raw: str) -> str:
    """Light cleanup of agent final reply before channel send."""
    text = _strip_internal_markup(raw)
    text = _drop_process_lines(text)
    text = _pick_report_section(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > _DELIVERY_MAX_CHARS:
        text = text[: _DELIVERY_MAX_CHARS - 3].rstrip() + "..."
    return text


def format_delivery_success(raw: str, automation_name: str) -> str:
    body = sanitize_delivery_text(raw)
    if not body:
        return f"✅ {automation_name}\n\n本次任务已完成，但未生成可投递的正文。"
    return body


def format_delivery_failure(
    *,
    automation_name: str,
    error: str,
    partial_raw: str | None = None,
) -> str:
    user_msg = classify_task_error_for_user(error)
    lines = [f"❌ {automation_name}", "", user_msg]
    partial = sanitize_delivery_text(partial_raw or "")
    if partial and partial not in user_msg:
        lines.extend(["", "—", "", partial[:1200]])
    return "\n".join(lines)


def format_delivery_body(
    *,
    succeeded: bool,
    raw_summary: str | None,
    automation_name: str,
    error: str | None = None,
) -> str:
    """Single entry point for pipeline sinks."""
    if succeeded:
        return format_delivery_success(raw_summary or "", automation_name)
    return format_delivery_failure(
        automation_name=automation_name,
        error=error or "unknown error",
        partial_raw=raw_summary,
    )


# ======================================================================
# From types.py
# ======================================================================

"""Optional automation metadata (delivery / digest) — backward compatible."""




@dataclass(frozen=True, slots=True)
class DeliveryConfig:
    """Mirrors OpenHuman ``DeliveryConfig`` subset used after cron agent runs."""

    mode: str = "silent"
    chat_id: str | None = None
    channel: str | None = None
    to: str | None = None
    best_effort: bool = True
    thread_id: str | None = None

    def is_active(self) -> bool:
        return self.mode.strip().lower() not in ("", "silent", "none")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> DeliveryConfig:
        if not raw:
            return cls()
        mode = str(raw.get("mode", "silent")).strip().lower() or "silent"
        return cls(
            mode=mode,
            chat_id=_opt_str(raw.get("chat_id")),
            channel=_opt_str(raw.get("channel")),
            to=_opt_str(raw.get("to")),
            best_effort=bool(raw.get("best_effort", True)),
            thread_id=_opt_str(raw.get("thread_id")),
        )


@dataclass(frozen=True, slots=True)
class DigestConfig:
    """Prefetch sources injected before the agent prompt (email / feishu / …)."""

    sources: tuple[str, ...] = ()
    account: str | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> DigestConfig | None:
        if not raw:
            return None
        sources_raw = raw.get("sources")
        if not isinstance(sources_raw, list) or not sources_raw:
            return None
        sources = tuple(str(s).strip() for s in sources_raw if str(s).strip())
        if not sources:
            return None
        return cls(sources=sources, account=_opt_str(raw.get("account")))


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def cron_prompt_prefix(automation_id: str, name: str) -> str:
    """Align with OpenHuman ``[cron:{id} {name}]`` prefix."""
    return f"[cron:{automation_id} {name}] "


CRON_EXECUTION_PLAYBOOK = """\
[Cron execution playbook]
You are running a scheduled background task. Follow these rules:

Tool usage:
1. Prefer web_search (AnySearch + Tavily) or MCP search tools (bing, fetch, china-stock, yahoo) over exec_shell/curl.
2. Do NOT call tool_search_tool_regex or tool_search_tool_bm25 — use the tools already available.
3. Do NOT call request_user_input — complete the task with available tools.
4. Do NOT run pip install or long shell setup; use MCP or web_search instead.
5. Limit exec_shell to at most 2 attempts; if data is unavailable, stop and write a short summary.
6. Do NOT send messages to Feishu/email/webhook yourself — the system delivers your final reply automatically.

Output contract (this final reply IS the message users receive):
7. Write ONLY the finished report in your last message — no process narration ("我来…", "让我…", "Let me…").
8. Do NOT mention delivery, webhooks, chat_id, or "消息已发送".
9. Use clear structure: title → key data (bullets/table) → one-line takeaway if useful.
10. Keep it scannable (roughly 200–600 words unless the task needs a list).
11. Match the task language (Chinese prompt → Chinese report).
12. If data is unavailable, state what is missing and one actionable fix — do not dump tool errors or retry logs.
"""


def cron_execution_prefix(automation_id: str, name: str) -> str:
    return cron_prompt_prefix(automation_id, name) + CRON_EXECUTION_PLAYBOOK + "\n\n"
