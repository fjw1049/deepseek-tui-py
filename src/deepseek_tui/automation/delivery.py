"""Automation delivery formatting and types.
"""

from __future__ import annotations

import re
import hashlib
from typing import TYPE_CHECKING
from dataclasses import dataclass
from typing import Any
from deepseek_tui.utils import optional_text as _opt_str


class DeliveryNotSent(RuntimeError):
    """The channel rejected the request or failed before sending any message."""


def delivery_target_fingerprint(config: DeliveryConfig) -> str:
    """Identify a webhook destination without copying its credential into a run."""
    from deepseek_tui.automation.inbox import _parse_wecom_webhook_key

    target = config.to or config.chat_id or ""
    target = _parse_wecom_webhook_key(target) or target
    return hashlib.sha256(target.encode()).hexdigest()


def public_delivery_config(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    result = dict(raw)
    if str(raw.get("mode", "")).strip().lower() in {"wecom", "wecom_webhook", "wework"}:
        result["to"] = None
        result["chat_id"] = None
    return result


def sanitized_delivery_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    result = dict(snapshot)
    raw_config = result.get("config")
    if isinstance(raw_config, dict) and str(raw_config.get("mode", "")).strip().lower() in {"wecom", "wecom_webhook", "wework"}:
        target = raw_config.get("to") or raw_config.get("chat_id")
        if target:
            config = DeliveryConfig(mode="wecom", to=str(target))
            result["target_fingerprint"] = delivery_target_fingerprint(config)
        result["config"] = public_delivery_config(raw_config)
    return result

if TYPE_CHECKING:
    from deepseek_tui.protocol.messages import Message

_DELIVERY_MAX_CHARS = 3500

# Internal recovery errors — not user-actionable; do not push to Feishu/email.
_SKIP_DELIVERY_MARKERS = (
    "stale after restart",
    "task interrupted (stale",
)

_CRON_PREFIX = re.compile(r"^\[cron:[^\]]+\]\s*", re.MULTILINE)
# Rules echoed back by the model: the legacy header, or a whole unattended block.
_PLAYBOOK_HEADER = re.compile(
    r"\[Cron execution playbook\][\s\S]*?(?=\n\n|\Z)"
    r"|\[Unattended run\][\s\S]*?\[/Unattended run\]\s*",
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


def classify_task_error_for_user(error: str, locale: str | None = None) -> str:
    """Map internal task errors to canned user-facing copy (no raw leaks)."""
    from deepseek_tui.utils.user_text import user_text

    lower = error.strip().lower()
    if not lower:
        key = "error_generic"
    elif "stale after restart" in lower or "task interrupted (stale" in lower:
        key = "error_restart"
    elif "original conversation no longer exists" in lower:
        key = "error_thread_gone"
    elif (
        "tool round-trip limit" in lower
        or "max tool" in lower
        or "maximum tool iterations" in lower
        or "too many tool" in lower
    ):
        key = "error_too_many_steps"
    elif "web_search failed" in lower or (
        "web_search" in lower and "not configured" in lower
    ):
        key = "error_web_search"
    elif any(
        marker in lower
        for marker in (
            "http 401", "http 403", "authentication_error", "authentication fails",
            "api key invalid", "invalid api key", "missing_api_key", "unauthorized",
        )
    ):
        key = "error_auth"
    elif "canceled" in lower or "cancelled" in lower:
        key = "error_canceled"
    elif "timeout" in lower or "timed out" in lower:
        key = "error_timeout"
    elif "delivery failed" in lower:
        key = "error_delivery"
    elif "failed to enqueue" in lower:
        key = "error_enqueue"
    else:
        key = "error_generic"
    return user_text(key, locale)


def _strip_internal_markup(text: str) -> str:
    out = text.strip()
    out = _DIGEST_BLOCK.sub("", out)
    out = _PLAYBOOK_HEADER.sub("", out)
    out = _CRON_PREFIX.sub("", out)
    out = _TOOL_ERROR.sub("", out)
    return out.strip()


def sanitize_delivery_text(raw: str) -> str:
    """Light cleanup of agent final reply before channel send."""
    text = _strip_internal_markup(raw)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > _DELIVERY_MAX_CHARS:
        text = text[: _DELIVERY_MAX_CHARS - 3].rstrip() + "..."
    return text


def format_delivery_success(raw: str, automation_name: str) -> str:
    body = sanitize_delivery_text(raw)
    if not body:
        from deepseek_tui.utils.user_text import user_text

        return f"✅ {automation_name}\n\n{user_text('delivery_empty_body')}"
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


"""Optional automation metadata (delivery / digest) — backward compatible."""




@dataclass(frozen=True, slots=True)
class DeliveryConfig:
    """``DeliveryConfig`` subset used after cron agent runs."""

    mode: str = "silent"
    chat_id: str | None = None
    channel: str | None = None
    to: str | None = None
    best_effort: bool = True
    thread_id: str | None = None
    credential_ref: str | None = None

    def is_active(self) -> bool:
        return self.mode.strip().lower() not in ("", "silent", "none")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> DeliveryConfig:
        if not raw:
            return cls()
        mode = str(raw.get("mode", "silent")).strip().lower() or "silent"
        aliases = {"none": "silent", "mail": "email", "smtp": "email", "announce": "feishu",
                   "wecom_webhook": "wecom", "wework": "wecom", "proactive": "notify"}
        mode = aliases.get(mode, mode)
        if mode not in {"silent", "email", "feishu", "wecom", "notify"}:
            raise ValueError(f"Unknown delivery mode: {mode}")
        if not isinstance(raw.get("best_effort", True), bool):
            raise ValueError("delivery.best_effort must be a boolean")
        target = _opt_str(raw.get("to"))
        reference = _opt_str(raw.get("credential_ref"))
        if mode == "wecom" and reference and not (target or _opt_str(raw.get("chat_id"))):
            from deepseek_tui.state.secrets import load_delivery_secret

            target = load_delivery_secret(reference)
            if not target:
                raise ValueError("Delivery credential unavailable; restore the local credential store")
        return cls(
            mode=mode,
            chat_id=_opt_str(raw.get("chat_id")),
            channel=_opt_str(raw.get("channel")),
            to=target,
            credential_ref=reference,
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


def cron_prompt_prefix(automation_id: str, name: str) -> str:
    """Align with OpenHuman ``[cron:{id} {name}]`` prefix."""
    # A "]" in the name would end the marker early, so _CRON_PREFIX could
    # no longer strip it from delivered text.
    safe = " ".join(name.replace("]", ")").split())
    return f"[cron:{automation_id} {safe}] "


# Tasks queued before the unattended block existed carry this text verbatim;
# it is kept only so their prompts can still be cleaned for display.
_LEGACY_CRON_PLAYBOOK = """\
[Cron execution playbook]
You are running a scheduled background task. Follow these rules:

Tool usage:
1. Available tools: web_search, fetch_url, read_file, grep_files, file_search, exec_shell, load_skill, and any installed MCP tools (mcp_* / list_mcp_resources / read_mcp_resource) already in your tool list.
2. Prefer installed MCP tools for structured data sources when they match the task; use web_search/fetch_url as fallback. If web_search fails on an AnySearch/Tavily key and a Bing Search MCP tool is in this turn's list (mcp_*bing*), use it. If it is not listed, do not mention MCP or wait for a key.
3. Use load_skill when a listed skill matches the report format or process.
4. exec_shell is allowed — prefer short, non-interactive commands; avoid interactive prompts and package installs unless the task requires them.
5. Do NOT call request_user_input — nobody is watching this run.
6. If data is unavailable after a couple of tool attempts, stop and write a short summary of what is missing.
7. Do NOT send messages to Feishu/email/webhook yourself — the system delivers your final reply automatically.

Output contract (this final reply IS the message users receive):
8. Write ONLY the finished report in your last message — no process narration ("我来…", "让我…", "Let me…").
9. Do NOT mention delivery, webhooks, chat_id, or "消息已发送".
10. Use clear structure: title → key data (bullets/table) → one-line takeaway if useful.
11. Keep it scannable (roughly 200–600 words unless the task needs a list).
12. Match the task language (Chinese prompt → Chinese report).
13. If data is unavailable, state what is missing and one actionable fix — do not dump tool errors or retry logs.
"""

_UNATTENDED_OPEN = "[Unattended run]"
_UNATTENDED_CLOSE = "[/Unattended run]"

# Rules for any run nobody is watching. The tool list is deliberately not
# repeated here: the model sees the real one.
_UNATTENDED_RULES = """\
This run was started by a schedule or trigger; nobody is watching it.
- Do not ask questions. Where something is ambiguous, take the most reasonable reading and say which one in your result.
- Prefer installed MCP tools (mcp_*) for structured data sources that match the task; otherwise use web_search / fetch_url. If web_search fails for lack of a search key and an MCP search tool is in your tool list, use that.
- Use load_skill when a listed skill matches the work.
- Keep shell commands non-interactive; install packages only when the task needs them.
- If something stays unavailable after a couple of attempts, stop retrying and report what is missing.

Your final message is this run's result: it is what the user reads instead of watching the run. Give the outcome, not the process: no narration of steps ("I'll…", "Let me…", "我来…") and no raw tool errors or retry logs. If part could not be done, say what is missing and one concrete fix. Write in the language of the task."""

_DELIVERY_RULES = """\
The system sends that final message to the user automatically. Do not send it yourself through any channel, and do not mention delivery, webhooks or chat ids. Keep it scannable: a title, the key facts, then a one-line takeaway if useful."""


def unattended_preamble(*, delivery_active: bool) -> str:
    """Rules prepended to a cron or trigger run's prompt."""
    body = _UNATTENDED_RULES
    if delivery_active:
        body += "\n" + _DELIVERY_RULES
    return f"{_UNATTENDED_OPEN}\n{body}\n{_UNATTENDED_CLOSE}\n\n"


_UNATTENDED_BLOCK = re.compile(
    re.escape(_UNATTENDED_OPEN) + r"[\s\S]*?" + re.escape(_UNATTENDED_CLOSE) + r"\s*"
)


def strip_unattended_preamble(text: str) -> str:
    """The task's own instruction, without the rules the harness added."""
    return _UNATTENDED_BLOCK.sub("", text.replace(_LEGACY_CRON_PLAYBOOK, "", 1), count=1)


def cron_execution_prefix(
    automation_id: str, name: str, *, delivery_active: bool = False
) -> str:
    return cron_prompt_prefix(automation_id, name) + unattended_preamble(
        delivery_active=delivery_active
    )
