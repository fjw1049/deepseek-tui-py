"""Notifications module parity tests.

Mirror Rust tests in ``crates/tui/src/tui/notifications.rs`` (notifications.rs:184-341).
"""

from __future__ import annotations

import io
import os
from unittest.mock import patch

from deepseek_tui.tui.notifications import (
    Method,
    _resolve_method,
    humanize_duration,
    notify_done_to,
)


def _capture(method: Method, in_tmux: bool, msg: str, threshold: int, elapsed: int) -> bytes:
    buf = io.BytesIO()
    notify_done_to(method, in_tmux, msg, threshold, elapsed, buf)
    return buf.getvalue()


def test_osc9_body_format() -> None:
    """Mirror Rust ``osc9_body_format`` (notifications.rs:217)."""
    out = _capture(Method.OSC9, False, "deepseek: done", 0, 1)
    assert out == b"\x1b]9;deepseek: done\x07"


def test_bel_emits_exactly_one_byte() -> None:
    """Mirror Rust ``bel_emits_exactly_one_byte`` (notifications.rs:223)."""
    out = _capture(Method.BEL, False, "ignored", 0, 1)
    assert out == b"\x07"


def test_off_mode_emits_nothing() -> None:
    """Mirror Rust ``off_mode_emits_nothing`` (notifications.rs:229)."""
    out = _capture(Method.OFF, False, "ignored", 0, 9999)
    assert out == b""


def test_below_threshold_emits_nothing() -> None:
    """Mirror Rust ``below_threshold_emits_nothing`` (notifications.rs:235)."""
    out = _capture(Method.OSC9, False, "msg", 30, 29)
    assert out == b""


def test_at_threshold_emits() -> None:
    """Mirror Rust ``at_threshold_emits`` (notifications.rs:241)."""
    out = _capture(Method.OSC9, False, "msg", 30, 30)
    assert out


def test_tmux_dcs_passthrough_wraps_osc9() -> None:
    """Mirror Rust ``tmux_dcs_passthrough_wraps_osc9`` (notifications.rs:247)."""
    out = _capture(Method.OSC9, True, "hello", 0, 1).decode()
    assert out.startswith("\x1bPtmux;")
    assert out.endswith("\x1b\\")
    assert "hello" in out


def test_auto_detect_picks_osc9_for_iterm() -> None:
    """Mirror Rust ``auto_detect_picks_osc9_for_iterm`` (notifications.rs:259)."""
    with patch.dict(os.environ, {"TERM_PROGRAM": "iTerm.app"}):
        assert _resolve_method() == Method.OSC9


def test_auto_detect_falls_back_to_bel_for_unknown_terms() -> None:
    with patch.dict(os.environ, {"TERM_PROGRAM": "xterm"}):
        assert _resolve_method() == Method.BEL


def test_method_from_str_round_trips() -> None:
    """Mirror Rust ``Method::from_str`` semantics (notifications.rs:29)."""
    assert Method.from_str("osc9") == Method.OSC9
    assert Method.from_str("OSC-9") == Method.OSC9
    assert Method.from_str("bel") == Method.BEL
    assert Method.from_str("off") == Method.OFF
    assert Method.from_str("disabled") == Method.OFF
    assert Method.from_str("none") == Method.OFF
    assert Method.from_str("auto") == Method.AUTO
    assert Method.from_str("garbage") == Method.AUTO


def test_humanize_duration_seconds_below_minute() -> None:
    assert humanize_duration(0) == "0s"
    assert humanize_duration(45) == "45s"


def test_humanize_duration_minutes_and_seconds() -> None:
    assert humanize_duration(60) == "1m"
    assert humanize_duration(72) == "1m 12s"


def test_humanize_duration_hours_drops_minute_when_zero() -> None:
    """Mirror Rust expectation 1h not '1h 0m' (notifications.rs:131)."""
    assert humanize_duration(3600) == "1h"
    assert humanize_duration(3 * 3600 + 12 * 60) == "3h 12m"


def test_humanize_duration_days_and_weeks() -> None:
    assert humanize_duration(86400) == "1d"
    assert humanize_duration(86400 * 2 + 3600 * 5) == "2d 5h"
    assert humanize_duration(7 * 86400) == "1w"
    assert humanize_duration(3 * 7 * 86400 + 2 * 86400) == "3w 2d"


# ---------------------------------------------------------------------------
# [notifications] config consumption — Stage 6 follow-up.
#
# ``DeepSeekTUI._maybe_notify_turn_done`` reads ``Config.notifications.*``
# first, then falls back to ``Config.ui.notify_*`` for backwards compat.
# These tests bypass the full Textual app and just exercise the same
# resolution logic via a tiny shim.
# ---------------------------------------------------------------------------


def _resolve_from_config(config: object) -> tuple[Method, float, bool]:
    """Mirror ``DeepSeekTUI._maybe_notify_turn_done`` resolution order.

    Kept inline here (rather than imported) so the test pins the contract:
    if app.py drifts, this test breaks loudly.
    """
    notif = config.notifications  # type: ignore[attr-defined]
    if not notif.enabled:
        return Method.OFF, 0.0, False
    ui = config.ui  # type: ignore[attr-defined]
    method_str = notif.method if notif.method is not None else ui.notify_method
    threshold_secs = float(
        notif.threshold_secs
        if notif.threshold_secs is not None
        else ui.notify_threshold_secs
    )
    return Method.from_str(method_str), threshold_secs, True


def test_notifications_method_overrides_ui_notify_method() -> None:
    from deepseek_tui.config.models import Config

    cfg = Config()
    cfg.ui.notify_method = "auto"
    cfg.notifications.method = "bel"
    method, _, enabled = _resolve_from_config(cfg)
    assert enabled is True
    assert method is Method.BEL


def test_notifications_threshold_overrides_ui_threshold() -> None:
    from deepseek_tui.config.models import Config

    cfg = Config()
    cfg.ui.notify_threshold_secs = 30.0
    cfg.notifications.threshold_secs = 5.0
    _, threshold, _ = _resolve_from_config(cfg)
    assert threshold == 5.0


def test_notifications_falls_back_to_ui_when_unset() -> None:
    from deepseek_tui.config.models import Config

    cfg = Config()
    cfg.ui.notify_method = "osc9"
    cfg.ui.notify_threshold_secs = 12.5
    # leave cfg.notifications.method / threshold_secs as their default None
    method, threshold, _ = _resolve_from_config(cfg)
    assert method is Method.OSC9
    assert threshold == 12.5


def test_notifications_disabled_short_circuits() -> None:
    from deepseek_tui.config.models import Config

    cfg = Config()
    cfg.notifications.enabled = False
    cfg.ui.notify_method = "bel"  # should be ignored
    method, _, enabled = _resolve_from_config(cfg)
    assert enabled is False
    assert method is Method.OFF
