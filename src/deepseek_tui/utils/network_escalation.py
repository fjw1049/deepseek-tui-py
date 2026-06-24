"""网络超时升级：在 ToolContext 上按 host 追踪超时次数。

目标：当同一个 host 在一轮对话内反复超时，直接给出"换镜像 / 换工具"
的提示，而不是让模型原地重试（reverse-skill 那条 trace 曾对着
``raw.githubusercontent.com`` 连锤 4-5 轮才想到换源）。

状态存在 ``context.metadata["network_host_timeouts"]`` 里，结构是
``{host: 次数}``。ToolContext 是 per-engine 的、一轮对话内的多个 round
共享，所以这个计数器正好覆盖我们见过的"多轮重试风暴"。它不跨 turn
持久化——新的一轮从零开始，这是对的：上一轮的一次瞬时网络抖动不该
永久把某个 host 拉黑。

本模块刻意保持很小：只有几个小助手函数。``exec_shell``（curl 超时）
和 ``fetch_url``（httpx 超时）都会先调用 ``record_host_timeout`` 记一
笔，再用 ``should_escalate`` 判断是否要在报错信息里附上升级提示。
host 维度的具体镜像知识（例如 raw GitHub 走 jsDelivr）不放在这里，
那属于 skill / prompt 层；这里只给 host 无关的通用升级提示。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    # 规避运行期循环导入：registry -> shell -> utils.network_escalation -> registry。
    # 这里只用 ToolContext 做类型标注；运行期传入的是一个鸭子类型对象，
    # 我们只读写它的 .metadata。
    from deepseek_tui.tools.registry import ToolContext

# 挂在 context.metadata 上的计数器键，值是 {host: int}。
_HOST_TIMEOUTS_KEY = "network_host_timeouts"

# 单个 host 在一轮内超时达到这个次数，就从"轻量单次提示"升级为
# "明确建议换镜像 / 换工具"的提示。
_ESCALATION_THRESHOLD = 2


def _store(context: ToolContext) -> dict[str, int]:
    """取到（必要时新建）挂在 ``context.metadata`` 上的 ``{host: 次数}`` 字典。

    防御性处理：如果已存的值不是 dict（None、或被外部写成了别的类型），
    就当它没初始化过，用一个空 dict 覆盖回去——避免后续 ``store.get``
    在非 dict 上炸掉。
    """
    store = context.metadata.get(_HOST_TIMEOUTS_KEY)
    if not isinstance(store, dict):
        store = {}
        context.metadata[_HOST_TIMEOUTS_KEY] = store
    return store


def record_host_timeout(context: ToolContext, url: str) -> str | None:
    """把 ``url`` 所在 host 的超时计数 +1。

    返回该 host 字符串，方便调用方直接拿去拼提示而不用再解析一次
    URL。如果 ``url`` 解析不出可用 host（不是 http(s) URL），则什么都不
    记，返回 None。
    """
    host = _host_of(url)
    if host is None:
        return None
    store = _store(context)
    store[host] = store.get(host, 0) + 1
    return host


def host_timeout_count(context: ToolContext, url: str) -> int:
    """``url`` 所在 host 在本轮内已经超时了多少次。

    没有 host、或还没有任何计数记录时返回 0。注意：生产调用方实际
    用的是上层的 :func:`should_escalate`，本函数主要供测试直接断言。
    """
    host = _host_of(url)
    if host is None:
        return 0
    store = context.metadata.get(_HOST_TIMEOUTS_KEY)
    if not isinstance(store, dict):
        return 0
    return int(store.get(host, 0))


def should_escalate(context: ToolContext, url: str) -> bool:
    """该 host 是否已跨过升级阈值（默认 2 次）。

    一旦为真，调用方就应在报错里附上"换镜像 / 换工具"的提示，而不
    是只给一个轻量的"优先用 fetch_url"提示。
    """
    return host_timeout_count(context, url) >= _ESCALATION_THRESHOLD


def reset_host_timeouts(context: ToolContext) -> None:
    """清空所有 host 的超时计数。

    在每轮对话开始时调用，保证上一轮的瞬时网络抖动不会把某个 host
    永久拉进升级状态。对应模块想要维持的不变式——计数是 turn 级别而
    非 session 级别的："新的一轮从零开始"。
    """
    context.metadata.pop(_HOST_TIMEOUTS_KEY, None)


def _host_of(url: str) -> str | None:
    """从 ``url`` 取出小写、去掉 ``www.`` 前缀的 host。

    空 URL 或解析不出 netloc 时返回 None。
    """
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    return host or None
