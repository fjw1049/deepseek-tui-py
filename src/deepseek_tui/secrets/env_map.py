"""Provider-name → environment-variable mapping.

Mirrors `env_for` in
`docs/DeepSeek-TUI-main/crates/secrets/src/lib.rs:393-415`.

The Rust implementation hard-codes a small candidate list per provider
(`deepseek`, `openrouter`, `novita`, `nvidia`/`nvidia-nim`/`nvidia_nim`/
`nim`, `openai`). Unknown providers return ``None`` — the caller does NOT
get a generic ``{PROVIDER}_API_KEY`` guess.

Empty / whitespace-only values are treated as unset.
"""

from __future__ import annotations

import os

__all__ = ["env_for"]


# Canonical provider name -> ordered candidate env var list.
# Order matters: the first non-empty match wins.
_PROVIDER_ENV_CANDIDATES: dict[str, tuple[str, ...]] = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "novita": ("NOVITA_API_KEY",),
    # NVIDIA NIM falls back to DEEPSEEK_API_KEY because the catalog
    # endpoint accepts the same DeepSeek-issued key when no dedicated
    # NVIDIA token is set. This mirrors pre-v0.7 behaviour.
    "nvidia": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nvidia-nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nvidia_nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "nim": ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "DEEPSEEK_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
}


def env_for(name: str) -> str | None:
    """Return the API key for a provider from the environment, or None.

    Looks up `name.lower()` in the canonical candidate list. If no list
    matches the provider name, returns ``None`` *without* attempting a
    `{NAME}_API_KEY` guess — this is intentional: the Rust source is
    explicit about closing the door on unknown providers, and a wrong
    guess would silently leak whatever happened to be set.
    """
    candidates = _PROVIDER_ENV_CANDIDATES.get(name.lower())
    if candidates is None:
        return None
    for var in candidates:
        value = os.environ.get(var)
        if value is not None and value.strip():
            return value
    return None
