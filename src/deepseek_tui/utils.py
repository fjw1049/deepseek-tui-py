"""Shared utility functions, trace correlation, and logging setup.

Consolidates the former ``utils.py``, ``trace.py``, and ``logging_setup.py``
modules into a single infrastructure module.
"""

from __future__ import annotations



import contextvars
import json
import logging
import logging.handlers
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config

# ============================================================================
# General utilities
# ============================================================================


def write_json_atomic(path: Path, value: Any) -> None:
    """Write a JSON-serialisable value to *path* atomically (write-tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def summarize_text(text: str, limit: int = 280) -> str:
    """Truncate *text* to *limit* chars, appending '...' if needed."""
    take = max(limit - 3, 0)
    count = 0
    out: list[str] = []
    for ch in text:
        if count >= take:
            out.append("...")
            return "".join(out)
        if ch.isspace() or not (ch < " " or ch == "\x7f"):
            out.append(ch)
            count += 1
    return "".join(out)


# ============================================================================
# Trace correlation (formerly trace.py)
# ============================================================================

_turn_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "deepseek_turn_id", default=""
)
_tool_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "deepseek_tool_id", default=""
)


def short_id() -> str:
    """Generate an 8-char hex id suitable for one turn or tool call."""
    return uuid.uuid4().hex[:8]


def current_turn() -> str:
    """Return the currently bound turn id (empty string if unbound)."""
    return _turn_id.get()


def current_tool() -> str:
    """Return the currently bound tool-call id (empty string if unbound)."""
    return _tool_id.get()


@contextmanager
def bind_turn(turn_id: str | None = None) -> Iterator[str]:
    """Bind a turn id for the duration of the ``with`` block."""
    tid = turn_id or short_id()
    token = _turn_id.set(tid)
    try:
        yield tid
    finally:
        _turn_id.reset(token)


@contextmanager
def bind_tool(tool_call_id: str | None = None) -> Iterator[str]:
    """Bind a tool-call id for the duration of the ``with`` block."""
    if tool_call_id:
        compact = "".join(c for c in tool_call_id if c.isalnum())[:8]
        tid = compact or short_id()
    else:
        tid = short_id()
    token = _tool_id.set(tid)
    try:
        yield tid
    finally:
        _tool_id.reset(token)


class TraceFilter(logging.Filter):
    """Inject the current trace ids onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        turn = current_turn() or "-"
        tool = current_tool() or "-"
        record.trace_turn = turn  # type: ignore[attr-defined]
        record.trace_tool = tool  # type: ignore[attr-defined]
        record.trace_tag = f"[turn={turn} tool={tool}]"  # type: ignore[attr-defined]
        return True


# ============================================================================
# Logging setup (formerly logging_setup.py)
# ============================================================================

_INIT_MARKER = "_deepseek_log_setup_done"

_NOISY_LOGGERS: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "textual",
    "aiosqlite",
    "uvicorn.access",
)

_DEFAULT_FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)-5s %(trace_tag)s "
    "%(name)s  %(message)s"
)
_DEFAULT_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"

DEFAULT_LOG_DIR = Path(".deepseek/logs")
DEFAULT_KEEP_HOURS = 24


def _resolve_level(value: str | int) -> int:
    if isinstance(value, int):
        return value
    name = str(value).strip().upper()
    if not name:
        return logging.INFO
    return getattr(logging, name, logging.INFO)


def setup_logging(
    config: Config | None = None,
    *,
    level_override: str | int | None = None,
    dir_override: Path | str | None = None,
    console_override: bool | None = None,
) -> Path | None:
    """Initialise per-hour rotating file logging for the package."""
    cfg_logging = _shape_from_config(config)
    enabled = cfg_logging.enabled
    if level_override is not None:
        cfg_logging.level = _resolve_level(level_override)
    if dir_override is not None:
        cfg_logging.dir = Path(str(dir_override)).expanduser()
    if console_override is not None:
        cfg_logging.console = bool(console_override)

    root = logging.getLogger()
    _strip_previous_handlers(root)

    if not enabled:
        setattr(root, _INIT_MARKER, True)
        return None

    cfg_logging.dir = cfg_logging.dir.absolute()
    cfg_logging.dir.mkdir(parents=True, exist_ok=True)
    log_file = cfg_logging.dir / "deepseek.log"

    handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_file),
        when="H",
        interval=1,
        backupCount=cfg_logging.keep_hours,
        encoding="utf-8",
        utc=False,
    )
    handler.suffix = "%Y-%m-%d-%H"
    handler.namer = _rotated_namer
    formatter = logging.Formatter(fmt=_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)
    handler.setFormatter(formatter)
    handler.addFilter(TraceFilter())
    handler.set_name("deepseek_tui_file")
    handler._deepseek_owned = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    if cfg_logging.console:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.addFilter(TraceFilter())
        console.set_name("deepseek_tui_console")
        console._deepseek_owned = True  # type: ignore[attr-defined]
        root.addHandler(console)

    root.setLevel(cfg_logging.level)
    setattr(root, _INIT_MARKER, True)

    for name, lvl in cfg_logging.per_logger.items():
        logging.getLogger(name).setLevel(_resolve_level(lvl))

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(
            max(logging.WARNING, cfg_logging.level)
        )

    pkg_logger = logging.getLogger("deepseek_tui")
    pkg_logger.info(
        "log_setup file=%s level=%s console=%s keep_hours=%d",
        log_file,
        logging.getLevelName(cfg_logging.level),
        cfg_logging.console,
        cfg_logging.keep_hours,
    )
    return cfg_logging.dir


def current_log_path() -> Path | None:
    """Return the active log file path, or None if logging is off."""
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_deepseek_owned", False) and isinstance(
            handler, logging.handlers.TimedRotatingFileHandler
        ):
            return Path(handler.baseFilename)
    return None


def tail_log(n_lines: int = 50) -> list[str]:
    """Return the last ``n_lines`` from the current log file."""
    path = current_log_path()
    if path is None or not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n_lines:] if n_lines > 0 else lines


def _rotated_namer(default_name: str) -> str:
    base = Path(default_name)
    parent = base.parent
    name = base.name
    if name.startswith("deepseek.log."):
        suffix = name[len("deepseek.log."):]
        return str(parent / f"deepseek-{suffix}.log")
    return default_name


def _strip_previous_handlers(root: logging.Logger) -> None:
    keep: list[logging.Handler] = []
    for handler in root.handlers:
        if getattr(handler, "_deepseek_owned", False):
            try:
                handler.close()
            except Exception:
                pass
            continue
        keep.append(handler)
    root.handlers = keep


class _LoggingShape:
    __slots__ = ("enabled", "level", "dir", "console", "keep_hours", "per_logger")

    def __init__(
        self,
        *,
        enabled: bool,
        level: int,
        dir_: Path,
        console: bool,
        keep_hours: int,
        per_logger: dict[str, str],
    ) -> None:
        self.enabled = enabled
        self.level = level
        self.dir = dir_
        self.console = console
        self.keep_hours = keep_hours
        self.per_logger = dict(per_logger)


def _shape_from_config(config: Any | None) -> _LoggingShape:
    if config is None:
        return _LoggingShape(
            enabled=True,
            level=logging.INFO,
            dir_=DEFAULT_LOG_DIR,
            console=False,
            keep_hours=DEFAULT_KEEP_HOURS,
            per_logger={},
        )
    cfg = getattr(config, "logging", None)
    if cfg is None:
        return _LoggingShape(
            enabled=True,
            level=logging.INFO,
            dir_=DEFAULT_LOG_DIR,
            console=False,
            keep_hours=DEFAULT_KEEP_HOURS,
            per_logger={},
        )
    raw_dir = getattr(cfg, "dir", DEFAULT_LOG_DIR)
    return _LoggingShape(
        enabled=bool(getattr(cfg, "enabled", True)),
        level=_resolve_level(getattr(cfg, "level", "INFO")),
        dir_=Path(str(raw_dir)).expanduser(),
        console=bool(getattr(cfg, "console", False)),
        keep_hours=int(getattr(cfg, "keep_hours", DEFAULT_KEEP_HOURS)),
        per_logger=dict(getattr(cfg, "per_logger", {}) or {}),
    )
