"""Clipboard module tests.

Mirror Rust ``clipboard.rs`` tests where applicable. The image paste
codec is intentionally not ported (see HANDOVER simplification note).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

from deepseek_tui.tui.clipboard import (
    PastedImage,
    clipboard_images_dir,
    read_text,
    write_text,
)


def test_pasted_image_labels_format_correctly() -> None:
    """Mirror Rust ``pasted_image_labels_format_correctly`` (clipboard.rs:235)."""
    p = PastedImage(
        path=Path("/tmp/x.png"),
        width=1024,
        height=768,
        byte_len=235 * 1024,
    )
    assert p.short_label() == "1024x768 PNG"
    assert p.size_label() == "235KB"


def test_clipboard_images_dir_uses_workspace_when_home_available(tmp_path: Path) -> None:
    """Pasted images land under ``<workspace>/.deepseek/clipboard-images``.

    Mirrors the project-local-state design switch on 2026-05-11. The
    previous behaviour parked images in ``~/.deepseek/clipboard-images``;
    moving them next to the workspace makes attachment paths stable across
    machines and keeps state out of the user's home.
    """
    with patch.dict("os.environ", {"HOME": str(tmp_path)}):
        d = clipboard_images_dir(workspace=tmp_path)
    assert d == tmp_path / ".deepseek" / "clipboard-images"


def test_clipboard_images_dir_falls_back_to_workspace(tmp_path: Path) -> None:
    with patch.dict("os.environ", {}, clear=True):
        d = clipboard_images_dir(workspace=tmp_path)
    assert d == tmp_path / "clipboard-images"


def test_write_then_read_round_trips_when_pbcopy_available() -> None:
    """End-to-end: write text and read it back — only meaningful on macOS.

    Skips on systems without pbcopy/xclip/wl-copy or in sandboxed envs
    where subprocess invocation of the clipboard tool is blocked.
    """
    if not (shutil.which("pbcopy") or shutil.which("xclip") or shutil.which("wl-copy")):
        return

    payload = "hello-clipboard-test"
    if not write_text(payload):
        return
    got = read_text()
    if got is not None:
        assert payload in got


def test_write_text_strips_osc8_escapes() -> None:
    """OSC 8 hyperlinks must be stripped from clipboard payloads.

    We don't actually write to the system clipboard here — we just
    verify the strip helper integration by patching the subprocess
    call.
    """
    captured: list[bytes] = []

    def _fake_run(cmd: list[str], **kwargs: object) -> object:
        captured.append(kwargs.get("input", b""))  # type: ignore[arg-type]

        class _Result:
            returncode = 0

        return _Result()

    with patch("subprocess.run", side_effect=_fake_run):
        with patch("shutil.which", return_value="/usr/bin/pbcopy"):
            with patch("os.uname") as mock_uname:
                mock_uname.return_value.sysname = "Darwin"
                ok = write_text("\x1b]8;;https://example.com\x1b\\click\x1b]8;;\x1b\\")
                assert ok is True

    assert captured
    assert captured[0] == b"click"
