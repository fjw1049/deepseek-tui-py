from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SandboxResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int


_SANDBOX_PROFILE_TEMPLATE = """\
(version 1)
(deny default)
(allow process-exec)
(allow file-read*)
{write_rules}
(allow sysctl-read)
(allow mach-lookup)
"""


class Sandbox:
    """macOS sandbox-exec wrapper for restricting tool execution."""

    def __init__(self, allowed_write_paths: list[Path] | None = None) -> None:
        self._allowed_write_paths = allowed_write_paths or []

    async def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 30.0,
    ) -> SandboxResult:
        profile = self._build_profile()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sb", delete=False) as f:
            f.write(profile)
            profile_path = f.name

        try:
            process = await asyncio.create_subprocess_exec(
                "sandbox-exec",
                "-f",
                profile_path,
                *command,
                cwd=str(cwd) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return SandboxResult(
                success=process.returncode == 0,
                stdout=stdout.decode("utf-8") if stdout else "",
                stderr=stderr.decode("utf-8") if stderr else "",
                returncode=process.returncode or 0,
            )
        except asyncio.TimeoutError:
            process.kill()
            return SandboxResult(
                success=False,
                stdout="",
                stderr="sandbox execution timed out",
                returncode=-1,
            )
        finally:
            os.unlink(profile_path)

    def _build_profile(self) -> str:
        write_rules = ""
        for path in self._allowed_write_paths:
            write_rules += f'(allow file-write* (subpath "{path}"))\n'
        return _SANDBOX_PROFILE_TEMPLATE.format(write_rules=write_rules)
