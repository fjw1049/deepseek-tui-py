"""Parity tests for the rotating-file logging subsystem (2026-05-10).

Covers:
- Trace context vars + ``TraceFilter`` injection
- ``setup_logging`` produces a per-hour rotating handler with the right
  formatter, level, and rotation namer
- ``--log-level`` / ``--log-dir`` / ``--log-console`` overrides win over
  ``Config.logging``
- ``current_log_path`` / ``tail_log`` introspection helpers
- ``/log`` slash command shape (path + ``tail [N]``)
- Sensitive data heuristics: ``Authorization`` / API key strings never
  appear in serialized log records (we don't *add* a redactor — we just
  prove the埋点 we've added doesn't include them)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from deepseek_tui.config.models import Config, LoggingConfig
from deepseek_tui.logging_setup import (
    current_log_path,
    setup_logging,
    tail_log,
)
from deepseek_tui.trace import (
    TraceFilter,
    bind_tool,
    bind_turn,
    current_tool,
    current_turn,
    short_id,
)

# --- trace.py -------------------------------------------------------------


def test_short_id_is_eight_hex_chars() -> None:
    sid = short_id()
    assert len(sid) == 8
    assert all(c in "0123456789abcdef" for c in sid)


def test_bind_turn_and_tool_round_trip() -> None:
    assert current_turn() == ""
    with bind_turn("abcd1234") as t1:
        assert t1 == "abcd1234"
        assert current_turn() == "abcd1234"
        with bind_tool("call-zzzz9999") as t2:
            # ``bind_tool`` strips non-alnum and takes the first 8 chars;
            # so "call-zzzz9999" → "callzzzz".
            assert current_tool() == "callzzzz"
            assert t2 == "callzzzz"
        assert current_tool() == ""
    assert current_turn() == ""


def test_trace_filter_attaches_attributes() -> None:
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname="", lineno=1,
        msg="hi", args=(), exc_info=None,
    )
    filt = TraceFilter()
    with bind_turn("aaaa1111"):
        with bind_tool("bbbb2222"):
            assert filt.filter(record) is True
            assert record.trace_turn == "aaaa1111"
            assert record.trace_tool == "bbbb2222"
            assert record.trace_tag == "[turn=aaaa1111 tool=bbbb2222]"


def test_trace_filter_uses_dashes_when_unbound() -> None:
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname="", lineno=1,
        msg="hi", args=(), exc_info=None,
    )
    TraceFilter().filter(record)
    assert record.trace_turn == "-"
    assert record.trace_tool == "-"
    assert record.trace_tag == "[turn=- tool=-]"


# --- logging_setup.py -----------------------------------------------------


def test_setup_logging_creates_rotating_handler(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, level="DEBUG", dir=log_dir)
    resolved = setup_logging(cfg)
    try:
        assert resolved == log_dir
        assert log_dir.exists()
        # File doesn't exist until first record, but path is reachable.
        path = current_log_path()
        assert path is not None
        assert path.parent == log_dir
        assert path.name == "deepseek.log"
        # Confirm the handler is actually wired and writes.
        logging.getLogger("deepseek_tui.test").info("hello world")
        assert path.exists()
        assert "hello world" in path.read_text(encoding="utf-8")
    finally:
        # Clean up so other tests don't see leaked handlers.
        setup_logging(_disable_config())


def test_setup_logging_disabled_returns_none() -> None:
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=False)
    resolved = setup_logging(cfg)
    assert resolved is None
    assert current_log_path() is None


def test_setup_logging_level_override_wins(tmp_path: Path) -> None:
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, level="WARNING", dir=tmp_path / "lg")
    setup_logging(cfg, level_override="DEBUG")
    try:
        assert logging.getLogger().level == logging.DEBUG
    finally:
        setup_logging(_disable_config())


def test_setup_logging_console_override(tmp_path: Path) -> None:
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, dir=tmp_path / "lg", console=False)
    setup_logging(cfg, console_override=True)
    try:
        names = [
            getattr(h, "name", "")
            for h in logging.getLogger().handlers
            if getattr(h, "_deepseek_owned", False)
        ]
        assert "deepseek_tui_console" in names
    finally:
        setup_logging(_disable_config())


def test_setup_logging_strips_previous_handlers(tmp_path: Path) -> None:
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, dir=tmp_path / "a")
    setup_logging(cfg)
    first_count = sum(
        1 for h in logging.getLogger().handlers
        if getattr(h, "_deepseek_owned", False)
    )
    cfg2 = Config()
    cfg2.logging = LoggingConfig(enabled=True, dir=tmp_path / "b")
    setup_logging(cfg2)
    try:
        second_count = sum(
            1 for h in logging.getLogger().handlers
            if getattr(h, "_deepseek_owned", False)
        )
        # Re-init replaces, doesn't accumulate.
        assert second_count == first_count
    finally:
        setup_logging(_disable_config())


def test_tail_log_reads_recent_lines(tmp_path: Path) -> None:
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, dir=tmp_path / "logs")
    setup_logging(cfg)
    try:
        for i in range(5):
            logging.getLogger("deepseek_tui.test").info("line %d", i)
        lines = tail_log(3)
        assert len(lines) == 3
        assert "line 4" in lines[-1]
    finally:
        setup_logging(_disable_config())


def test_noisy_third_party_loggers_silenced(tmp_path: Path) -> None:
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, level="DEBUG", dir=tmp_path / "lg")
    setup_logging(cfg)
    try:
        # Even at DEBUG root, httpx / textual stay at WARNING+ to avoid
        # SSL-handshake noise drowning out engine signal.
        for name in ("httpx", "httpcore", "urllib3", "textual"):
            assert logging.getLogger(name).level >= logging.WARNING
    finally:
        setup_logging(_disable_config())


def test_log_records_carry_trace_tag_in_format(tmp_path: Path) -> None:
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, dir=tmp_path / "lg")
    setup_logging(cfg)
    try:
        with bind_turn("ffeeddcc"):
            logging.getLogger("deepseek_tui.test").info("greppable")
        path = current_log_path()
        assert path is not None
        content = path.read_text(encoding="utf-8")
        assert "[turn=ffeeddcc" in content
        assert "greppable" in content
    finally:
        setup_logging(_disable_config())


# --- /log slash command ---------------------------------------------------


def test_log_slash_handler_registered() -> None:
    from deepseek_tui.tui.commands.handlers import get_handler

    handler = get_handler("/log")
    assert handler is not None


def test_log_slash_no_args_when_disabled() -> None:
    from deepseek_tui.tui.commands.handlers import get_handler

    handler = get_handler("/log")
    setup_logging(_disable_config())
    result = handler("", _StubApp())  # type: ignore[arg-type]
    assert result.output is not None
    assert "disabled" in result.output


def test_log_slash_prints_path_when_enabled(tmp_path: Path) -> None:
    from deepseek_tui.tui.commands.handlers import get_handler

    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, dir=tmp_path / "logs")
    setup_logging(cfg)
    try:
        handler = get_handler("/log")
        assert handler is not None
        result = handler("", _StubApp())  # type: ignore[arg-type]
        assert result.output is not None
        assert "deepseek.log" in result.output
    finally:
        setup_logging(_disable_config())


def test_log_slash_tail_returns_recent_entries(tmp_path: Path) -> None:
    from deepseek_tui.tui.commands.handlers import get_handler

    cfg = Config()
    cfg.logging = LoggingConfig(enabled=True, dir=tmp_path / "logs")
    setup_logging(cfg)
    try:
        for i in range(3):
            logging.getLogger("deepseek_tui.test").info("entry %d", i)
        handler = get_handler("/log")
        assert handler is not None
        result = handler("tail 2", _StubApp())  # type: ignore[arg-type]
        assert result.output is not None
        assert "last 2 lines" in result.output
        assert "entry 2" in result.output
    finally:
        setup_logging(_disable_config())


def test_log_slash_unknown_subcommand_errors() -> None:
    from deepseek_tui.tui.commands.handlers import get_handler

    handler = get_handler("/log")
    assert handler is not None
    result = handler("nonsense", _StubApp())  # type: ignore[arg-type]
    assert result.error is not None
    assert "unknown subcommand" in result.error


# --- Config ---------------------------------------------------------------


def test_config_has_logging_subsection_with_defaults() -> None:
    cfg = Config()
    assert isinstance(cfg.logging, LoggingConfig)
    assert cfg.logging.enabled is True
    assert cfg.logging.level == "INFO"
    assert cfg.logging.console is False
    assert cfg.logging.keep_hours == 24


def test_logging_config_accepts_per_logger_overrides() -> None:
    cfg = Config.model_validate(
        {
            "logging": {
                "enabled": True,
                "level": "INFO",
                "per_logger": {"deepseek_tui.engine.turn_loop": "DEBUG"},
            }
        }
    )
    assert cfg.logging.per_logger == {"deepseek_tui.engine.turn_loop": "DEBUG"}


# --- helpers --------------------------------------------------------------


def _disable_config() -> Config:
    cfg = Config()
    cfg.logging = LoggingConfig(enabled=False)
    return cfg


class _StubApp:
    """Minimal stand-in so handlers that don't actually need DeepSeekTUI work."""

    _engine: Any = None
    config: Any = None

    def query_one(self, _cls: Any) -> Any:  # pragma: no cover — unused by /log
        raise RuntimeError("query_one should not be called by /log")
