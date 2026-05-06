from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.deepseek/config.toml")
DEFAULT_MANAGED_CONFIG_PATH = Path("/etc/deepseek/managed_config.toml")
DEFAULT_REQUIREMENTS_PATH = Path("/etc/deepseek/requirements.toml")
PROJECT_CONFIG_RELATIVE = Path(".deepseek/config.toml")


def expand_path(path: Path | str) -> Path:
    raw = os.path.expandvars(str(path))
    return Path(raw).expanduser()


def default_config_path() -> Path:
    return expand_path(os.getenv("DEEPSEEK_CONFIG_PATH", str(DEFAULT_CONFIG_PATH)))


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
