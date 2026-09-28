"""Config/CLI boundaries, failure cleanup and resource budgets."""

import asyncio
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from deepseek_tui.config.loader import ENV_TO_FIELD, ConfigLoader
from deepseek_tui.config.models import Config
from deepseek_tui.utils import summarize_text, write_text_atomic

cli = importlib.import_module("deepseek_tui.cli.app")


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    for key in (*ENV_TO_FIELD, "DEEPSEEK_CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DEEPSEEK_HOME", str(home / ".deepseek"))
    monkeypatch.chdir(workspace)
    return home, workspace


def user_config(home, text):
    path = home / ".deepseek/config.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return path


def test_discovery_uses_requested_workspace(config_env, tmp_path):
    home, workspace = config_env
    user_config(home, 'model="user"\n')
    (workspace / "deepseek-tui.toml").write_text('model="wrong"\n')
    other = tmp_path / "other"
    other.mkdir()
    (other / "deepseek-tui.toml").write_text('model="right"\napproval_policy="never"\n')
    loaded = ConfigLoader().load(workspace=other)
    assert loaded.model == "right"
    assert loaded.approval_policy == "on-request"


def test_disable_all_implicit_project_sources(config_env):
    home, workspace = config_env
    user_config(home, 'model="user"\n')
    (workspace / "deepseek-tui.toml").write_text('model="root"\n')
    (workspace / ".env").write_text("DEEPSEEK_MODEL=dotenv\n")
    (workspace / ".deepseek").mkdir()
    (workspace / ".deepseek/config.toml").write_text('model="overlay"\n')
    assert ConfigLoader().load(no_project_config=True).model == "user"


def test_explicit_other_workspace_remains_untrusted(config_env, tmp_path):
    _, _workspace = config_env
    other = tmp_path / "other"
    other.mkdir()
    path = other / "custom.toml"
    path.write_text('model="custom"\napproval_policy="never"\n')
    loaded = ConfigLoader().load(config_path=path, workspace=other, no_project_config=True)
    assert loaded.model == "custom"
    assert loaded.approval_policy == "on-request"


def test_provider_switch_drops_old_key_and_endpoint(config_env):
    home, workspace = config_env
    user_config(home, 'api_key="FIXTURE_ONLY"\nbase_url="https://old.invalid"\n')
    (workspace / "deepseek-tui.toml").write_text(
        'provider="openai"\n[automation.email]\nsmtp_host="bad.invalid"\n'
    )
    cfg = ConfigLoader().load()
    assert cfg.provider == "openai"
    assert cfg.api_key is None and cfg.base_url is None
    assert cfg.automation.email.smtp_host is None


def test_env_profile_and_partial_nested_override(config_env, monkeypatch):
    home, _ = config_env
    user_config(
        home,
        'model="base"\n[ui]\nlocale="en"\n[profiles.fast]\nmodel="fast"\n[profiles.fast.ui]\nshow_thinking=false\n',
    )
    monkeypatch.setenv("DEEPSEEK_TUI_PROFILE", "fast")
    cfg = ConfigLoader().load()
    assert cfg.profile == "fast" and cfg.model == "fast"
    assert cfg.ui.locale == "en" and cfg.ui.show_thinking is False


def test_profile_cli_selector_beats_environment(config_env, monkeypatch):
    home, _ = config_env
    user_config(home, '[profiles.a]\nmodel="A"\n[profiles.b]\nmodel="B"\n')
    monkeypatch.setenv("DEEPSEEK_TUI_PROFILE", "b")
    cfg = ConfigLoader().load(profile_name="a")
    assert cfg.profile == "a" and cfg.model == "A"


def test_cli_overrides_before_managed_policy(config_env, monkeypatch):
    home, _ = config_env
    managed = home / "managed.toml"
    managed.write_text('approval_policy="on-request"\n')
    user_config(home, f'managed_config_path="{managed}"\n')
    seen = []
    monkeypatch.setattr(cli, "_launch_tui", seen.append)
    monkeypatch.setattr("deepseek_tui.utils.setup_logging", lambda *a, **kw: None)
    result = CliRunner().invoke(
        cli.app, ["--api-key", "FIXTURE_ONLY", "--approval-policy", "never"]
    )
    assert result.exit_code == 0, result.output
    assert seen[0].api_key == "FIXTURE_ONLY"
    assert seen[0].approval_policy == "on-request"


def test_global_flags_reach_subcommands(config_env):
    result = CliRunner().invoke(cli.app, ["--model", "chosen", "config", "get", "model"])
    assert result.exit_code == 0 and result.output.strip() == "chosen"


def test_unsupported_output_mode_fails_explicitly(config_env):
    result = CliRunner().invoke(cli.app, ["--output-mode", "json", "version"])
    assert result.exit_code != 0


def test_profile_writes_and_secret_redaction(config_env):
    home, _ = config_env
    path = user_config(home, 'model="base"\n[profiles.fast]\nmodel="old"\n')
    runner = CliRunner()
    call = runner.invoke(
        cli.app, ["--config", str(path), "config", "set", "model", "new", "--profile", "fast"]
    )
    assert call.exit_code == 0, call.output
    cfg = ConfigLoader().load(config_path=path, profile_name="fast")
    assert cfg.model == "new"
    assert ConfigLoader().load(config_path=path).model == "base"
    call = runner.invoke(
        cli.app,
        ["--config", str(path), "config", "set", "providers.deepseek.api_key", "FIXTURE_ONLY"],
    )
    assert call.exit_code == 0 and "FIXTURE_ONLY" not in call.output
    for args in [
        ["config", "show"],
        ["config", "list"],
        ["config", "get", "providers"],
        ["config", "get", "providers.deepseek.api_key"],
    ]:
        call = runner.invoke(cli.app, ["--config", str(path), *args])
        assert call.exit_code == 0 and "FIXTURE_ONLY" not in call.output
    call = runner.invoke(
        cli.app,
        ["--config", str(path), "config", "get", "providers.deepseek.api_key", "--show-secrets"],
    )
    assert call.exit_code == 0 and "FIXTURE_ONLY" in call.output


async def test_one_shot_create_failure_closes_client(monkeypatch):
    client = SimpleNamespace(api_key="fixture", close=AsyncMock())
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda _: client)
    monkeypatch.setattr(
        "deepseek_tui.engine.orchestrator.Engine.create",
        AsyncMock(side_effect=RuntimeError("startup")),
    )
    with pytest.raises(RuntimeError, match="startup"):
        await cli._run_one_shot_async(Config(), "hello")
    client.close.assert_awaited_once()


@pytest.mark.parametrize("event_kind", ["error", "failed", "crash", "success"])
async def test_one_shot_outcome_and_cleanup(monkeypatch, event_kind):
    from deepseek_tui.engine.events import ErrorEvent, TurnCompleteEvent

    client = SimpleNamespace(api_key="fixture", close=AsyncMock())
    engine = SimpleNamespace(shutdown=AsyncMock(side_effect=client.close))

    async def create(handle, *_a, **_kw):
        async def run():
            if event_kind == "crash":
                raise RuntimeError("run failure")
            if event_kind == "error":
                await handle.emit(ErrorEvent(message="fixture failure"))
            else:
                await handle.emit(
                    TurnCompleteEvent(assistant_message=None, success=event_kind == "success")
                )
            await asyncio.Event().wait()

        engine.run = run
        return engine

    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda _: client)
    monkeypatch.setattr("deepseek_tui.engine.orchestrator.Engine.create", create)
    if event_kind == "success":
        await asyncio.wait_for(cli._run_one_shot_async(Config(), "hello"), 2)
    else:
        with pytest.raises((RuntimeError, cli.typer.Exit)):
            await asyncio.wait_for(cli._run_one_shot_async(Config(), "hello"), 2)
    engine.shutdown.assert_awaited_once()
    client.close.assert_awaited_once()


def test_atomic_writer_closes_fd_on_chmod_failure(tmp_path, monkeypatch):
    import tempfile

    path = tmp_path / "file"
    path.write_text("old")
    descriptors = []
    original = tempfile.mkstemp

    def track(*a, **kw):
        fd, name = original(*a, **kw)
        descriptors.append(fd)
        return fd, name

    def fail(*_):
        raise OSError("mode failure")

    monkeypatch.setattr(tempfile, "mkstemp", track)
    monkeypatch.setattr(os, "fchmod", fail)
    with pytest.raises(OSError, match="mode failure"):
        write_text_atomic(path, "new")
    try:
        with pytest.raises(OSError):
            os.fstat(descriptors[0])
    finally:
        try:
            os.close(descriptors[0])
        except OSError:
            pass
    assert path.read_text() == "old"


@pytest.mark.parametrize(
    "text,limit,expected",
    [("abcd", 5, "abcd"), ("abcdef", 5, "ab..."), ("abc", 0, ""), ("abcd", 2, "..")],
)
def test_summary_budget(text, limit, expected):
    assert summarize_text(text, limit) == expected


def test_tail_log_bounded_and_utf8(tmp_path, monkeypatch):
    import deepseek_tui.utils as utils

    path = tmp_path / "log"
    path.write_bytes(b"x" * 2000000 + b"\n" + "最后\n".encode())
    monkeypatch.setattr(utils, "current_log_path", lambda: path)

    def forbidden(*_, **__):
        raise AssertionError("unbounded read")

    monkeypatch.setattr(Path, "read_text", forbidden)
    assert utils.tail_log(1) == ["最后"]
    assert utils.tail_log(0) == []


def test_configured_budgets_are_provider_scoped(config_env):
    from deepseek_tui.config.providers import configured_context_window

    cfg = Config.model_validate(
        {
            "provider": "a",
            "providers": {
                "a": {"model": "same", "context_window": 8192},
                "b": {"model": "same", "context_window": 65536},
            },
        }
    )
    assert configured_context_window("same", cfg) == 8192
    assert configured_context_window("b::same", cfg) == 65536
    cfg.providers["a"].context_windows["gpt-4o"] = 4096
    assert configured_context_window("gpt-4o", cfg) == 4096
    # A separately loaded file must not affect either route.
    ConfigLoader().load()
    assert configured_context_window("same", cfg) == 8192


async def test_two_engines_keep_budget_snapshots(config_env):
    from deepseek_tui.config.models import FeatureConfig, ProviderConfig
    from deepseek_tui.engine.context import context_input_budget
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine

    _, workspace = config_env
    configs = [
        Config(
            provider="custom",
            providers={"custom": ProviderConfig(model="same", context_window=window)},
            features=FeatureConfig(mcp=False, plugins=False, tasks=False, subagents=False),
        )
        for window in (8192, 65536)
    ]
    engines = []
    try:
        for cfg in configs:
            engines.append(
                await Engine.create(
                    EngineHandle(),
                    AsyncMock(),
                    config=cfg,
                    default_model="same",
                    working_directory=workspace,
                )
            )
        configs[0].providers["custom"].context_window = 1000000
        assert [e.context_breakdown()["window"] for e in engines] == [8192, 65536]
        assert context_input_budget("same", 1024, engines[0].turn_loop.model_config) < 8192
        engines[0].set_model_route(AsyncMock(), configs[1], "same")
        assert engines[0].context_breakdown()["window"] == 65536
    finally:
        for engine in engines:
            await engine.shutdown()


def test_thread_metadata_obeys_runtime_lease(config_env):
    from datetime import datetime, timezone

    from deepseek_tui.server.threads.models import ThreadRecord
    from deepseek_tui.workspace.project_lease import ThreadLease

    _, workspace = config_env
    store = cli._thread_store()
    now = datetime.now(timezone.utc)
    store.save_thread(
        ThreadRecord(
            id="fixture", created_at=now, updated_at=now, model="fixture", workspace=str(workspace)
        )
    )
    lease = ThreadLease("fixture")
    assert lease.acquire_blocking(nonblocking=True)
    try:
        result = CliRunner().invoke(cli.app, ["thread", "archive", "fixture"])
        assert result.exit_code == 1 and "in use" in result.output
        assert not store.load_thread("fixture").archived
    finally:
        lease.release()
    result = CliRunner().invoke(cli.app, ["thread", "set-name", "fixture", "renamed"])
    assert result.exit_code == 0, result.output
    assert store.load_thread("fixture").title == "renamed"


def test_mcp_start_error_still_stops(config_env, monkeypatch):
    manager = SimpleNamespace(
        start_all=AsyncMock(side_effect=RuntimeError("start")), stop_all=AsyncMock()
    )
    monkeypatch.setattr("deepseek_tui.mcp.manager.McpManager", lambda *a, **kw: manager)
    call = CliRunner().invoke(cli.app, ["mcp", "connect"])
    assert call.exit_code != 0
    manager.stop_all.assert_awaited_once()


@pytest.mark.parametrize("command", ["enable", "disable", "remove", "trust", "untrust"])
def test_plugin_failure_exit_code(config_env, monkeypatch, command):
    monkeypatch.setattr(
        "deepseek_tui.plugins.PluginHost.apply",
        lambda *_: SimpleNamespace(outcome="failed", message="fixture failure"),
    )
    call = CliRunner().invoke(cli.app, ["plugin", command, "missing"])
    assert call.exit_code == 1


def test_custom_model_resolve_keeps_name(config_env):
    call = CliRunner().invoke(
        cli.app, ["model", "resolve", "custom-fixture", "--provider", "openai"]
    )
    assert call.exit_code == 0 and "resolved: custom-fixture" in call.output


def test_sandbox_diagnostic_does_not_claim_policy_evaluation(config_env):
    call = CliRunner().invoke(cli.app, ["sandbox", "check", "ls"])
    assert call.exit_code == 0 and "command-safety-heuristic" in call.output
    call = CliRunner().invoke(cli.app, ["sandbox", "check", "ls", "--ask", "never"])
    assert call.exit_code != 0


@pytest.mark.parametrize(
    "section,values",
    [
        ("providers", {"x": {"timeout": 0}}),
        ("providers", {"x": {"context_window": -1}}),
        ("providers", {"x": {"context_windows": {"fixture": 0}}}),
        ("providers", {"x": {"rate_limit": -1}}),
        ("subagents", {"max_concurrent": 0}),
        ("subagents", {"llm_max_concurrent": -1}),
        ("logging", {"keep_hours": -1}),
    ],
)
def test_invalid_resource_limits_rejected(section, values):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Config.model_validate({section: values})


def test_zero_disable_values_remain_valid():
    cfg = Config.model_validate(
        {
            "providers": {"x": {"rate_limit": 0}},
            "subagents": {"llm_max_concurrent": 0},
            "logging": {"keep_hours": 0},
        }
    )
    assert cfg.providers["x"].rate_limit == 0 and cfg.subagents.llm_max_concurrent == 0


def test_logging_reload_restores_old_overrides(tmp_path):
    import logging

    from deepseek_tui.utils import setup_logging

    target = logging.getLogger("audit17.fixture")
    previous = target.level
    try:
        setup_logging(
            Config.model_validate(
                {"logging": {"dir": str(tmp_path), "per_logger": {"audit17.fixture": "DEBUG"}}}
            )
        )
        assert target.level == logging.DEBUG
        setup_logging(Config.model_validate({"logging": {"enabled": False}}))
        assert target.level == previous
    finally:
        setup_logging(Config.model_validate({"logging": {"enabled": False}}))
        target.setLevel(previous)


def test_concurrent_home_migration(config_env):
    import subprocess
    import sys

    from deepseek_tui.config.layout import user_home_lease

    home, _ = config_env
    runtime_home = home / ".deepseek"
    legacy = runtime_home / "workbench/backup-meta.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"directory":"fixture"}')
    code = (
        "from deepseek_tui.config.layout import ensure_user_home_layout; "
        'print("ready",flush=True); ensure_user_home_layout()'
    )
    env = dict(os.environ, PYTHONPATH=str(Path(cli.__file__).parents[2]))
    children = []
    try:
        with user_home_lease():
            for _ in range(2):
                child = subprocess.Popen(
                    [sys.executable, "-c", code],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                children.append(child)
                assert child.stdout.readline().strip() == "ready"
        for child in children:
            _, err = child.communicate(timeout=10)
            assert child.returncode == 0, err
        assert (
            json.loads((runtime_home / "settings.json").read_text())["backup"]["directory"]
            == "fixture"
        )
        assert not legacy.exists()
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()


def test_redaction_keeps_nonsecret_limits():
    cfg = Config.model_validate(
        {
            "providers": {
                "x": {
                    "api_key": "FIXTURE_ONLY",
                    "max_tokens": 123,
                    "extra_headers": {"Authorization": "FIXTURE_ONLY"},
                }
            },
            "automation": {"wecom": {"webhook_key": "FIXTURE_ONLY"}},
        }
    )
    output = cli._redacted_config(cfg)
    assert "FIXTURE_ONLY" not in json.dumps(output)
    assert output["providers"]["x"]["max_tokens"] == 123


def test_cli_policy_overrides_must_pass_requirements(config_env):
    home, _ = config_env
    requirement = home / "requirements.toml"
    requirement.write_text('allowed_approval_policies=["on-request"]\n')
    user_config(home, f'requirements_path="{requirement}"\n')
    call = CliRunner().invoke(cli.app, ["--approval-policy", "never", "config", "show"])
    assert call.exit_code != 0


async def test_budget_helpers_use_configured_window():
    from deepseek_tui.config.models import ProviderConfig
    from deepseek_tui.engine.capacity import CompactionBudgetError, validate_summary_request_budget
    from deepseek_tui.engine.context_pressure import measure_context_pressure
    from deepseek_tui.engine.cycle import CycleConfig, should_advance_cycle
    from deepseek_tui.protocol.messages import Message, MessageRequest

    cfg = Config(
        model="gpt-4o", providers={"deepseek": ProviderConfig(context_windows={"gpt-4o": 4096})}
    )
    messages = [Message.user("x")]
    assert measure_context_pressure("gpt-4o", messages, model_config=cfg).window == 4096
    assert should_advance_cycle(4000, "gpt-4o", CycleConfig(enabled=True), False, model_config=cfg)
    with pytest.raises(CompactionBudgetError):
        validate_summary_request_budget(
            MessageRequest(model="gpt-4o", messages=messages, max_tokens=5000), cfg
        )


def test_migration_exception_releases_home_lease(config_env, monkeypatch):
    from deepseek_tui.config import layout
    from deepseek_tui.workspace.project_lease import FileLease

    home, _ = config_env

    def fail(_):
        raise OSError("fixture migration failure")

    monkeypatch.setattr(layout, "_migrate_agents", fail)
    with pytest.raises(OSError, match="fixture migration failure"):
        layout.ensure_user_home_layout()
    lease = FileLease(home / ".deepseek/locks/home-layout.lock")
    try:
        assert lease.acquire_blocking(nonblocking=True)
    finally:
        lease.release()


@pytest.mark.parametrize("managed_kind", [None, "top", "provider", "switch", "empty"])
def test_cli_key_precedence_reaches_client_factory(config_env, monkeypatch, managed_kind):
    from deepseek_tui.client.factory import build_llm_client
    from deepseek_tui.config.routing import config_for_model
    from deepseek_tui.state.secrets import SecretsManager

    home, _ = config_env
    managed = home / "managed.toml"
    text = f'managed_config_path="{managed}"\n[providers.deepseek]\napi_key="STORED_FIXTURE"\n'
    user_config(home, text)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ENV_FIXTURE")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    if managed_kind == "top":
        managed.write_text('api_key="MANAGED_FIXTURE"\n')
    elif managed_kind == "provider":
        managed.write_text('[providers.deepseek]\napi_key="MANAGED_FIXTURE"\n')
    elif managed_kind == "switch":
        managed.write_text('provider="openai"\n')
    elif managed_kind == "empty":
        managed.write_text('api_key=""\n')
    cfg = ConfigLoader().load(overrides={"api_key": "CLI_FIXTURE"})
    if managed_kind in {"switch", "empty"}:
        assert SecretsManager().resolve_api_key(cfg) is None
        return
    expected = "MANAGED_FIXTURE" if managed_kind else "CLI_FIXTURE"
    assert SecretsManager().resolve_api_key(cfg) == expected
    assert SecretsManager().resolve_api_key(config_for_model(cfg, "openai::custom")) is None
    captured = {}

    monkeypatch.setattr(
        "deepseek_tui.client.factory.DeepSeekClient",
        type("FakeClient", (), {"__init__": lambda self, **kwargs: captured.update(kwargs)}),
    )
    build_llm_client(cfg)
    assert captured["api_key"] == expected
    assert "_api_key_override" not in cfg.model_dump()
