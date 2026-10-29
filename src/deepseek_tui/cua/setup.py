"""One-click setup of the desktop-control components, for the Workbench setup checklist.

LCU is installed from one pinned release whose archive digests are fixed here, so a changed
or substituted download fails closed. The release's own installer does the actual setup.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

LCU_VERSION = "0.11.6"
# From the release's published .sha256 files (github.com/amontlabs/lcu, tag v0.11.6).
LCU_SHA256 = {
    "darwin-arm64": "0f512eb0d00a3576edfd4509fb5ff1b5917a0a069080e3a22ad196d70e7e5ccb",
}
LCU_DOWNLOAD = "https://github.com/amontlabs/lcu/releases/download/v{version}/lcu-{version}-{target}.tar.gz"
LCU_GUIDE = "https://github.com/amontlabs/lcu/blob/main/docs/INSTALLATION.md"
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
CHATGPT_DOWNLOAD = "https://chatgpt.com/download/"
CHATGPT_NODE = Path("/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node")
INSTALL_TIMEOUT = 600
CHECK_SCRIPT = Path(__file__).with_name("chrome_check.mjs")


class SetupError(Exception):
    """A setup step failed; the message is shown to the user."""


def target() -> str | None:
    """The one-click target for this machine; Linux needs root and apt, so it stays manual."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "darwin-arm64"
    return None


def chatgpt_installed() -> bool:
    return sys.platform == "darwin" and CHATGPT_NODE.is_file()


def installed_version(installation: Path) -> str | None:
    """The release the installation points at (releases/<version>-<build>), if installed."""
    root = installation.expanduser()
    if not (root / "bin/lcu").is_file() or not (root / "node-path").is_file():
        return None
    return root.resolve().name.split("-", 1)[0] or None


def connector_state(status_output: str) -> str:
    """Read `lcu browser status`: its extension check may fail while the connector is fine."""
    for line in status_output.splitlines():
        if line.startswith("Chrome connector:"):
            return "installed" if "configured" in line else "missing"
    return "unknown"


def _download(url: str, destination: Path) -> str:
    import httpx

    digest = hashlib.sha256()
    size = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        with destination.open("wb") as out:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise SetupError("The LCU download is larger than expected.")
                digest.update(chunk)
                out.write(chunk)
    return digest.hexdigest()


def _extract(archive: Path, destination: Path) -> Path:
    """Extract with the data filter: no absolute paths, links out of the tree, or devices."""
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(destination, filter="data")
    roots = [p for p in destination.iterdir() if (p / "scripts/install.sh").is_file()]
    if len(roots) != 1:
        raise SetupError("The LCU release does not contain its installer.")
    return roots[0]


async def install_lcu() -> dict[str, Any]:
    """Download the pinned release, verify its digest, and run its installer (runtime only)."""
    machine = target()
    if machine is None:
        raise SetupError("One-click installation supports Apple Silicon Macs; follow the guide.")
    if not chatgpt_installed():
        raise SetupError(
            "Install the ChatGPT desktop app first; LCU runs its computer-use runtime.")
    url = LCU_DOWNLOAD.format(version=LCU_VERSION, target=machine)
    work = Path(tempfile.mkdtemp(prefix="lcu-install-"))
    try:
        archive = work / "lcu.tar.gz"
        try:
            digest = await asyncio.to_thread(_download, url, archive)
        except SetupError:
            raise
        except Exception as exc:  # Network and HTTP failures alike: report, install nothing.
            raise SetupError(f"Could not download LCU {LCU_VERSION}: {exc}") from exc
        if digest != LCU_SHA256[machine]:
            raise SetupError("The LCU download failed its integrity check; nothing was installed.")
        try:
            release = await asyncio.to_thread(_extract, archive, work / "release")
        except (tarfile.TarError, OSError) as exc:
            raise SetupError(
                "The LCU release could not be unpacked; nothing was installed.") from exc
        process = await asyncio.create_subprocess_exec(
            "/bin/sh", str(release / "scripts/install.sh"), "--runtime-only", "--yes",
            cwd=release, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(process.communicate(), INSTALL_TIMEOUT)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise SetupError("The LCU installer did not finish in time.") from exc
        log = out.decode(errors="replace").strip()
        if process.returncode != 0:
            raise SetupError((log.splitlines() or ["The LCU installer failed."])[-1][:500])
        return {"version": LCU_VERSION, "log": log[-2000:]}
    finally:
        await asyncio.to_thread(shutil.rmtree, work, True)


async def verify_chrome(node: str, client: Path, executable: Path) -> dict[str, Any]:
    """Ask the runtime which browsers it reaches; reads no tab, page or desktop content."""
    process = await asyncio.create_subprocess_exec(
        node, str(CHECK_SCRIPT), str(client), str(executable),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), 90)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return {"connected": False, "reason": "timeout"}
    for line in reversed(out.decode(errors="replace").splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict) and "connected" in result:
            reason = result.get("reason")
            return {"connected": result["connected"] is True,
                    "reason": reason if isinstance(reason, str) else None}
    return {"connected": False, "reason": "no-result"}
