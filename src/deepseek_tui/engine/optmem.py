"""OptMem helpers — wake the durable agent memory without mutating system.

``memo wake`` output is injected as a user-role ``<system-reminder>`` so the
static system prompt (and DeepSeek KV prefix cache) stays stable.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_MEMO = Path.home() / ".optmem" / "memo"
_PART_RE = re.compile(
    r"Not awake yet\.\s*Run:\s*(\S+)\s+wake\s+(\d+)\s+(\d+)",
    re.IGNORECASE,
)
_MAX_PARTS = 8
_WAKE_TIMEOUT_S = 30.0


def memo_path() -> Path:
    return Path(os.environ.get("OPTMEM_MEMO", str(_DEFAULT_MEMO))).expanduser()


def memory_dir() -> Path:
    override = os.environ.get("MEMORY_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".optmem" / "memory"


def optmem_available() -> bool:
    memo = memo_path()
    return memo.is_file() and os.access(memo, os.X_OK) and memory_dir().is_dir()


def run_memo_wake(*, memo: Path | None = None) -> str | None:
    """Run ``memo wake`` (following part prompts) and return stdout, or None."""
    tool = memo if memo is not None else memo_path()
    if not tool.is_file() or not os.access(tool, os.X_OK):
        return None
    if not memory_dir().is_dir():
        return None

    chunks: list[str] = []
    cmd = [str(tool), "wake"]
    for _ in range(_MAX_PARTS):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_WAKE_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("optmem wake failed: %s", exc)
            return None
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0 and not out:
            logger.warning(
                "optmem wake exit=%s stderr=%s",
                proc.returncode,
                err[:300],
            )
            return None
        if out:
            chunks.append(out)
        match = _PART_RE.search(out)
        if not match:
            break
        cmd = [match.group(1), "wake", match.group(2), match.group(3)]
    if not chunks:
        return None
    return "\n\n".join(chunks)


def format_optmem_wake_reminder(wake_text: str) -> str:
    """Body for ``wrap_system_reminder`` (without the XML tags)."""
    body = wake_text.strip()
    return (
        "[OptMem] Durable memory activated via `memo wake`. "
        "Treat the following as your long-term memory context. "
        "Register new lasting facts with `~/.optmem/memo note \"...\"`.\n\n"
        f"{body}"
    )
