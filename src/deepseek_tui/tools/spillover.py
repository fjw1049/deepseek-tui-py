"""Tool-output spillover writer (#422).

Mirrors ``docs/DeepSeek-TUI-main/crates/tui/src/tools/truncate.rs``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from pathlib import Path

from deepseek_tui.config.paths import user_tool_outputs_dir
from deepseek_tui.tools.base import ToolResult

logger = logging.getLogger(__name__)

SPILLOVER_DIR_NAME = "tool_outputs"
SPILLOVER_THRESHOLD_BYTES = 100 * 1024
SPILLOVER_HEAD_BYTES = 32 * 1024
SPILLOVER_MAX_AGE_SECS = 7 * 24 * 60 * 60

_TEST_SPILLOVER_ROOT: Path | None = None


def spillover_root() -> Path | None:
    """Resolve ``~/.deepseek/tool_outputs/`` (or test override)."""
    if _TEST_SPILLOVER_ROOT is not None:
        return _TEST_SPILLOVER_ROOT
    try:
        return user_tool_outputs_dir()
    except Exception:  # noqa: BLE001
        return None


def set_test_spillover_root(root: Path | None) -> Path | None:
    """Override spillover root for tests."""
    global _TEST_SPILLOVER_ROOT
    previous = _TEST_SPILLOVER_ROOT
    _TEST_SPILLOVER_ROOT = root
    return previous


def sanitise_id(tool_id: str) -> str | None:
    """Keep ASCII alphanumerics, ``-``, ``_``; reject empty."""
    cleaned = "".join(
        ch for ch in tool_id if ch.isascii() and (ch.isalnum() or ch in "-_")
    )
    return cleaned or None


def spillover_path(tool_id: str) -> Path | None:
    root = spillover_root()
    safe = sanitise_id(tool_id)
    if root is None or safe is None:
        return None
    return root / f"{safe}.txt"


def write_spillover(tool_id: str, content: str) -> Path:
    path = spillover_path(tool_id)
    if path is None:
        raise OSError("could not resolve spillover path")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path


def prune_older_than(max_age_secs: float = SPILLOVER_MAX_AGE_SECS) -> int:
    """Delete spillover files older than *max_age_secs*. Non-fatal."""
    root = spillover_root()
    if root is None or not root.is_dir():
        return 0
    cutoff = time.time() - max_age_secs
    pruned = 0
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                pruned += 1
        except OSError as err:
            logger.warning("spillover prune skipped %s: %s", entry, err)
    return pruned


def _utf8_head(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    cut = min(max_bytes, len(encoded))
    while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
        cut -= 1
    return encoded[:cut].decode("utf-8")


def maybe_spillover(
    tool_id: str,
    content: str,
    *,
    threshold: int = SPILLOVER_THRESHOLD_BYTES,
    head_bytes: int = SPILLOVER_HEAD_BYTES,
) -> tuple[str, Path] | None:
    if len(content.encode("utf-8")) <= threshold:
        return None
    path = write_spillover(tool_id, content)
    head = _utf8_head(content, head_bytes)
    return head, path


def apply_spillover(result: ToolResult, tool_id: str) -> ToolResult:
    """Spill large successful tool results to disk; shrink inline content.

    Mirrors Rust ``apply_spillover`` (truncate.rs:229). Failures are logged
    and the original result is returned unchanged.
    """
    if not result.success:
        return result
    content = result.content or ""
    if len(content.encode("utf-8")) <= SPILLOVER_THRESHOLD_BYTES:
        return result

    total = len(content.encode("utf-8"))
    try:
        pair = maybe_spillover(tool_id, content)
    except OSError as err:
        logger.warning("spillover write failed tool_id=%s: %s", tool_id, err)
        return result
    if pair is None:
        return result

    head, path = pair
    path_str = str(path)
    head_kib = len(head.encode("utf-8")) // 1024
    total_kib = total // 1024
    footer = (
        f"\n\n[Output truncated: {head_kib} KiB of {total_kib} KiB shown. "
        f"Full output saved to {path_str}. Use "
        f"`retrieve_tool_result ref={tool_id} mode=tail` or "
        f"`retrieve_tool_result ref={tool_id} mode=query query=<text>` "
        f"if you need the elided output.]"
    )
    metadata = dict(result.metadata)
    metadata["spillover_path"] = path_str
    return replace(result, content=head + footer, metadata=metadata)
