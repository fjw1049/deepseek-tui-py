"""Automation follows current configuration, including arbitrary model IDs."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.automation.pipeline import fire_http_trigger, try_write_run_result
from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config, FeatureConfig, ProviderConfig
from deepseek_tui.config.routing import config_for_model
from deepseek_tui.engine.dispatch import _run_task_engine_turn
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadManager,
    RuntimeThreadManagerConfig,
    UpdateThreadRequest,
)
from deepseek_tui.server.threads.items import automation_result_items, automation_result_message
from deepseek_tui.tools.automation import (
    AUTOMATION_MANAGER_KEY,
    AutomationManager,
    AutomationRunStatus,
    CreateAutomationRequest,
    CronCreateTool,
)
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.task import TaskManager, TaskManagerConfig, TaskStatus


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    loader = ConfigLoader.load
    config = Config(
        provider="deepseek",
        model="global-initial",
        api_key="wrong-global-secret",
        base_url="https://wrong.test/v1",
        providers={
            "endpoint": ProviderConfig(
                model="initial-model",
                api_key="endpoint-secret",
                base_url="https://endpoint.test/v1",
                extra_headers={"x-test": "header-secret"},
            ),
            "endpoint-secondary": ProviderConfig(
                model="secondary-default",
                api_key="secondary-secret",
                base_url="https://secondary.test/v1",
                protocol="anthropic",
            ),
        },
        features=FeatureConfig(mcp=False, tasks=False, subagents=False, automations=False),
    )
    monkeypatch.setattr(ConfigLoader, "load", lambda self, **kwargs: config)
    tasks = TaskManager(
        TaskManagerConfig(
            data_dir=tmp_path / "tasks",
            default_workspace=tmp_path,
            config=config,
        )
    )
    threads = RuntimeThreadManager(
        config=config,
        workspace=tmp_path,
        manager_cfg=RuntimeThreadManagerConfig.from_task_data_dir(tmp_path / "tasks"),
        llm_client=object(),
    )
    automations = AutomationManager.open(tmp_path / "automations")
    automations.thread_manager = threads
    return SimpleNamespace(
        config=config,
        tasks=tasks,
        threads=threads,
        automations=automations,
        workspace=tmp_path,
        loader=loader,
    )


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize(
    "provider,model",
    [
        ("endpoint", "glm-5-3"),
        ("endpoint", "any-new-model-2027"),
        ("endpoint-secondary", "claude-selected"),
        ("endpoint-secondary", "vendor/model-v9"),
    ],
)
async def test_chat_jobs_follow_latest_selection_before_any_new_message(
    setup,
    monkeypatch,
    restart,
    provider,
    model,
):
    thread = await setup.threads.create_thread(
        CreateThreadRequest(
            provider="endpoint",
            model="initial-model",
        )
    )
    context = ToolContext(
        working_directory=setup.workspace,
        metadata={
            AUTOMATION_MANAGER_KEY: setup.automations,
            "runtime_thread_id": thread.id,
            "task_config": config_for_model(setup.config, "initial-model", provider="endpoint"),
            "task_model": "initial-model",
        },
    )
    result = await CronCreateTool().execute(
        {
            "name": "read project",
            "prompt": "Read README",
            "schedule": "0 9 * * *",
        },
        context,
    )
    job = setup.automations.get_automation(result.content)
    assert "secret" not in str(job.to_dict())
    await setup.threads.update_thread(
        thread.id, UpdateThreadRequest(provider=provider, model=model)
    )
    setup.config.providers[provider].api_key = "rotated-provider-secret"
    manager = (
        AutomationManager.open(setup.workspace / "automations") if restart else setup.automations
    )
    manager.thread_manager = setup.threads
    run = await manager.run_now(job.id, setup.tasks)
    task = await setup.tasks.get_task(run.task_id)
    assert (task.provider, task.model) == (provider, model)
    saved = (setup.workspace / "tasks" / "tasks" / f"{task.id}.json").read_text()
    assert "secret" not in saved and "api_key" not in saved
    _, execution, _ = await setup.tasks._pop_next_task()
    captured = []

    def build(config):
        captured.append(config)
        return SimpleNamespace(close=AsyncMock())

    class ReachedRuntime(Exception):
        pass

    async def runtime(**kwargs):
        raise ReachedRuntime

    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", build)
    monkeypatch.setattr("deepseek_tui.tools.runtime.create_tool_runtime", runtime)
    with pytest.raises(ReachedRuntime):
        await _run_task_engine_turn(execution, asyncio.Event())
    actual = captured[0].effective_provider_config()
    expected = setup.config.providers[provider]
    assert actual.model == model
    assert actual.base_url == expected.base_url
    assert actual.api_key == "rotated-provider-secret"
    assert actual.protocol == (expected.protocol or "openai")
    assert actual.extra_headers == expected.extra_headers
    assert setup.config.provider == "deepseek"


async def test_standalone_job_and_http_trigger_follow_latest_global_config(setup, monkeypatch):
    job = setup.automations.create_automation(
        CreateAutomationRequest(
            name="standalone",
            prompt="Read README",
            schedule="0 9 * * *",
        )
    )
    # Previously frozen job fields must not override the user's newer selection.
    old = job.to_dict() | {"provider": "deepseek", "model": "old-frozen-model"}
    import json

    (setup.workspace / "automations" / f"{job.id}.json").write_text(json.dumps(old))
    latest = config_for_model(setup.config, "totally-custom-model", provider="endpoint-secondary")
    monkeypatch.setattr(ConfigLoader, "load", lambda self, **kwargs: latest)
    run = await setup.automations.run_now(job.id, setup.tasks)
    triggered = await fire_http_trigger(prompt="Read README", task_manager=setup.tasks)
    for task_id in (run.task_id, triggered["task_id"]):
        task = await setup.tasks.get_task(task_id)
        assert (task.provider, task.model) == ("endpoint-secondary", "totally-custom-model")


async def test_real_config_file_is_reloaded_between_runs(setup, monkeypatch):
    path = setup.workspace / "user-config.toml"
    monkeypatch.setenv("DEEPSEEK_CONFIG_PATH", str(path))
    monkeypatch.setattr(ConfigLoader, "load", setup.loader)
    job = setup.automations.create_automation(
        CreateAutomationRequest(
            name="standalone",
            prompt="Read README",
            schedule="0 9 * * *",
            cwds=[str(setup.workspace)],
        )
    )
    for model in ("first-custom-model", "replacement-model"):
        path.write_text(
            'provider = "local-custom"\n[providers.local-custom]\n'
            f'model = "{model}"\nbase_url = "https://custom.test/v1"\napi_key = "fake-key"\n'
        )
        run = await setup.automations.run_now(job.id, setup.tasks)
        task = await setup.tasks.get_task(run.task_id)
        assert (task.provider, task.model) == ("local-custom", model)


@pytest.mark.parametrize("missing_manager", [False, True])
async def test_missing_origin_fails_without_guessing_a_model(setup, missing_manager):
    job = setup.automations.create_automation(
        CreateAutomationRequest(
            name="missing",
            prompt="Read README",
            schedule="0 9 * * *",
            conversation_thread_id="thr_missing",
        )
    )
    if missing_manager:
        setup.automations.thread_manager = None
    run = await setup.automations.run_now(job.id, setup.tasks)
    assert run.status is AutomationRunStatus.FAILED
    assert run.task_id is None
    assert not await setup.tasks.list_tasks()


async def test_removed_provider_fails_without_using_global_default(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    thread.provider = "deleted-custom-provider"
    setup.threads.store.save_thread(thread)
    job = setup.automations.create_automation(
        CreateAutomationRequest(
            name="removed",
            prompt="Read README",
            schedule="0 9 * * *",
            conversation_thread_id=thread.id,
        )
    )
    run = await setup.automations.run_now(job.id, setup.tasks)
    assert run.status is AutomationRunStatus.FAILED and run.task_id is None
    assert "Unknown model provider" in run.error


@pytest.mark.parametrize(
    "model,base_url,problem",
    [
        (None, "https://custom.test/v1", "model"),
        ("", "https://custom.test/v1", "model"),
        ("custom-model", None, "URL"),
    ],
)
def test_incomplete_custom_config_cannot_fall_back_to_deepseek(model, base_url, problem):
    config = Config(
        provider="unknown-custom",
        providers={
            "unknown-custom": ProviderConfig(model=model, base_url=base_url, api_key="fake-key"),
        },
    )
    with pytest.raises(ValueError, match=problem):
        build_llm_client(config)


async def test_auth_failure_chat_is_short_and_keeps_task_context(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest())
    job = setup.automations.create_automation(
        CreateAutomationRequest(
            name="项目检查",
            prompt="阅读 README 并提出两个建议。",
            schedule="0 9 * * *",
            conversation_thread_id=thread.id,
        )
    )
    run = await setup.automations.run_now(job.id, setup.tasks)
    task = SimpleNamespace(
        status=TaskStatus.FAILED,
        result_summary=None,
        prompt="阅读 README 并提出两个建议。",
        error=(
            'HTTP 401 from https://provider.test: {"message":"Authentication Fails, '
            'Your api key: sensitive-key is invalid"}'
        ),
    )
    run.status = AutomationRunStatus.FAILED
    assert await try_write_run_result(
        job,
        run,
        SimpleNamespace(get_task=AsyncMock(return_value=task)),
        thread_manager=setup.threads,
    )
    item = automation_result_items(setup.threads.store, thread.id)[0]
    assert "认证" in item.detail
    assert "sensitive-key" not in item.detail and "provider.test" not in item.detail
    assert "任务要求" not in item.detail
    assert item.detail.count("项目检查") == 1
    assert f"Task ID: {run.task_id}" in item.detail
    assert len(item.detail) < 250
    assert "阅读 README 并提出两个建议" in str(automation_result_message(item))


async def test_helper_requests_use_the_conversation_provider(setup, monkeypatch):
    from deepseek_tui.protocol.responses import StreamTextDelta
    from deepseek_tui.server.threads import TurnItemKind

    thread = await setup.threads.create_thread(
        CreateThreadRequest(
            provider="endpoint-secondary",
            model="unlisted-helper-model",
        )
    )
    requests = []

    async def stream(request):
        requests.append(request)
        yield StreamTextDelta(text="Recovered answer")

    client = SimpleNamespace(stream_chat_completion=stream)
    selected = []

    def get_client(provider=None):
        selected.append(provider)
        assert provider == "endpoint-secondary"
        return client

    monkeypatch.setattr(setup.threads, "_get_llm_client", get_client)
    await setup.threads.append_automation_notice(
        thread.id,
        automation_name="evidence",
        summary="Read README successfully",
    )
    stored = setup.threads.store.load_thread(thread.id)
    turn = setup.threads.store.load_turn(stored.latest_turn_id)
    item = setup.threads.store.load_item(turn.item_ids[0])
    item.kind = TurnItemKind.TOOL_CALL
    setup.threads.store.save_item(item)
    assert (
        await setup.threads._recover_missing_final_answer(thread.id, turn.id) == "Recovered answer"
    )
    assert requests[0].model == "unlisted-helper-model"

    async def narrate(actual_client, config, **kwargs):
        assert actual_client is client
        assert config.provider == "endpoint-secondary"
        assert config.effective_provider_config().model == "unlisted-helper-model"
        return "phase summary"

    monkeypatch.setattr("deepseek_tui.server.threads.manager.compute_narration_display", narrate)
    assert (
        await setup.threads._compute_phase_bridge(
            thread_id=thread.id,
            user_prompt="Read README",
            state=object(),
            segment=object(),
            tool_calls=(),
            recent_tool_results=[],
            locale="en",
        )
        == "phase summary"
    )
    assert selected == ["endpoint-secondary", "endpoint-secondary"]


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
async def test_arbitrary_model_name_is_preserved_in_outgoing_payload(protocol):
    from deepseek_tui.protocol.messages import Message, MessageRequest

    model = "vendor/new-model@v2"
    config = Config(
        provider="never-seen-provider",
        providers={
            "never-seen-provider": ProviderConfig(
                model=model,
                base_url="https://custom.test/v1",
                api_key="fake-key",
                protocol=protocol,
            ),
        },
    )
    client = build_llm_client(config)
    try:
        payload = client._build_payload(
            MessageRequest(model=model, messages=[Message.user("hello")])
        )
        assert payload["model"] == model
        assert client.base_url == "https://custom.test/v1"
    finally:
        await client.close()


@pytest.mark.parametrize(
    "base_url,key,problem",
    [
        (None, "custom-key", "URL"),
        ("https://custom.test/v1", None, "missing_api_key"),
    ],
)
def test_legacy_client_cannot_use_another_providers_defaults(monkeypatch, base_url, key, problem):
    from deepseek_tui.client.deepseek import DeepSeekClient

    monkeypatch.setenv("DEEPSEEK_API_KEY", "unrelated-provider-key")
    config = Config(
        provider="custom-provider",
        providers={
            "custom-provider": ProviderConfig(model="user-model", base_url=base_url, api_key=key),
        },
    )
    with pytest.raises(ValueError, match=problem):
        DeepSeekClient.from_config(config)


async def test_creating_thread_with_only_provider_uses_its_configured_model(setup):
    thread = await setup.threads.create_thread(CreateThreadRequest(provider="endpoint-secondary"))
    assert (thread.provider, thread.model) == ("endpoint-secondary", "secondary-default")
