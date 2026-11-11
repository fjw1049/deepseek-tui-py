"""User-facing copy written by the harness itself, in the session language.

Model output follows the language directive in its prompt; these are the few
strings the harness writes on its own (delivery notices, status lines).
"""

from __future__ import annotations

_TEXT: dict[str, dict[str, str]] = {
    "zh": {
        "error_generic": "自动化任务未能完成。请稍后重试，或在 Workbench 查看任务详情。",
        "error_restart": "服务重启中断了正在运行的后台任务。下次调度时会自动重试。",
        "error_thread_gone": "创建该自动化的对话已被删除，无法确定要使用的模型。请重新创建该自动化。",
        "error_too_many_steps": "任务步骤过多已自动停止。请简化自动化描述，或检查工具是否陷入重复调用。",
        "error_web_search": (
            "网络搜索失败。可改用默认的 Bing Search 连接器（无需 Tavily/AnySearch key）。"
            "若仍要走 web_search，请检查 ANYSEARCH_API_KEY / TAVILY_API_KEY "
            "或 config.toml 中的 anysearch_api_key / tavily_api_key 后重启服务。"
        ),
        "error_auth": "模型服务认证失败。请检查该自动化所用服务商的 API 密钥和访问权限，再重新运行。",
        "error_canceled": "任务已取消。",
        "error_timeout": "任务执行超时。请缩小任务范围或稍后重试。",
        "error_delivery": "任务已完成，但消息投递失败。请检查飞书/邮件配置。",
        "error_enqueue": "任务未能启动。请稍后重试。",
        "delivery_empty_body": "本次任务已完成，但未生成可投递的正文。",
        "email_subject": "{name} · 自动化摘要",
        "turn_still_running": "仍在处理中，可能在等待桌面端的确认。完成后的结果请在 Workbench 中查看。",
        "run_resumed": "继续执行",
        "round_truncated": "本轮输出超出长度上限，已丢弃并重新生成",
    },
    "en": {
        "error_generic": "The automation did not finish. Try again later, or open the task in Workbench for details.",
        "error_restart": "A restart interrupted this background task. It will retry at the next scheduled run.",
        "error_thread_gone": "The chat that created this automation was deleted, so its model is unknown. Please recreate the automation.",
        "error_too_many_steps": "The task stopped after too many steps. Simplify the automation, or check whether a tool is being called in a loop.",
        "error_web_search": (
            "Web search failed. The default Bing Search connector needs no Tavily/AnySearch key. "
            "To keep using web_search, check ANYSEARCH_API_KEY / TAVILY_API_KEY "
            "or anysearch_api_key / tavily_api_key in config.toml, then restart."
        ),
        "error_auth": "The model provider rejected the credentials. Check the API key and access for this automation's provider, then run it again.",
        "error_canceled": "The task was cancelled.",
        "error_timeout": "The task timed out. Narrow its scope or try again later.",
        "error_delivery": "The task finished, but sending the message failed. Check the Feishu / email settings.",
        "error_enqueue": "The task could not start. Try again later.",
        "delivery_empty_body": "The task finished but produced no text to send.",
        "email_subject": "{name} · automation summary",
        "turn_still_running": "Still working, possibly waiting for a confirmation on the desktop. See Workbench for the result.",
        "run_resumed": "Resumed",
        "round_truncated": "This round hit the output limit; it was discarded and is being regenerated",
    },
}


def ui_locale() -> str:
    """``ui.locale`` from config; ``zh`` when it cannot be read."""
    try:
        from deepseek_tui.config.loader import ConfigLoader

        locale = ConfigLoader().load().ui.locale
    except Exception:  # noqa: BLE001 — copy must never break the caller
        return "zh"
    return locale if locale in _TEXT else "zh"


def user_text(key: str, locale: str | None = None, **values: str) -> str:
    table = _TEXT.get(locale or ui_locale(), _TEXT["zh"])
    return table[key].format(**values) if values else table[key]
