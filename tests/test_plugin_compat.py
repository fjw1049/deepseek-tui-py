"""Cross-ecosystem plugin compatibility tests - tool-name mapping, hook
condition firing, and vendor layout preservation."""

from __future__ import annotations

import json
from pathlib import Path

from deepseek_tui.config.models import LifecycleHookEntry
from deepseek_tui.integrations.hooks import HookContext, HookExecutor
from deepseek_tui.integrations.plugin_compat import (
    map_tool_matcher,
    matcher_to_condition,
)
from deepseek_tui.integrations.plugins import (
    collect_contributions,
    discover_plugins,
    install_plugin,
    set_plugin_trusted,
)


def test_map_tool_matcher() -> None:
    assert map_tool_matcher("Edit|Write") == ["edit_file", "write_file"]
    assert map_tool_matcher("Skill") == ["load_skill"]
    assert map_tool_matcher("Bash|Read") == ["exec_shell", "read_file"]
    assert map_tool_matcher("MultiEdit") == ["edit_file"]
    # All-tools sentinels -> no filter.
    assert map_tool_matcher("") == []
    assert map_tool_matcher("*") == []
    assert map_tool_matcher(".*") == []
    # Unknown / already-native tokens pass through lowercased.
    assert map_tool_matcher("read_file") == ["read_file"]
    assert map_tool_matcher("Foo") == ["foo"]


def test_matcher_to_condition() -> None:
    assert matcher_to_condition("Edit|Write") == {
        "type": "tool_name_any",
        "names": ["edit_file", "write_file"],
    }
    assert matcher_to_condition("") is None
    assert matcher_to_condition("*") is None


def test_tool_name_any_condition_fires() -> None:
    runner = object.__new__(HookExecutor)
    hook = LifecycleHookEntry(
        event="tool_call_before",
        command="x",
        condition=matcher_to_condition("Edit|Write"),
    )
    fire = lambda tool: HookExecutor._matches_condition(  # noqa: E731
        runner, hook, HookContext(tool_name=tool)
    )
    assert fire("edit_file") is True
    assert fire("write_file") is True
    assert fire("read_file") is False


def _make_codebuddy_plugin_with_hooks(root: Path, name: str = "ppt") -> Path:
    plugin = root / name
    (plugin / ".codebuddy-plugin").mkdir(parents=True)
    (plugin / "hooks").mkdir()
    (plugin / "skills" / "s").mkdir(parents=True)
    (plugin / "skills" / "s" / "SKILL.md").write_text(
        "---\nname: s\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    (plugin / ".codebuddy-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "1.0.0",
                "skills": ["./skills/s"],
                "hooks": "./hooks/hooks.json",
            }
        ),
        encoding="utf-8",
    )
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'node "${CODEBUDDY_PLUGIN_ROOT}/x.js" '
                                    '"${CODEBUDDY_PROJECT_DIR}"',
                                }
                            ]
                        }
                    ],
                    "PostToolUse": [
                        {
                            "matcher": "Edit|Write",
                            "hooks": [{"type": "command", "command": "echo hi"}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return plugin


def test_install_preserves_vendor_layout(tmp_path: Path) -> None:
    source = _make_codebuddy_plugin_with_hooks(tmp_path / "src")
    plugins_dir = tmp_path / "installed"
    outcome, _ = install_plugin(str(source), plugins_dir, trust=True)
    assert outcome.name == "INSTALLED"
    dest = plugins_dir / "ppt"
    # Installed copy keeps the vendor layout; runtime adapters map at read time.
    assert (dest / ".codebuddy-plugin" / "plugin.json").is_file()
    assert not (dest / ".claude-plugin").exists()
    # Original source is untouched.
    assert (source / ".codebuddy-plugin" / "plugin.json").is_file()
    assert not (source / ".claude-plugin").exists()
    src_hooks = json.loads((source / "hooks" / "hooks.json").read_text())
    assert src_hooks["hooks"]["PostToolUse"][0]["matcher"] == "Edit|Write"


def test_foreign_hooks_load_with_mapped_condition(tmp_path: Path) -> None:
    _make_codebuddy_plugin_with_hooks(tmp_path)
    set_plugin_trusted("ppt", True, plugins_dir=tmp_path)
    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    tool_hooks = [
        h for h in contribs.hook_entries if h.event == "tool_call_after"
    ]
    assert tool_hooks
    assert tool_hooks[0].condition == {
        "type": "tool_name_any",
        "names": ["edit_file", "write_file"],
    }
