"""Optional automation metadata (delivery / digest) — backward compatible."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
1. Prefer web_search (Tavily) or MCP search tools (bing, fetch, china-stock, yahoo) over exec_shell/curl.
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
