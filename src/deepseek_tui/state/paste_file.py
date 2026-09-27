"""Spill a large composer paste into a workspace ``.txt`` and mention it.

Mirrors the common chat-composer pattern: a few words stay inline, a dump
(log, stack, article) becomes a file so the input box stays a short request.
Keep the line/char thresholds in sync with the Workbench helper
``packages/workbench/src/renderer/src/lib/composer-paste-file.ts``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

PASTE_DIR = Path(".deepseek") / "pastes"
LARGE_PASTE_MIN_LINES = 8
LARGE_PASTE_MIN_CHARS = 800


def is_large_paste(text: str) -> bool:
    if not text or not text.strip():
        return False
    if len(text) >= LARGE_PASTE_MIN_CHARS:
        return True
    return len(text.splitlines()) >= LARGE_PASTE_MIN_LINES


def write_paste_txt(text: str, workspace: Path) -> Path:
    dest_dir = Path(workspace) / PASTE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    n = 1
    while True:
        suffix = "" if n == 1 else f"-{n}"
        dest = dest_dir / f"paste-{stamp}{suffix}.txt"
        try:
            with dest.open("x", encoding="utf-8") as stream:
                stream.write(text)
            return dest
        except FileExistsError:
            n += 1


def mention_for_paste(path: Path, workspace: Path) -> str:
    try:
        token = path.resolve().relative_to(Path(workspace).resolve()).as_posix()
    except ValueError:
        token = Path(path).as_posix()
    if any(ch.isspace() for ch in token):
        return f'@"{token}"'
    return f"@{token}"
