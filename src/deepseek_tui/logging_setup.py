"""Central logging configuration for the deepseek_tui package.

Wires up a per-hour rotating file handler under ``~/.deepseek/logs/`` with
trace correlation ids (see :mod:`deepseek_tui.trace`) and conservative
defaults for noisy third-party loggers (``httpx`` / ``urllib3`` / ``textual``).

Usage from the CLI / app server / MCP server entry points::

    from deepseek_tui.logging_setup import setup_logging
    setup_logging(config)

Calling :func:`setup_logging` more than once is safe — duplicate handlers
are removed so the file pool doesn't grow.

This module deliberately avoids JSON or external aggregators (per the
2026-05-10 design discussion: text-only, local files, 24h retention).
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.trace import TraceFilter

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config

# Marker attribute on the root logger so we can detect re-init and
# clean up old handlers without losing custom handlers added by callers.
_INIT_MARKER = "_deepseek_log_setup_done"

# Loggers we want to silence at WARNING regardless of root level — these
# emit DEBUG noise on TLS handshake / connection pooling / SQL traffic
# that drowns out the engine signal during real-API testing.
_NOISY_LOGGERS: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "textual",
    "aiosqlite",
    "uvicorn.access",  # we have our own request middleware
)

_DEFAULT_FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)-5s %(trace_tag)s "
    "%(name)s  %(message)s"
)
_DEFAULT_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"

# Project-local default. ``project_logs_dir(workspace)`` is the typed
# helper for callers that have a workspace handle; this constant is the
# bare fallback used before Config is loaded.
DEFAULT_LOG_DIR = Path(".deepseek/logs")
DEFAULT_KEEP_HOURS = 24


def _resolve_level(value: str | int) -> int:
    """Accept ``"DEBUG"`` / ``"info"`` / numeric levels uniformly."""
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
    """Initialise per-hour rotating file logging for the package.

    Returns the resolved log directory (so callers / ``/log`` slash can
    surface it to the user), or ``None`` when logging is disabled.

    Each call removes any handlers previously installed by this function
    so successive invocations (e.g. CLI ``--log-level`` overrides on top
    of a fresh ``Config``) don't duplicate output.

    :param config: optional :class:`Config` carrying ``Config.logging`` —
        when absent, sensible defaults are used (``INFO`` to
        ``~/.deepseek/logs/`` for 24 hours).
    :param level_override: CLI ``--log-level`` flag, takes precedence
        over ``config.logging.level``.
    :param dir_override: CLI ``--log-dir``.
    :param console_override: CLI ``--log-console``.
    """
    cfg_logging: _LoggingShape = _shape_from_config(config)
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
        # Mark as initialised so duplicate calls are still cheap, but
        # don't touch handler config. Callers may still log to stderr
        # via their own setup.
        setattr(root, _INIT_MARKER, True)
        return None

    # Resolve to an absolute path before handing off to TimedRotatingFileHandler.
    # The handler stores the filename verbatim and re-resolves on each rotate;
    # if cwd ever shifts mid-run (tools that chdir), logs would split across
    # directories. Snapshotting against the cwd at setup time avoids that.
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
    # Suffix so rotated files carry the YYYY-MM-DD-HH stamp users grep
    # for. ``namer`` rewrites the rotated filename so it matches the
    # convention agreed in the design doc ("deepseek-2026-05-10-19.log").
    handler.suffix = "%Y-%m-%d-%H"
    handler.namer = _rotated_namer
    formatter = logging.Formatter(fmt=_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)
    handler.setFormatter(formatter)
    handler.addFilter(TraceFilter())
    handler.set_name("deepseek_tui_file")

    # Tag our handlers so ``_strip_previous_handlers`` can find them on
    # re-init. Setting a dynamic attribute is enough — subclassing the
    # stdlib handlers breaks pickling under uvicorn.
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

    # Per-logger overrides. Useful when the user wants
    # ``deepseek_tui.engine.turn_loop = DEBUG`` while keeping the rest
    # at INFO during long-running tests.
    for name, lvl in cfg_logging.per_logger.items():
        logging.getLogger(name).setLevel(_resolve_level(lvl))

    for name in _NOISY_LOGGERS:
        # Don't drop them below WARNING — still want to see real errors,
        # just not the chatty handshake / pool / EOF noise.
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
    """Return the active log file path, or ``None`` if logging is off.

    Used by the ``/log`` slash command to surface "where are my logs?"
    without duplicating handler-walking logic.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, "_deepseek_owned", False) and isinstance(
            handler, logging.handlers.TimedRotatingFileHandler
        ):
            return Path(handler.baseFilename)
    return None


def tail_log(n_lines: int = 50) -> list[str]:
    """Return the last ``n_lines`` from the current log file.

    Best-effort: returns an empty list if logging is off or the file
    can't be opened. Reads the entire file then slices — fine for the
    24-hour retention window since each per-hour file caps at a few MB
    of human-readable text.
    """
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
    """Rewrite ``deepseek.log.YYYY-MM-DD-HH`` → ``deepseek-YYYY-MM-DD-HH.log``."""
    base = Path(default_name)
    parent = base.parent
    name = base.name
    if name.startswith("deepseek.log."):
        suffix = name[len("deepseek.log."):]
        return str(parent / f"deepseek-{suffix}.log")
    return default_name


def _strip_previous_handlers(root: logging.Logger) -> None:
    """Remove handlers added by a previous :func:`setup_logging` call."""
    keep: list[logging.Handler] = []
    for handler in root.handlers:
        if getattr(handler, "_deepseek_owned", False):
            try:
                handler.close()
            except Exception:  # noqa: BLE001 — handler.close() may double-fire
                pass
            continue
        keep.append(handler)
    root.handlers = keep


class _LoggingShape:
    """Mutable view over either a :class:`Config.logging` or fresh defaults.

    Avoids importing :class:`Config` at module load time so test fixtures
    that monkey-patch the config module don't deadlock with circular
    imports.
    """

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


__all__ = [
    "DEFAULT_KEEP_HOURS",
    "DEFAULT_LOG_DIR",
    "current_log_path",
    "setup_logging",
    "tail_log",
]
