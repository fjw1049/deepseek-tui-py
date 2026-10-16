"""One rule for file access: explicit grant, else ask; denials say why.

Matrix: entry point (mention / read / write / search / sub-agent) x
decision (inside workspace / granted / outside / sensitive / trust / never).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import ApprovalHandler, AutoApprovalHandler, EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.approval import ApprovalBridge, HttpApprovalHandler
from deepseek_tui.server.threads.store import RuntimeThreadStore
from deepseek_tui.tools.approval import (
    NEVER_BLOCKED_PREFIX,
    ApprovalDecision,
    path_access_prompt,
)
from deepseek_tui.tools.file import ReadFileTool, WriteFileTool
from deepseek_tui.tools.path_access import PathGrant, PathGrants
from deepseek_tui.tools.registry import ToolContext, ToolError, ToolRegistry
from deepseek_tui.tools.search import GrepFilesTool
from deepseek_tui.tools.subagent.loop import _execute_subagent_tool


@pytest.fixture
def layout(tmp_path: Path) -> SimpleNamespace:
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "inside.txt").write_text("inside")
    (workspace / ".env").write_text("TOKEN=inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.txt").write_text("outside notes")
    (outside / ".env").write_text("TOKEN=outside")
    return SimpleNamespace(
        workspace=workspace.resolve(),
        outside=outside.resolve(),
        notes=(outside / "notes.txt").resolve(),
        outside_env=(outside / ".env").resolve(),
    )


# --- check_path: the single rule -------------------------------------------


def test_check_path_matrix(layout) -> None:
    ctx = ToolContext(working_directory=layout.workspace)
    inside = ctx.check_path("inside.txt", allow_read_roots=True)
    assert inside.allowed
    outside = ctx.check_path(str(layout.notes), allow_read_roots=True)
    assert not outside.allowed and outside.outside and not outside.sensitive
    env = ctx.check_path(".env", allow_read_roots=True)
    assert not env.allowed and env.sensitive

    ctx.path_grants.add(layout.outside, recursive=True)
    assert ctx.check_path(str(layout.notes), allow_read_roots=True).allowed
    assert not ctx.check_path(str(layout.notes), write=True).allowed  # read grant != write
    # A directory grant never covers credential files inside it.
    assert not ctx.check_path(str(layout.outside_env), allow_read_roots=True).allowed

    ctx.path_grants.add(layout.outside_env)  # exact-file grant does
    assert ctx.check_path(str(layout.outside_env), allow_read_roots=True).allowed


def test_write_grant_covers_read_and_trust_never_covers_sensitive(layout) -> None:
    ctx = ToolContext(working_directory=layout.workspace)
    ctx.path_grants.add(layout.notes, write=True)
    assert ctx.check_path(str(layout.notes), write=True).allowed
    assert ctx.check_path(str(layout.notes), allow_read_roots=True).allowed

    trusted = ToolContext(working_directory=layout.workspace, trust_mode=True)
    assert trusted.check_path(str(layout.outside / "x.txt"), write=True).allowed
    assert not trusted.check_path(".env", allow_read_roots=True).allowed


def test_extra_read_roots_are_read_only(layout) -> None:
    ctx = ToolContext(working_directory=layout.workspace, extra_read_roots=(layout.outside,))
    assert ctx.check_path(str(layout.notes), allow_read_roots=True).allowed
    assert not ctx.check_path(str(layout.notes), write=True).allowed


def test_denials_keep_error_types_and_explain_who_can_authorize(layout) -> None:
    ctx = ToolContext(working_directory=layout.workspace)
    with pytest.raises(ValueError, match="escapes workspace.*@-mention"):
        ctx.resolve_path(str(layout.notes), allow_read_roots=True)
    with pytest.raises(ToolError, match="refusing to read sensitive file.*@-mention"):
        ctx.resolve_path(".env", allow_read_roots=True)
    with pytest.raises(ToolError, match="refusing to write sensitive file"):
        ctx.resolve_path(".env", write=True)


async def test_os_permission_denial_is_reported_as_os_level(layout, monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    def deny(*_args, **_kwargs):
        raise PermissionError(1, "Operation not permitted", str(layout.workspace / "inside.txt"))

    monkeypatch.setattr("deepseek_tui.tools.file._read_text_page", deny)
    with pytest.raises(ToolError, match="operating system denied access.*Privacy & Security"):
        await registry.execute(
            "read_file", {"path": "inside.txt"}, ToolContext(working_directory=layout.workspace)
        )


# --- PathGrants store ------------------------------------------------------


def test_grants_round_trip_drop_turns_and_notify(layout) -> None:
    saved: list[list[dict]] = []
    grants = PathGrants(turn_id="t1", on_change=saved.append)
    grants.add(layout.notes)
    grants.turn_id = "t2"
    grants.add(layout.outside, recursive=True)
    assert len(saved) == 2

    restored = PathGrants()
    restored.load(saved[-1])
    assert restored.grants == grants.grants

    grants.drop_turns({"t2"})
    assert grants.grants == [PathGrant(layout.notes, turn_id="t1")]
    assert saved[-1] == grants.dump()


def test_store_sidecar_survives_reload_and_thread_delete(tmp_path) -> None:
    store = RuntimeThreadStore(tmp_path / "store")
    store.save_path_grants("thr_1", [{"path": "/a", "turn_id": "t"}])
    assert RuntimeThreadStore(tmp_path / "store").load_path_grants("thr_1") == [
        {"path": "/a", "turn_id": "t"}
    ]
    store.delete_thread("thr_1")
    assert store.load_path_grants("thr_1") == []


# --- approval preflight ----------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "path_attr", "expect"),
    [
        ("on-request", "notes", "prompt"),
        ("untrusted", "notes", "prompt"),
        ("auto", "notes", None),  # auto without trust: execution reports it
        ("auto", "outside_env", "forced"),  # credentials always reach a human
        ("never", "notes", "blocked"),
    ],
)
def test_preflight_by_policy(layout, policy, path_attr, expect) -> None:
    ctx = ToolContext(working_directory=layout.workspace)
    path = str(getattr(layout, path_attr))
    prompt = path_access_prompt(ReadFileTool(), {"path": path}, ctx, policy)
    if expect is None:
        assert prompt is None
        return
    assert prompt is not None
    assert prompt.request.force_prompt  # only a human may widen the boundary
    assert prompt.request.reason.startswith(NEVER_BLOCKED_PREFIX) is (expect == "blocked")


def test_preflight_skips_allowed_paths_and_media(layout) -> None:
    ctx = ToolContext(working_directory=layout.workspace)
    assert path_access_prompt(ReadFileTool(), {"path": "inside.txt"}, ctx, "on-request") is None
    assert path_access_prompt(ReadFileTool(), {"path": "media:abc"}, ctx, "on-request") is None
    ctx.path_grants.add(layout.notes)
    assert path_access_prompt(ReadFileTool(), {"path": str(layout.notes)}, ctx, None) is None


def test_search_root_approval_grants_directory_tree(layout) -> None:
    ctx = ToolContext(working_directory=layout.workspace)
    prompt = path_access_prompt(
        GrepFilesTool(), {"pattern": "x", "path": str(layout.outside)}, ctx, None
    )
    assert prompt is not None
    prompt.request.remembered = True
    assert prompt.grant(ctx) is ctx  # remembered: shared with this session
    assert ctx.check_path(str(layout.notes), allow_read_roots=True).allowed


# --- handlers --------------------------------------------------------------


@pytest.mark.parametrize("path", [".env", "../outside/notes.txt"])
async def test_handler_without_a_human_denies_path_prompts(layout, path) -> None:
    ctx = ToolContext(working_directory=layout.workspace)
    prompt = path_access_prompt(ReadFileTool(), {"path": path}, ctx, "on-request")
    assert prompt is not None
    decision = await AutoApprovalHandler().request_approval("c", prompt.request)
    assert decision is ApprovalDecision.DENIED


async def test_http_handler_asks_for_forced_prompts_even_under_auto(layout) -> None:
    bridge = ApprovalBridge()

    async def auto() -> bool:
        return True

    handler = HttpApprovalHandler(bridge, auto_approve=auto)
    ctx = ToolContext(working_directory=layout.workspace)
    prompt = path_access_prompt(ReadFileTool(), {"path": ".env"}, ctx, "auto")
    assert prompt is not None
    task = asyncio.create_task(handler.request_approval("c", prompt.request))
    await asyncio.sleep(0)
    [pending] = bridge.list_pending()
    assert bridge.resolve(pending["approval_id"], True)
    assert await asyncio.wait_for(task, 1) is ApprovalDecision.APPROVED


# --- engine gate -----------------------------------------------------------


class _NoopClient(LLMClient):
    async def stream_chat_completion(self, request):  # pragma: no cover - unused
        if False:
            yield None


class _Handler(ApprovalHandler):
    def __init__(self, *decisions: ApprovalDecision, auto: bool = False) -> None:
        self.decisions = list(decisions)
        self.auto = auto
        self.requests: list = []

    async def auto_approve_enabled(self) -> bool:
        return self.auto

    async def request_approval(self, tool_call_id, request) -> ApprovalDecision:
        self.requests.append(request)
        return self.decisions.pop(0)


async def _engine(layout, handler: ApprovalHandler) -> Engine:
    return await Engine.create(
        handle=EngineHandle(),
        client=_NoopClient(),
        working_directory=layout.workspace,
        config=Config(
            features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False)
        ),
        start_mcp=False,
        approval_handler=handler,
    )


async def _run(engine: Engine, *calls: tuple[str, dict]) -> list:
    messages = await engine._execute_tool_calls(
        [ToolCall(id=f"c{i}", name=name, arguments=args) for i, (name, args) in enumerate(calls)]
    )
    return [m.content[0] for m in messages]


async def test_engine_asks_once_per_call_unless_remembered(layout) -> None:
    handler = _Handler(
        ApprovalDecision.APPROVED, ApprovalDecision.APPROVED_SESSION
    )
    engine = await _engine(layout, handler)
    try:
        read = ("read_file", {"path": str(layout.notes)})
        [first] = await _run(engine, read)
        assert not first.is_error and "outside notes" in first.content
        assert engine.tool_context.path_grants.grants == []  # one-shot revoked
        [second] = await _run(engine, read)  # asks again, user remembers
        [third] = await _run(engine, read)  # covered by the session grant
        assert not second.is_error and not third.is_error
        assert len(handler.requests) == 2
        assert str(layout.notes) in handler.requests[0].primary_preview
    finally:
        await engine.shutdown_session()


async def test_engine_denial_tells_the_model_not_to_work_around_it(layout) -> None:
    engine = await _engine(layout, _Handler(ApprovalDecision.DENIED))
    try:
        [result] = await _run(engine, ("read_file", {"path": str(layout.notes)}))
        assert result.is_error
        assert "did not authorize" in result.content and "shell" in result.content
    finally:
        await engine.shutdown_session()


async def test_engine_outside_write_is_one_prompt_then_written(layout) -> None:
    handler = _Handler(ApprovalDecision.APPROVED)
    engine = await _engine(layout, handler)
    target = layout.outside / "new.txt"
    try:
        [result] = await _run(engine, ("write_file", {"path": str(target), "content": "hi"}))
        assert not result.is_error, result.content
        assert target.read_text() == "hi"
        assert len(handler.requests) == 1
    finally:
        await engine.shutdown_session()


async def test_engine_trust_mode_reads_outside_but_still_asks_for_credentials(layout) -> None:
    handler = _Handler(ApprovalDecision.APPROVED, auto=True)
    engine = await _engine(layout, handler)
    engine.tool_context.trust_mode = True
    try:
        [plain] = await _run(engine, ("read_file", {"path": str(layout.notes)}))
        assert not plain.is_error and handler.requests == []
        [secret] = await _run(engine, ("read_file", {"path": ".env"}))
        assert not secret.is_error and "TOKEN=inside" in secret.content
        assert [r.force_prompt for r in handler.requests] == [True]
    finally:
        await engine.shutdown_session()


async def test_non_interactive_engine_cannot_grant_itself_outside_access(layout) -> None:
    # Background tasks / automations run with AutoApprovalHandler.
    engine = await _engine(layout, AutoApprovalHandler())
    target = layout.outside / "planted.txt"
    try:
        [read] = await _run(engine, ("read_file", {"path": str(layout.notes)}))
        [write] = await _run(engine, ("write_file", {"path": str(target), "content": "x"}))
        assert read.is_error and "outside notes" not in read.content
        assert write.is_error and not target.exists()
        assert engine.tool_context.path_grants.grants == []
    finally:
        await engine.shutdown_session()


async def test_engine_never_policy_blocks_without_asking(layout) -> None:
    handler = _Handler()
    engine = await _engine(layout, handler)
    engine.exec_policy.approval_policy = "never"
    try:
        [result] = await _run(engine, ("read_file", {"path": str(layout.notes)}))
        assert result.is_error and NEVER_BLOCKED_PREFIX in result.content
        assert handler.requests == []
    finally:
        await engine.shutdown_session()


async def test_parallel_batch_with_unauthorized_read_is_serialized_and_asked(layout) -> None:
    handler = _Handler(ApprovalDecision.APPROVED)
    engine = await _engine(layout, handler)
    try:
        results = await _run(
            engine,
            ("read_file", {"path": "inside.txt"}),
            ("read_file", {"path": str(layout.notes)}),
        )
        assert [r.is_error for r in results] == [False, False]
        assert len(handler.requests) == 1
    finally:
        await engine.shutdown_session()


# --- sub-agents ------------------------------------------------------------


async def test_subagent_shares_grants_and_asks_through_parent(layout) -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    shared = PathGrants()
    context = ToolContext(working_directory=layout.workspace, path_grants=shared)
    handler = _Handler(ApprovalDecision.APPROVED_SESSION)
    runtime = SimpleNamespace(
        config=SimpleNamespace(approval_policy="on-request"),
        approval_handler=handler,
        emit_event=None,
    )

    async def read() -> str:
        return await _execute_subagent_tool(
            registry, context, tool_name="read_file",
            tool_input={"path": str(layout.notes)}, auto_approve=False,
            tool_call_id="tc", runtime=runtime,  # type: ignore[arg-type]
        )

    assert "outside notes" in await read()
    assert "outside notes" in await read()
    assert len(handler.requests) == 1
    assert shared.allows(layout.notes, write=False)  # visible to the parent


async def test_detached_auto_subagent_does_not_gain_outside_access(layout) -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    context = ToolContext(working_directory=layout.workspace)
    out = await _execute_subagent_tool(
        registry, context, tool_name="read_file",
        tool_input={"path": str(layout.notes)}, auto_approve=True,
        tool_call_id="tc", runtime=None,
    )
    assert out.startswith("Error:") and "approval" in out
    assert context.path_grants.grants == []


def test_one_shot_grant_is_call_local_and_never_persisted(layout):
    ctx = ToolContext(working_directory=layout.workspace)
    saved = []
    ctx.path_grants.on_change = saved.append
    sibling = ToolContext(working_directory=layout.workspace, path_grants=ctx.path_grants)
    prompt = path_access_prompt(ReadFileTool(), {"path": str(layout.notes)}, ctx, "on-request")
    approved = prompt.grant(ctx)
    assert approved.check_path(str(layout.notes), allow_read_roots=True).allowed
    assert not sibling.check_path(str(layout.notes), allow_read_roots=True).allowed
    assert ctx.path_grants.dump() == []
    assert saved == []
    reloaded = PathGrants()
    reloaded.load(ctx.path_grants.dump())
    assert not reloaded.allows(layout.notes, write=False)
    assert approved.metadata is ctx.metadata
    assert approved.file_reads is ctx.file_reads


async def test_search_honors_exact_sensitive_grant_but_not_directory_grant(layout):
    ctx = ToolContext(working_directory=layout.workspace)
    ctx.path_grants.add(layout.outside, recursive=True)
    tool = GrepFilesTool()
    result = await tool.execute({"path": str(layout.outside), "pattern": "TOKEN"}, ctx)
    assert "TOKEN=outside" not in result.content
    ctx.path_grants.add(layout.outside_env)
    for path in (layout.outside, layout.outside_env):
        result = await tool.execute({"path": str(path), "pattern": "TOKEN", "output_mode": "content"}, ctx)
        assert "TOKEN=outside" in result.content
