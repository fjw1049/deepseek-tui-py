"""Audit 17 defect observations. Temporary files and mocks only; no network."""

import asyncio
import importlib
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from deepseek_tui.config.loader import ConfigLoader, strip_project_security_keys
from deepseek_tui.config.models import Config
from deepseek_tui.config.providers import (
    context_window_for_model,
    register_provider_context_windows,
)
from deepseek_tui.utils import summarize_text, write_text_atomic

cli = importlib.import_module("deepseek_tui.cli.app")


async def one_shot_probes():
    client = SimpleNamespace(api_key="FIXTURE_ONLY", close=AsyncMock())
    with (
        patch("deepseek_tui.client.factory.build_llm_client", return_value=client),
        patch(
            "deepseek_tui.engine.orchestrator.Engine.create", side_effect=RuntimeError("fixture")
        ),
    ):
        try:
            await cli._run_one_shot_async(Config(), "fixture")
        except RuntimeError:
            pass
    assert client.close.await_count == 0
    from deepseek_tui.engine.events import ErrorEvent

    engine = SimpleNamespace(shutdown=AsyncMock())

    async def create(handle, *_args, **_kwargs):
        async def run():
            await handle.emit(ErrorEvent(message="fixture failure"))
            await asyncio.Event().wait()

        engine.run = run
        return engine

    with (
        patch("deepseek_tui.client.factory.build_llm_client", return_value=client),
        patch("deepseek_tui.engine.orchestrator.Engine.create", side_effect=create),
        patch("deepseek_tui.cli.app.typer.echo"),
    ):
        result = await cli._run_one_shot_async(Config(), "fixture")
    assert result is None
    return {"startup_failure_client_close_count": 0, "error_event_returns_normally": True}


def run(root):
    result = {}
    home = root / "home"
    workspace = root / "workspace"
    other = root / "other"
    for path in (home, workspace, other):
        path.mkdir()
    config_path = home / "config.toml"
    config_path.write_text('model="base"\n[profiles.fast]\nmodel="fast"\n')
    os.chdir(workspace)
    with (
        patch.dict(os.environ, {"DEEPSEEK_HOME": str(home)}, clear=True),
        patch.object(Path, "home", return_value=home),
    ):
        loader = ConfigLoader()
        with patch.dict(os.environ, {"DEEPSEEK_TUI_PROFILE": "fast"}):
            loaded = loader.load()
        assert loaded.profile == "fast" and loaded.model == "base"
        result["env_profile"] = {"selected": loaded.profile, "actual_model": loaded.model}
        (workspace / "deepseek-tui.toml").write_text('model="project"\n')
        loaded = loader.load(no_project_config=True)
        assert loaded.model == "project"
        result["no_project_config"] = {"project_still_applied": True}
        loaded = loader.load(workspace=other)
        assert loaded.model == "project"
        result["workspace_discovery"] = {"cwd_project_used_for_other_workspace": True}
        (workspace / "deepseek-tui.toml").unlink()
        config_path.write_text('provider="deepseek"\napi_key="FIXTURE_ONLY"\n')
        (workspace / ".deepseek").mkdir()
        project_config = workspace / ".deepseek/config.toml"
        project_config.write_text('provider="openai"\n')
        loaded = loader.load()
        assert (
            loaded.provider == "openai"
            and loaded.effective_provider_config().api_key == "FIXTURE_ONLY"
        )
        result["provider_key_scope"] = {"provider_changed": True, "old_key_carried": True}
        project_config.unlink()
        base = Config.model_validate(
            {"ui": {"locale": "en"}, "profiles": {"p": {"ui": {"show_thinking": False}}}}
        )
        loaded = loader._merge_profile(base, "p")
        assert loaded.ui.locale == "zh"
        result["partial_profile"] = {"base_locale": "en", "merged_locale": loaded.ui.locale}
        raw = {
            "automation": {"email": {"smtp_host": "fixture.invalid", "to_addr": "fixture@invalid"}}
        }
        stripped = strip_project_security_keys(raw, workspace / "config.toml")
        assert stripped == raw
        result["project_delivery_config"] = {"smtp_host_and_recipient_survive_filter": True}
        a = Config.model_validate(
            {"providers": {"a": {"model": "custom-fixture", "context_window": 8192}}}
        )
        b = Config.model_validate(
            {"providers": {"b": {"model": "custom-fixture", "context_window": 65536}}}
        )
        register_provider_context_windows(a)
        first = context_window_for_model("custom-fixture")
        register_provider_context_windows(b)
        second = context_window_for_model("custom-fixture")
        assert (first, second) == (8192, 65536)
        result["global_context_map"] = {"before": first, "after_other_config": second}
        runner = CliRunner()
        seen = []
        with (
            patch.object(cli, "_load_config", return_value=Config()),
            patch.object(cli, "_launch_tui", side_effect=seen.append),
            patch("deepseek_tui.config.layout.ensure_user_home_layout"),
            patch("deepseek_tui.utils.setup_logging"),
            patch("deepseek_tui.tools.runtime.prune_older_than"),
        ):
            call = runner.invoke(
                cli.app, ["--api-key", "FIXTURE_ONLY", "--approval-policy", "never"]
            )
        assert (
            call.exit_code == 0
            and seen[0].api_key is None
            and seen[0].approval_policy == "on-request"
        )
        result["cli_overrides"] = {"api_key_ignored": True, "approval_policy_ignored": True}
        with patch.object(cli, "_load_config", return_value=Config(api_key="FIXTURE_ONLY")):
            call = runner.invoke(cli.app, ["config", "show"])
        assert "FIXTURE_ONLY" in call.output
        result["config_display"] = {"fixture_key_printed": True}
        result["one_shot"] = asyncio.run(one_shot_probes())
        handles = []
        original = tempfile.mkstemp

        def tracked(*args, **kwargs):
            fd, path = original(*args, **kwargs)
            handles.append(fd)
            return fd, path

        target = root / "existing"
        target.write_text("old")
        with (
            patch("deepseek_tui.utils.tempfile.mkstemp", side_effect=tracked),
            patch("deepseek_tui.utils.os.fchmod", side_effect=OSError("fixture")),
        ):
            try:
                write_text_atomic(target, "new")
            except OSError:
                pass
        try:
            os.fstat(handles[0])
            result["atomic_writer"] = {"descriptor_open_after_fchmod_error": True}
        finally:
            os.close(handles[0])
        assert target.read_text() == "old"
        result["summary_limit"] = {
            "input_length": 4,
            "limit": 5,
            "output": summarize_text("abcd", 5),
        }
        assert result["summary_limit"]["output"] == "ab..."
    return result


if __name__ == "__main__":
    original_cwd = Path.cwd()
    try:
        with tempfile.TemporaryDirectory(prefix="audit17-") as directory:
            data = run(Path(directory))
    finally:
        os.chdir(original_cwd)
    print(json.dumps(data, ensure_ascii=False, indent=2))
