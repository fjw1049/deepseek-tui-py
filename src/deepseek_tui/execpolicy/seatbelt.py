"""macOS Seatbelt (sandbox-exec) profile generation.

Port of ``docs/DeepSeek-TUI-main/crates/tui/src/sandbox/seatbelt.rs``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.execpolicy.sandbox import ExecutionSandboxPolicy

SANDBOX_EXEC_PATH = "/usr/bin/sandbox-exec"

SEATBELT_BASE_POLICY = """
(version 1)
(deny default)

; Core process operations
(allow process-exec)
(allow process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target same-sandbox))

; User preferences (needed by many CLI tools)
(allow user-preference-read)

; Basic I/O to /dev/null
(allow file-write-data
  (require-all
    (path "/dev/null")
    (vnode-type CHARACTER-DEVICE)))

; System information
(allow sysctl-read)

; IPC primitives
(allow ipc-posix-sem)
(allow ipc-posix-shm-read*)
(allow ipc-posix-shm-write-create)
(allow ipc-posix-shm-write-data)
(allow ipc-posix-shm-write-unlink)

; Terminal support (essential for shell commands)
(allow pseudo-tty)
(allow file-read* file-write* file-ioctl (literal "/dev/ptmx"))
(allow file-read* file-write* file-ioctl (regex #"^/dev/ttys[0-9]+$"))

; macOS-specific device access
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/dev/random"))
(allow file-ioctl (literal "/dev/dtracehelper"))

; Mach IPC (needed by many system services)
(allow mach-lookup)
"""

SEATBELT_NETWORK_POLICY = """
; Network access
(allow network-outbound)
(allow network-inbound)
(allow system-socket)
(allow network-bind)
"""


@lru_cache(maxsize=1)
def is_available() -> bool:
    if sys.platform != "darwin":
        return False
    if not Path(SANDBOX_EXEC_PATH).exists():
        return False
    try:
        result = subprocess.run(
            [
                SANDBOX_EXEC_PATH,
                "-p",
                "(version 1)(allow default)",
                "--",
                "/usr/bin/true",
            ],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def create_seatbelt_args(
    command: list[str],
    policy: ExecutionSandboxPolicy,
    sandbox_cwd: Path,
) -> list[str]:
    full_policy = generate_policy(policy, sandbox_cwd)
    params = generate_params(policy, sandbox_cwd)

    args = ["-p", full_policy]
    for key, value in params:
        args.append(f"-D{key}={value}")
    args.append("--")
    args.extend(command)
    return args


def generate_policy(policy: ExecutionSandboxPolicy, cwd: Path) -> str:
    full_policy = SEATBELT_BASE_POLICY

    if policy.has_full_disk_read_access():
        full_policy += "\n; Full filesystem read access\n(allow file-read*)"

    file_write_policy = generate_write_policy(policy, cwd)
    if file_write_policy:
        full_policy += "\n\n; Write access policy\n"
        full_policy += file_write_policy

    if policy.has_network_access():
        full_policy += "\n"
        full_policy += SEATBELT_NETWORK_POLICY

    full_policy += "\n\n; Darwin user cache directory\n"
    full_policy += (
        '(allow file-read* file-write* (subpath (param "DARWIN_USER_CACHE_DIR")))'
    )

    full_policy += "\n\n; Common macOS directories\n"
    full_policy += '(allow file-read* (subpath "/usr/lib"))\n'
    full_policy += '(allow file-read* (subpath "/usr/share"))\n'
    full_policy += '(allow file-read* (subpath "/System/Library"))\n'
    full_policy += '(allow file-read* (subpath "/Library/Preferences"))\n'
    full_policy += '(allow file-read* (subpath "/private/var/db"))'

    if resolve_cargo_home() is not None:
        full_policy += "\n\n; Cargo home (~/.cargo) — registry/index/git caches\n"
        full_policy += '(allow file-read* (subpath (param "CARGO_HOME")))'
        if policy.kind != "read-only":
            full_policy += '\n(allow file-write* (subpath (param "CARGO_HOME_REGISTRY")))'
            full_policy += '\n(allow file-write* (subpath (param "CARGO_HOME_GIT")))'

    return full_policy


def resolve_cargo_home() -> Path | None:
    explicit = os.environ.get("CARGO_HOME", "").strip()
    if explicit:
        return Path(explicit)
    home = os.environ.get("HOME")
    if not home:
        return None
    return Path(home) / ".cargo"


def generate_write_policy(policy: ExecutionSandboxPolicy, cwd: Path) -> str:
    if policy.has_full_disk_write_access():
        return '(allow file-write* (regex #"^/"))'

    if policy.kind == "read-only":
        return ""

    writable_roots = policy.get_writable_roots(cwd)
    if not writable_roots:
        return ""

    policies: list[str] = []
    for index, root in enumerate(writable_roots):
        root_param = f"WRITABLE_ROOT_{index}"
        if not root.read_only_subpaths:
            policies.append(f'(subpath (param "{root_param}"))')
        else:
            parts = [f'(subpath (param "{root_param}"))']
            for subpath_index, _ in enumerate(root.read_only_subpaths):
                ro_param = f"WRITABLE_ROOT_{index}_RO_{subpath_index}"
                parts.append(f'(require-not (subpath (param "{ro_param}")))')
            policies.append(f"(require-all {' '.join(parts)})")

    if not policies:
        return ""

    return "(allow file-write*\n  " + "\n  ".join(policies) + ")"


def generate_params(
    policy: ExecutionSandboxPolicy,
    cwd: Path,
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []

    writable_roots = policy.get_writable_roots(cwd)
    for index, root in enumerate(writable_roots):
        try:
            canonical = root.root.resolve()
        except OSError:
            canonical = root.root
        params.append((f"WRITABLE_ROOT_{index}", str(canonical)))

        for subpath_index, subpath in enumerate(root.read_only_subpaths):
            try:
                canonical_subpath = subpath.resolve()
            except OSError:
                canonical_subpath = subpath
            params.append(
                (f"WRITABLE_ROOT_{index}_RO_{subpath_index}", str(canonical_subpath))
            )

    cache_dir = get_darwin_user_cache_dir()
    if cache_dir is not None:
        params.append(("DARWIN_USER_CACHE_DIR", str(cache_dir)))
    else:
        home = os.environ.get("HOME")
        if home:
            params.append(("DARWIN_USER_CACHE_DIR", f"{home}/Library/Caches"))

    cargo_home = resolve_cargo_home()
    if cargo_home is not None:
        try:
            canonical_home = cargo_home.resolve()
        except OSError:
            canonical_home = cargo_home
        params.append(("CARGO_HOME_REGISTRY", str(canonical_home / "registry")))
        params.append(("CARGO_HOME_GIT", str(canonical_home / "git")))
        params.append(("CARGO_HOME", str(canonical_home)))

    return params


def get_darwin_user_cache_dir() -> Path | None:
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        import ctypes.util

        libc_path = ctypes.util.find_library("c")
        if not libc_path:
            return None
        libc = ctypes.CDLL(libc_path)
        _CS_DARWIN_USER_CACHE_DIR = 65538
        buf = ctypes.create_string_buffer(4096)
        length = libc.confstr(_CS_DARWIN_USER_CACHE_DIR, buf, len(buf))
        if length == 0:
            return None
        path = Path(buf.value.decode("utf-8"))
        try:
            return path.resolve()
        except OSError:
            return path
    except (OSError, AttributeError, ValueError):
        return None


def detect_denial(exit_code: int, stderr: str) -> bool:
    if exit_code == 0:
        return False
    denial_patterns = (
        "Operation not permitted",
        "sandbox-exec",
        "deny(",
        "Sandbox: ",
    )
    return any(pattern in stderr for pattern in denial_patterns)
