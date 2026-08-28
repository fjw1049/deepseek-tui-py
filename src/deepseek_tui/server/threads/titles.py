"""Stable default titles derived from a thread's first user query."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from deepseek_tui.server.threads.models import TurnItemKind

if TYPE_CHECKING:
    from deepseek_tui.server.threads.store import RuntimeThreadStore


PLACEHOLDER_THREAD_TITLES = frozenset({"New Thread", "新会话"})
MAX_THREAD_TITLE_LENGTH = 48


def should_derive_thread_title(
    title: str | None,
    *,
    thread_id: str,
) -> bool:
    raw = (title or "").strip()
    return (
        not raw
        or raw in PLACEHOLDER_THREAD_TITLES
        or raw == thread_id[:8]
    )


def derive_thread_title_from_query(query: str) -> str | None:
    """Match the Workbench's short, stable first-query title closely."""

    clean_query = query.strip()
    if not clean_query:
        return None

    if "[ds-preview-pick]" in clean_query and "用户要求：" in clean_query:
        clean_query = clean_query.rsplit("用户要求：", 1)[1].strip()

    focus = re.match(
        r"^(?:@plugin:([^\s]+)|/([^\s/@]+)|@([^\s]+))(?:\s+([\s\S]*))?$",
        clean_query,
        flags=re.IGNORECASE,
    )
    if focus:
        clean_query = (focus.group(4) or next(filter(None, focus.groups()[:3]))).strip()

    lines: list[str] = []
    for raw_line in clean_query.splitlines():
        if re.match(r"^\s*(```|~~~)", raw_line):
            continue
        line = re.sub(r"^#{1,6}\s+", "", raw_line)
        line = re.sub(r"^>\s+", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        line = line.replace("`", "")
        line = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)

    if not lines:
        return None
    first_line = lines[0]
    sentence_break = re.search(r"[。！？.!?]", first_line)
    if sentence_break is not None and sentence_break.start() >= 8:
        first_line = first_line[: sentence_break.start()]
    shortened = first_line[:MAX_THREAD_TITLE_LENGTH].strip()
    title = re.sub(r"[\s,.;:!?，。；：！？、'\"`()\[\]{}]+$", "", shortened).strip()
    return title or None


def first_query_title(store: RuntimeThreadStore, thread_id: str) -> str | None:
    """Return a title from the earliest durable, non-hidden user message."""

    for turn in store.list_turns_for_thread(thread_id):
        for item_id in turn.item_ids:
            try:
                item = store.load_item(item_id)
            except FileNotFoundError:
                continue
            if item.kind != TurnItemKind.USER_MESSAGE:
                continue
            title = derive_thread_title_from_query(item.detail or item.summary)
            if title:
                return title
    return None
