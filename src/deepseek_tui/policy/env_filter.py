"""Environment scrubbing for child processes spawned on the model's behalf.

Shell commands and MCP stdio servers inherit ``os.environ`` by default,
which leaks credentials (``DEEPSEEK_API_KEY``, ``GITHUB_TOKEN``, ...) to
anything the model runs — a plain ``printenv`` reads them straight back
out. :func:`build_child_env` builds the child environment from a scrubbed
copy of the process env: entries whose name matches a secret pattern are
dropped, while explicitly declared overrides (tool env, mcp.json ``env``)
pass through untouched.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

logger = logging.getLogger(__name__)

# Case-insensitive suffix match on the variable name. Suffixes (rather
# than substrings) keep normal variables like ``PATH``, ``HOME``,
# ``LANG`` or ``SSH_AUTH_SOCK`` untouched.
_SECRET_SUFFIXES = (
    "_API_KEY",
    "_TOKEN",
    "_SECRET",
    "_PASSWORD",
    "_ACCESS_KEY",
    "_ACCESS_KEY_ID",
    "_PRIVATE_KEY",
    "_CREDENTIALS",
)


def is_secret_env_name(name: str) -> bool:
    """True if an env var name looks like it carries a credential."""
    upper = name.upper()
    return any(upper.endswith(suffix) for suffix in _SECRET_SUFFIXES)


def build_child_env(
    overrides: Mapping[str, str] | None = None,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a scrubbed child-process environment.

    Starts from ``base`` (defaults to ``os.environ``), drops entries whose
    name matches a secret pattern, then applies ``overrides`` verbatim —
    explicitly declared env vars are always allowed through.
    """
    source = os.environ if base is None else base
    env = {key: value for key, value in source.items() if not is_secret_env_name(key)}
    dropped = len(source) - len(env)
    if dropped:
        logger.debug(
            "scrubbed %d secret-like env var(s) from child environment", dropped
        )
    if overrides:
        env.update(overrides)
    return env
