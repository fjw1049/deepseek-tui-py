"""Composer paste-burst integration tests.

Mirror Rust ``paste_burst::newline_should_insert_instead_of_submit``
(paste_burst.rs:157) — after a paste containing newlines, the next
Enter should insert a newline instead of submitting.
"""

from __future__ import annotations

import pytest

from deepseek_tui.tui.widgets.composer import (
    PASTE_ENTER_SUPPRESS_WINDOW_SECS,
    Composer,
)


def test_paste_suppress_window_constant_matches_rust() -> None:
    """Mirror Rust ``PASTE_ENTER_SUPPRESS_WINDOW`` (paste_burst.rs:7)."""
    assert PASTE_ENTER_SUPPRESS_WINDOW_SECS == pytest.approx(0.120)


def _make_host_app(submitted_sink: list[str]) -> type:
    """Build an App subclass that captures Composer.Submitted into *sink*."""
    from textual.app import App, ComposeResult

    class _Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Composer()

        def on_composer_submitted(self, msg: Composer.Submitted) -> None:
            submitted_sink.append(msg.text)

    return _Host


@pytest.mark.asyncio
async def test_paste_with_newlines_suppresses_next_enter() -> None:
    """Pilot integration test: paste multi-line text, then press Enter,
    verify the Enter inserts a newline rather than submitting."""
    from textual.events import Paste

    submitted_texts: list[str] = []
    HostApp = _make_host_app(submitted_texts)

    async with HostApp().run_test() as pilot:
        composer = pilot.app.query_one(Composer)
        composer.focus()
        await pilot.pause()

        composer.post_message(Paste("hello\nworld"))
        await pilot.pause()

        assert "hello\nworld" in composer.text
        assert composer._paste_window_active()

        await pilot.press("enter")
        await pilot.pause()

        assert submitted_texts == []


@pytest.mark.asyncio
async def test_paste_without_newline_does_not_suppress_enter() -> None:
    """Single-line paste should NOT suppress the next Enter."""
    from textual.events import Paste

    submitted_texts: list[str] = []
    HostApp = _make_host_app(submitted_texts)

    async with HostApp().run_test() as pilot:
        composer = pilot.app.query_one(Composer)
        composer.focus()
        await pilot.pause()

        composer.post_message(Paste("inline-paste"))
        await pilot.pause()

        assert "inline-paste" in composer.text
        assert not composer._paste_window_active()

        await pilot.press("enter")
        await pilot.pause()

        assert submitted_texts == ["inline-paste"]
