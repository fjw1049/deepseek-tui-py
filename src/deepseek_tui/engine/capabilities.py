"""What this machine can run, so the model need not find out by trying.

Probed once per process and cached per machine: the answer sits in the stable
prompt prefix, so it must not change within a session.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import user_deepseek_dir

logger = logging.getLogger(__name__)

CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600
_PROBE_TIMEOUT_SECONDS = 3
# Package name -> import name, for the documents office tasks produce.
_LIBRARIES = {"python-docx": "docx", "openpyxl": "openpyxl", "python-pptx": "pptx"}
_LIBREOFFICE_PATHS = ("/Applications/LibreOffice.app/Contents/MacOS/soffice",)
_CHROME_PATHS = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",)
_CHROME_NAMES = ("google-chrome", "chromium", "chromium-browser")
_FIND_MODULES = (
    "import importlib.util as u,json,sys;"
    "print(json.dumps({n: u.find_spec(n) is not None for n in sys.argv[1:]}))"
)


def _run(*argv: str) -> str | None:
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def probe() -> dict[str, Any]:
    python = shutil.which("python3") or shutil.which("python")
    version = _run(python, "--version") if python else None
    modules = _run(python, "-c", _FIND_MODULES, *_LIBRARIES.values()) if python else None
    found = json.loads(modules) if modules else {}
    return {
        "python": version.split()[-1] if version else None,
        "node": _run("node", "--version") if shutil.which("node") else None,
        "libraries": {name: found.get(module, False) for name, module in _LIBRARIES.items()},
        "soffice": bool(shutil.which("soffice") or shutil.which("libreoffice")
                        or any(Path(path).exists() for path in _LIBREOFFICE_PATHS)),
        "pandoc": shutil.which("pandoc") is not None,
        "chrome": next((found for found in (
            *map(shutil.which, _CHROME_NAMES),
            *(path for path in _CHROME_PATHS if Path(path).exists())) if found), None),
        "timeout": "timeout" if shutil.which("timeout")
        else "gtimeout" if shutil.which("gtimeout") else None,
        "gnu_sed": _run("sed", "--version") is not None,
        # The app's own environment carries the document libraries the skill relies on.
        "office_python": sys.executable if all(
            importlib.util.find_spec(module) for module in _LIBRARIES.values()) else None,
    }


def _cache_path() -> Path:
    return user_deepseek_dir() / "caches" / "capabilities.json"


def _machine_key() -> str:
    # A different PATH can mean a different python, node and coreutils.
    machine = f"{sys.platform}\0{sys.executable}\0{os.environ.get('PATH', '')}"
    return hashlib.sha256(machine.encode()).hexdigest()


def _read_cache(key: str) -> dict[str, Any] | None:
    try:
        cached = json.loads(_cache_path().read_text(encoding="utf-8"))
        if cached["key"] == key and time.time() - cached["probed_at"] < CACHE_MAX_AGE_SECONDS:
            return cached["capabilities"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


@functools.cache
def machine_capabilities() -> dict[str, Any]:
    """Empty when probing fails: the block is an aid, never a startup failure."""
    key = _machine_key()
    cached = _read_cache(key)
    if cached is not None:
        return cached
    try:
        capabilities = probe()
    except (OSError, ValueError):
        logger.debug("capability_probe_failed", exc_info=True)
        return {}
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"key": key, "probed_at": time.time(), "capabilities": capabilities}), encoding="utf-8")
    except OSError:
        logger.debug("capability_cache_write_failed", exc_info=True)
    return capabilities


def render_capabilities(capabilities: dict[str, Any]) -> str:
    """Lines for ``## Environment``; states what is missing, since that is what gets tried."""
    if not capabilities:
        return ""
    python = capabilities.get("python")
    libraries = capabilities.get("libraries") or {}
    installed = [name for name, ok in libraries.items() if ok]
    missing = [name for name, ok in libraries.items() if not ok]
    detail = "; ".join(filter(None, [
        f"has {', '.join(installed)}" if installed else "",
        f"no {', '.join(missing)}" if missing else "",
    ]))
    lines = [
        f"- python: {python} ({detail})" if python else "- python: not installed",
        f"- node: {capabilities.get('node') or 'not installed'}",
        *([f"- office python: {office} (has {', '.join(libraries)}); "
           "load skill office-documents before writing document scripts"]
          if (office := capabilities.get("office_python")) else []),
        f"- soffice: {'available' if capabilities.get('soffice') else 'not installed'}",
        f"- pandoc: {'available' if capabilities.get('pandoc') else 'not installed'}",
        f"- chrome: {capabilities.get('chrome') or 'not installed'}",
    ]
    timeout = capabilities.get("timeout")
    if timeout != "timeout":
        lines.append(f"- timeout command: {timeout or 'none'}; prefer exec_shell timeout_ms")
    lines.append(f"- sed: {'GNU' if capabilities.get('gnu_sed') else 'BSD (sed -i needs an argument)'}")
    return "\n".join(lines)
