from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.plugins.grants import (
    grant_execution,
    has_execution_grant,
    read_grant,
    revoke_grant,
)
from deepseek_tui.plugins.identity import (
    PluginIdentityError,
    content_fingerprint,
    is_safe_plugin_id,
    validate_plugin_id,
)
from deepseek_tui.plugins.store import read_derived, write_derived
from deepseek_tui.tools.registry import ToolRegistry


def test_plugin_id_rejects_traversal() -> None:
    assert is_safe_plugin_id("demo-plugin")
    with pytest.raises(PluginIdentityError):
        validate_plugin_id("../escape")
    with pytest.raises(PluginIdentityError):
        validate_plugin_id("a/b")


def test_content_fingerprint_changes_with_file(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    root.mkdir()
    target = root / "SKILL.md"
    target.write_text("one", encoding="utf-8")
    first = content_fingerprint(root)
    target.write_text("two", encoding="utf-8")
    assert content_fingerprint(root) != first


def test_grant_is_digest_bound(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    grant_execution("demo", "fp:abc")
    assert has_execution_grant("demo", "fp:abc", "hooks.execute")
    assert not has_execution_grant("demo", "fp:other", "hooks.execute")
    assert read_grant("demo", "fp:abc") is not None
    assert revoke_grant("demo", "fp:abc") == 1
    assert read_grant("demo", "fp:abc") is None


def test_register_exclusive_rejects_collision() -> None:
    from deepseek_tui.tools.knowledge import NoteTool

    registry = ToolRegistry()
    tool = NoteTool()
    registry.register_exclusive(tool)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_exclusive(tool)


def test_write_derived_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    from deepseek_tui.plugins.model import (
        CompatibilityReport,
        CompatibilityStatus,
        DerivedPlugin,
        SourceProvenance,
    )

    plugin = DerivedPlugin(
        1,
        "demo",
        "1.0.0",
        "desc",
        SourceProvenance("local", str(tmp_path), "sha256:" + ("a" * 64)),
        (),
        (),
        CompatibilityReport(CompatibilityStatus.NATIVE, "claude", 1),
    )
    path = write_derived(plugin)
    assert path.is_file()
    assert read_derived(plugin.source.digest, "claude") is not None
