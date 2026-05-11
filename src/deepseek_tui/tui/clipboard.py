"""Clipboard handling for paste/copy support in TUI.

Mirrors ``crates/tui/src/tui/clipboard.rs`` (246 LOC).

Text uses platform-native commands (``pbcopy``/``pbpaste`` on macOS,
``xclip`` on Linux) so we don't have to add ``pyperclip`` as a runtime
dependency. Read returns the text payload; write_text returns success.

Image paste is a known simplification (recorded in HANDOVER): Rust uses
``arboard`` + ``image`` to receive RGBA pixels and encode PNG into
``~/.deepseek/clipboard-images/``. Since DeepSeek V4 doesn't accept inline
images on Chat Completions, the Rust TUI materializes them to disk so the
model can reach them via ``@``-mention. Doing the same in Python requires
``Pillow`` + a clipboard image backend (e.g. ``pngpaste``); this is left
as a follow-up to keep the stage changes surgical.

The strip path on copy uses :mod:`deepseek_tui.tui.osc8` to remove OSC 8
hyperlink wrappers so the user pastes plain text.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from deepseek_tui.tui.osc8 import strip as osc8_strip


@dataclass(frozen=True, slots=True)
class PastedImage:
    """Metadata for a pasted image (mirrors Rust ``PastedImage``)."""

    path: Path
    width: int
    height: int
    byte_len: int

    def short_label(self) -> str:
        """Mirror Rust ``PastedImage::short_label`` (clipboard.rs:36)."""
        return f"{self.width}x{self.height} PNG"

    def size_label(self) -> str:
        """Mirror Rust ``PastedImage::size_label`` (clipboard.rs:40)."""
        kb = round(self.byte_len / 1024.0)
        return f"{kb}KB"


def _macos() -> bool:
    return os.uname().sysname == "Darwin"


def write_text(text: str) -> bool:
    """Write *text* to the system clipboard.

    Mirrors Rust ``ClipboardHandler::write_text`` (clipboard.rs:90).
    OSC 8 escapes are stripped from the payload so the user pastes the
    visible label, not the wrapper.
    Returns True on success, False if no clipboard backend is available.
    """
    plain = osc8_strip(text)
    if _macos() and shutil.which("pbcopy"):
        try:
            proc = subprocess.run(  # noqa: S603,ASYNC221
                ["pbcopy"],
                input=plain.encode("utf-8"),
                check=False,
            )
            return proc.returncode == 0
        except OSError:
            return False
    if shutil.which("xclip"):
        try:
            proc = subprocess.run(  # noqa: S603,ASYNC221
                ["xclip", "-selection", "clipboard"],
                input=plain.encode("utf-8"),
                check=False,
            )
            return proc.returncode == 0
        except OSError:
            return False
    if shutil.which("wl-copy"):
        try:
            proc = subprocess.run(  # noqa: S603,ASYNC221
                ["wl-copy"],
                input=plain.encode("utf-8"),
                check=False,
            )
            return proc.returncode == 0
        except OSError:
            return False
    return False


def read_text() -> str | None:
    """Read text payload from the system clipboard.

    Mirrors Rust ``ClipboardHandler::read`` text branch (clipboard.rs:74).
    Returns None when no clipboard backend or no text available.
    """
    if _macos() and shutil.which("pbpaste"):
        try:
            result = subprocess.run(  # noqa: S603,ASYNC221
                ["pbpaste"],
                capture_output=True,
                check=False,
                timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.decode("utf-8", errors="replace")
        except OSError:
            return None
    if shutil.which("xclip"):
        try:
            result = subprocess.run(  # noqa: S603,ASYNC221
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                check=False,
                timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.decode("utf-8", errors="replace")
        except OSError:
            return None
    return None


def clipboard_images_dir(workspace: Path) -> Path:
    """Resolve the directory pasted images should land in.

    Mirrors Rust ``clipboard_images_dir`` (clipboard.rs:142). Project-local
    since 2026-05-11: pasted images land under ``<workspace>/.deepseek/
    clipboard-images/`` (or fall back to ``<workspace>/clipboard-images/``
    when ``HOME`` is unset, for test environments that scrub the env).
    """
    if "HOME" in os.environ:
        return workspace / ".deepseek" / "clipboard-images"
    return workspace / "clipboard-images"
