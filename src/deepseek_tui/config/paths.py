from __future__ import annotations

import os
from pathlib import Path

# State, logs, and config live next to the project (``./.deepseek/``) rather
# than under ``~/.deepseek/``. This keeps each checkout / clone isolated and
# avoids cross-project pollution (e.g. pytest tmp-dir zombie tasks bleeding
# across runs). Override via the ``DEEPSEEK_HOME`` env var for tests or
# system-wide installs.
DEFAULT_DOT_DEEPSEEK_RELATIVE = Path(".deepseek")
DEFAULT_CONFIG_PATH = DEFAULT_DOT_DEEPSEEK_RELATIVE / "config.toml"
DEFAULT_MANAGED_CONFIG_PATH = Path("/etc/deepseek/managed_config.toml")
DEFAULT_REQUIREMENTS_PATH = Path("/etc/deepseek/requirements.toml")
PROJECT_CONFIG_RELATIVE = DEFAULT_DOT_DEEPSEEK_RELATIVE / "config.toml"


def expand_path(path: Path | str) -> Path:
    raw = os.path.expandvars(str(path))
    return Path(raw).expanduser()


def dot_deepseek_dir() -> Path:
    """Resolve the ``.deepseek`` data directory.

    Precedence:
      1. ``DEEPSEEK_HOME`` env var — absolute or ``~``-relative override
      2. ``./.deepseek`` — project-local default (cwd at call time)

    Callers should always go through this helper; do *not* hardcode
    ``Path.home() / ".deepseek"`` anywhere. Switching to project-local
    isolation was an explicit design choice (commit history references
    pytest tmp-dir zombie tasks polluting global ``~/.deepseek``).
    """
    override = os.getenv("DEEPSEEK_HOME")
    if override:
        return expand_path(override)
    return Path.cwd() / DEFAULT_DOT_DEEPSEEK_RELATIVE


def default_config_path() -> Path:
    override = os.getenv("DEEPSEEK_CONFIG_PATH")
    if override:
        return expand_path(override)
    return dot_deepseek_dir() / "config.toml"


def project_config_path(workspace: Path | None = None) -> Path:
    root = workspace or Path.cwd()
    return root / PROJECT_CONFIG_RELATIVE


def dotenv_path(workspace: Path | None = None) -> Path:
    root = workspace or Path.cwd()
    return root / ".env"


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
