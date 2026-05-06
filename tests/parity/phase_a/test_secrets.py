"""Parity tests for the secrets module.

Each named test mirrors a `#[test]` block in
``crates/secrets/src/lib.rs::tests`` (lines 446-676 of the original
Rust source).

Cross-reference (Rust test name → Python test name):

* in_memory_store_round_trips → test_in_memory_store_round_trips
* resolve_prefers_keyring_over_env → test_resolve_prefers_keyring_over_env
* resolve_falls_back_to_env_when_keyring_empty → ...same suffix...
* resolve_returns_none_when_both_layers_empty → ...same suffix...
* resolve_treats_blank_keyring_value_as_unset → ...same suffix...
* nvidia_env_aliases_resolve → test_nvidia_env_aliases_resolve
* file_store_round_trips_with_secure_perms → ...same suffix...
* file_store_rejects_world_readable_file → ...same suffix...
* file_store_set_does_not_clobber_secrets_when_perms_are_bad
  → test_file_store_set_does_not_clobber_when_perms_bad
* file_store_delete_does_not_clobber_secrets_when_perms_are_bad
  → test_file_store_delete_does_not_clobber_when_perms_bad
* file_store_set_does_not_clobber_secrets_when_json_is_corrupt
  → test_file_store_set_does_not_clobber_when_json_corrupt
* file_store_set_still_creates_file_when_missing → ...same suffix...
* file_store_default_path_uses_home → test_file_store_default_path_uses_home
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from deepseek_tui.secrets import (
    FileKeyringStore,
    InMemoryKeyringStore,
    InsecurePermissionsError,
    Secrets,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_IS_UNIX = sys.platform != "win32"


# ---------------------------------------------------------------------------
# env management — mirrors `env_lock()` + `clear_known_envs()` in Rust.
# ---------------------------------------------------------------------------


_KNOWN_ENVS = (
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "NOVITA_API_KEY",
    "NVIDIA_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clear_known_envs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip every provider env var before each test, restore after."""
    for var in _KNOWN_ENVS:
        monkeypatch.delenv(var, raising=False)
    yield


# ---------------------------------------------------------------------------
# 1. In-memory store round-trip (Rust lib.rs:447-461)
# ---------------------------------------------------------------------------


def test_in_memory_store_round_trips() -> None:
    store = InMemoryKeyringStore()
    assert store.get("deepseek") is None
    store.set("deepseek", "sk-test")
    assert store.get("deepseek") == "sk-test"
    store.set("deepseek", "sk-replaced")
    assert store.get("deepseek") == "sk-replaced"
    store.delete("deepseek")
    assert store.get("deepseek") is None
    # Deleting an absent key is a no-op.
    store.delete("missing")


# ---------------------------------------------------------------------------
# 2. Resolve precedence (Rust lib.rs:463-498)
# ---------------------------------------------------------------------------


def test_resolve_prefers_keyring_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    store = InMemoryKeyringStore()
    store.set("deepseek", "ring-key")
    secrets = Secrets(store)
    assert secrets.resolve("deepseek") == "ring-key"


def test_resolve_falls_back_to_env_when_keyring_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-fallback")
    secrets = Secrets(InMemoryKeyringStore())
    assert secrets.resolve("deepseek") == "env-fallback"


def test_resolve_returns_none_when_both_layers_empty() -> None:
    secrets = Secrets(InMemoryKeyringStore())
    assert secrets.resolve("deepseek") is None


def test_resolve_treats_blank_keyring_value_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-real")
    store = InMemoryKeyringStore()
    store.set("deepseek", "   ")  # whitespace only → treated as unset
    secrets = Secrets(store)
    assert secrets.resolve("deepseek") == "env-real"


# ---------------------------------------------------------------------------
# 3. NVIDIA env aliases (Rust lib.rs:516-526)
# ---------------------------------------------------------------------------


def test_nvidia_env_aliases_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-key")
    secrets = Secrets(InMemoryKeyringStore())
    assert secrets.resolve("nvidia-nim") == "nim-key"
    assert secrets.resolve("nvidia") == "nim-key"


def test_nvidia_falls_back_to_deepseek_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rust documents this fallback at lib.rs:398-402."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    secrets = Secrets(InMemoryKeyringStore())
    assert secrets.resolve("nvidia-nim") == "ds-key"


def test_nvidia_prefers_nvidia_api_key_over_nim_over_deepseek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order check: NVIDIA_API_KEY > NVIDIA_NIM_API_KEY > DEEPSEEK_API_KEY."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    secrets = Secrets(InMemoryKeyringStore())
    assert secrets.resolve("nvidia") == "nv"


# ---------------------------------------------------------------------------
# 4. File-store happy path (Rust lib.rs:528-553)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _IS_UNIX, reason="Unix-only permission semantics")
def test_file_store_round_trips_with_secure_perms(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "secrets.json"
    store = FileKeyringStore(path)

    assert store.get("deepseek") is None
    store.set("deepseek", "sk-disk")
    assert store.get("deepseek") == "sk-disk"

    mode = path.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {mode:o}"

    store.set("openrouter", "or-disk")
    assert store.get("openrouter") == "or-disk"
    # First entry must still be intact.
    assert store.get("deepseek") == "sk-disk"

    store.delete("deepseek")
    assert store.get("deepseek") is None


@pytest.mark.skipif(not _IS_UNIX, reason="Unix-only permission semantics")
def test_file_store_rejects_world_readable_file(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text('{"entries": {"deepseek": "leak"}}')
    os.chmod(path, 0o644)

    store = FileKeyringStore(path)
    with pytest.raises(InsecurePermissionsError):
        store.get("deepseek")


# ---------------------------------------------------------------------------
# 5. File-store #281 invariants (Rust lib.rs:579-625)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _IS_UNIX, reason="Unix-only permission semantics")
def test_file_store_set_does_not_clobber_when_perms_bad(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    original = '{"entries":{"deepseek":"sk-keep","nvidia":"nv-keep"}}'
    path.write_text(original)
    os.chmod(path, 0o644)

    store = FileKeyringStore(path)
    with pytest.raises(InsecurePermissionsError):
        store.set("openrouter", "or-new")
    # File must still hold the original payload.
    assert path.read_text() == original


@pytest.mark.skipif(not _IS_UNIX, reason="Unix-only permission semantics")
def test_file_store_delete_does_not_clobber_when_perms_bad(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    original = '{"entries":{"deepseek":"sk-keep","nvidia":"nv-keep"}}'
    path.write_text(original)
    os.chmod(path, 0o644)

    store = FileKeyringStore(path)
    with pytest.raises(InsecurePermissionsError):
        store.delete("nvidia")
    assert path.read_text() == original


# ---------------------------------------------------------------------------
# 6. File-store corrupt-JSON behaviour (Rust lib.rs:627-650)
# ---------------------------------------------------------------------------


def test_file_store_set_does_not_clobber_when_json_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text("{ this is not valid json")
    if _IS_UNIX:
        os.chmod(path, 0o600)

    from deepseek_tui.secrets import SecretsError

    store = FileKeyringStore(path)
    with pytest.raises(SecretsError):
        store.set("deepseek", "sk-new")
    # File untouched.
    assert path.read_text() == "{ this is not valid json"


# ---------------------------------------------------------------------------
# 7. File-store auto-create on first write (Rust lib.rs:652-664)
# ---------------------------------------------------------------------------


def test_file_store_set_still_creates_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "secrets.json"
    store = FileKeyringStore(path)
    store.set("deepseek", "sk-fresh")
    assert store.get("deepseek") == "sk-fresh"


# ---------------------------------------------------------------------------
# 8. Default-path shape (Rust lib.rs:666-676)
# ---------------------------------------------------------------------------


def test_file_store_default_path_uses_home() -> None:
    path = FileKeyringStore.default_path()
    assert (
        str(path).endswith("secrets/secrets.json")
        or str(path).endswith("secrets\\secrets.json")
    ), f"unexpected default path: {path}"


# ---------------------------------------------------------------------------
# Extra Python-side coverage (not in Rust but useful for regression).
# ---------------------------------------------------------------------------


def test_file_store_writes_well_formed_json(tmp_path: Path) -> None:
    """Sanity: the on-disk format matches the schema FileSecretsBlob expects."""
    path = tmp_path / "secrets.json"
    store = FileKeyringStore(path)
    store.set("deepseek", "sk-1")
    store.set("openrouter", "or-1")

    blob = json.loads(path.read_text())
    assert blob == {
        "entries": {"deepseek": "sk-1", "openrouter": "or-1"},
    }


def test_env_for_unknown_provider_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown providers must not get a `{NAME}_API_KEY` guess."""
    from deepseek_tui.secrets import env_for

    # Even if a "matching" env exists, env_for should return None for
    # unknown providers — Rust closes the door at lib.rs:404.
    monkeypatch.setenv("WEIRD_API_KEY", "should-not-leak")
    assert env_for("weird") is None


def test_secrets_manager_falls_back_to_config_toml() -> None:
    """SecretsManager adds the third (config.toml) tier on top of Secrets."""
    from deepseek_tui.config.models import Config, ProviderConfig
    from deepseek_tui.secrets import SecretsManager

    config = Config(providers={"deepseek": ProviderConfig(api_key="config-key")})
    manager = SecretsManager(Secrets(InMemoryKeyringStore()))
    assert manager.resolve_api_key(config) == "config-key"


def test_secrets_manager_keyring_wins_over_config_toml() -> None:
    """The new precedence: keyring beats the config.toml fallback."""
    from deepseek_tui.config.models import Config, ProviderConfig
    from deepseek_tui.secrets import SecretsManager

    store = InMemoryKeyringStore()
    store.set("deepseek", "ring-key")
    config = Config(providers={"deepseek": ProviderConfig(api_key="config-key")})
    manager = SecretsManager(Secrets(store))
    assert manager.resolve_api_key(config) == "ring-key"


def test_secrets_manager_env_wins_over_config_toml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new precedence: env beats the config.toml fallback."""
    from deepseek_tui.config.models import Config, ProviderConfig
    from deepseek_tui.secrets import SecretsManager

    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    config = Config(providers={"deepseek": ProviderConfig(api_key="config-key")})
    manager = SecretsManager(Secrets(InMemoryKeyringStore()))
    assert manager.resolve_api_key(config) == "env-key"
