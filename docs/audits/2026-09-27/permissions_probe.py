"""Offline characterization of permission boundaries; no shell command executes.

PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/permissions_probe.py
Assertions confirm current behavior (including defects), not desired correctness.
All identifiers, URLs and credentials are synthetic. No LLM/network calls.
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from deepseek_tui.config.models import Config, FeatureConfig, HooksConfig
from deepseek_tui.engine.handle import ApprovalHandler, AutoApprovalHandler, DenyApprovalHandler, EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.integrations.skills import SkillRegistry
from deepseek_tui.policy.exec_policy import ExecPolicyConfig, RuleSet, TomlBackedPolicy
from deepseek_tui.policy.network import Decision as NetworkDecision, NetworkPolicy, NetworkPolicyDecider
from deepseek_tui.policy.sandbox import (
    CommandSpec, ExecutionSandboxPolicy, SandboxManager, elevation_kind_label,
    suggest_elevation_policy, sync_execution_sandbox_policy,
)
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.server.approval import ElevationBridge, PendingElevationRecord
from deepseek_tui.tools.approval import (
    ApprovalCache, ApprovalDecision, approval_request_for_tool, build_approval_key,
)
from deepseek_tui.tools.file import WriteFileTool
from deepseek_tui.tools.registry import ToolContext, ToolRegistry, ToolResult
from deepseek_tui.tools.runtime import create_tool_runtime
from deepseek_tui.tools.shell import ExecShellTool, check_command_policy
from deepseek_tui.tools.web import FetchUrlTool
from deepseek_tui.tools.subagent.agent import SubAgent
from deepseek_tui.tools.subagent.loop import _execute_subagent_tool, run_subagent_loop
from deepseek_tui.tools.subagent.manager import SubAgentRuntime
from deepseek_tui.tools.subagent.types import SubAgentAssignment, SubAgentType


class ManualAllow(ApprovalHandler):
    async def request_approval(self, tool_call_id, request):
        return ApprovalDecision.APPROVED


def config(**kwargs):
    return Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False,
        automations=False, plugins=False, exec_policy=False),
        hooks=HooksConfig(enabled=False, hooks=[]), **kwargs)


async def probes(root):
    observed = {}
    # Raw command evaluation vs the real shell preflight. No execution.
    raw = "echo ready\nprintf blocked"
    policy = ExecPolicyConfig(rules={"probe": RuleSet(deny=["printf blocked"])})
    ctx = ToolContext(working_directory=root, policy=TomlBackedPolicy(policy))
    observed["deny_rule"] = dict(raw=policy.evaluate(raw).kind,
        shell_refusal=check_command_policy(raw, ctx))
    assert observed["deny_rule"] == {"raw": "deny", "shell_refusal": None}

    # Actual Engine initialization, without network/plugin/skill discovery.
    cfg = config(sandbox_mode="read-only")
    runtime = await create_tool_runtime(config=cfg, working_directory=root)
    observed["sandbox_before_engine"] = runtime.context.execution_sandbox_policy.kind
    with patch("deepseek_tui.integrations.skills.discover_in_workspace", return_value=SkillRegistry()):
        engine = await Engine.create(handle=EngineHandle(), client=AsyncMock(), config=cfg,
                                     working_directory=root, tool_runtime=runtime)
    try:
        observed["sandbox_after_engine"] = engine.tool_context.execution_sandbox_policy.kind
    finally:
        await engine.shutdown_session()
        await runtime.shutdown()
    assert observed["sandbox_before_engine"] == "read-only"
    assert observed["sandbox_after_engine"] == "workspace-write"

    runtime = await create_tool_runtime(config=config(approval_policy="auto", sandbox_mode="read-only"),
                                        working_directory=root)
    try:
        observed["auto_with_explicit_readonly"] = dict(trust=runtime.context.trust_mode,
            sandbox=runtime.context.execution_sandbox_policy.kind)
    finally:
        await runtime.shutdown()
    assert observed["auto_with_explicit_readonly"] == {"trust": True, "sandbox": "danger-full-access"}

    # Hard never vs main cache and child handler. All tool executions mocked.
    call = ToolCall(id="probe", name="write_file", arguments={"path": "note.txt", "content": "x"})
    gate = ToolExecutionMixin()
    gate.tool_context = ToolContext(working_directory=root)
    gate.handle = SimpleNamespace(emit=AsyncMock())
    gate.approval_handler = DenyApprovalHandler()
    gate.approval_cache = ApprovalCache()
    gate.approval_cache.insert(build_approval_key(call.name, call.arguments, working_directory=root), True)
    request = approval_request_for_tool(WriteFileTool(), "never")
    observed["main_never_cached_denied"] = await gate._handle_approval_flow(call, request)
    assert observed["main_never_cached_denied"] is False
    children = {}
    for label, handler in (("manual_allow", ManualAllow()), ("auto_allow", AutoApprovalHandler())):
        registry = ToolRegistry()
        registry.register(WriteFileTool())
        registry.execute = AsyncMock(return_value=ToolResult(success=True, content="mock-only"))
        await _execute_subagent_tool(registry, ToolContext(working_directory=root),
            tool_name=call.name, tool_input=call.arguments, auto_approve=False, tool_call_id="probe",
            runtime=SimpleNamespace(config=SimpleNamespace(approval_policy="never"),
                                    approval_handler=handler, emit_event=AsyncMock()))
        children[label] = registry.execute.await_count
    observed["child_never_execution_count"] = children
    assert children == {"manual_allow": 1, "auto_allow": 1}

    # Capture the context made by the real child loop, stop before any LLM turn.
    class Captured(Exception):
        pass
    captured = []
    def capture_context(registry, context):
        captured.append(context)
        raise Captured
    cfg = config()
    cfg.features.exec_policy = True
    (root / "execpolicy.toml").write_text('[rules.probe]\ndeny=["printf blocked"]\n')
    parent_runtime = await create_tool_runtime(config=cfg, working_directory=root)
    try:
        observed["parent_context_has_command_policy"] = parent_runtime.context.policy is not None
        assert parent_runtime.context.policy is not None
    finally:
        await parent_runtime.shutdown()
    agent = SubAgent(SubAgentType.GENERAL, "probe", SubAgentAssignment(objective="probe"),
                     "deepseek-chat", None, None, "probe", workspace=root)
    child_runtime = SubAgentRuntime(manager=SimpleNamespace(), client=AsyncMock(),
        model="deepseek-chat", config=cfg, workspace=root, auto_approve=False)
    with patch("deepseek_tui.tools.registry.ToolRegistry.set_context", capture_context), \
         patch("deepseek_tui.tools.run_conversation.RunConversation", return_value=SimpleNamespace()):
        try:
            await run_subagent_loop(agent, child_runtime, asyncio.Event())
        except Captured:
            pass
    assert len(captured) == 1
    observed["child_context_has_command_policy"] = captured[0].policy is not None
    assert captured[0].policy is None

    # Approval fingerprints: changed execution scope is currently invisible.
    base = dict(name="n", prompt="p", schedule="0 9 * * *", cwds=["/project-a"], run_now=False)
    changes = dict(cwds=["/project-b"], timezone="America/New_York", run_now=True,
                   run_at="2027-01-01T00:00:00Z", paused=True)
    observed["cron_key_collisions"] = {
        key: build_approval_key("cron_create", base) == build_approval_key("cron_create", {**base, key: value})
        for key, value in changes.items()}
    assert all(observed["cron_key_collisions"].values())

    # Two different threads with a reused model tool-call id.
    bridge = ElevationBridge()
    def meta(thread):
        return PendingElevationRecord(thread_id=thread, tool_name="exec_shell", reason="probe",
                                      elevation_kind="network")
    first = bridge.register("same-id", meta=meta("thread-a"))
    second = bridge.register("same-id", meta=meta("thread-b"))
    bridge.resolve("same-id", True)
    observed["elevation_collision"] = dict(first_done=first.done(), second_done=second.done(),
                                            second_result=second.result())
    assert not first.done() and second.result() is True
    first.cancel()
    bridge.cancel_all()

    # Prompt publication precedes bridge registration. Cancel without waiting 600s.
    bridge = ElevationBridge()
    gate = ToolExecutionMixin()
    gate.mode = "agent"
    gate.tool_context = ToolContext(working_directory=root,
        metadata={"elevation_bridge": bridge, "runtime_thread_id": "thread"},
        execution_sandbox_policy=ExecutionSandboxPolicy.workspace_write(network_access=False))
    gate.approval_handler = DenyApprovalHandler()
    resolves = []
    async def emit(event):
        resolves.append(bridge.resolve(event.tool_call_id, True))
    gate.handle = SimpleNamespace(emit=emit)
    shell_call = ToolCall(id="early", name="exec_shell", arguments={"command": "echo probe"})
    result = ToolResult(success=False, content="denied", metadata={"sandbox_denied": True,
        "denial_message": "Sandbox blocked network access"})
    waiter = asyncio.create_task(gate._maybe_elevate_and_retry_tool(shell_call, [], "model", result))
    await asyncio.sleep(0)
    assert "early" in bridge._pending
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    observed["elevation_lifecycle"] = dict(early_answer=resolves[0],
        pending_storage=len(bridge._pending), metadata_storage=len(bridge._meta))
    assert resolves == [False] and len(bridge._pending) == 1 and len(bridge._meta) == 1
    bridge.cancel_all()

    elevated = suggest_elevation_policy(ExecutionSandboxPolicy.read_only(),
        "Sandbox blocked network access", workspace=root)
    observed["network_only_elevation_from_readonly"] = dict(kind=elevated.kind,
        label=elevation_kind_label(elevated))
    assert elevated.kind == "workspace-write" and elevation_kind_label(elevated) == "network"

    # No process is launched: inspect the prepared argv only.
    with patch("deepseek_tui.policy.sandbox.get_platform_sandbox", return_value=None):
        env = SandboxManager().prepare(CommandSpec.shell("echo probe", root, 1000)
            .with_policy(ExecutionSandboxPolicy.read_only()))
    observed["unavailable_sandbox"] = dict(sandboxed=env.is_sandboxed(), requested=env.policy.kind)
    assert not env.is_sandboxed() and env.policy.kind == "read-only"

    # Dormant unless an embedding caller injects a NetworkPolicyDecider.
    net = NetworkPolicyDecider(NetworkPolicy(deny=["blocked.invalid"]), audit_path=root / "audit.log")
    net.approve("blocked.invalid")
    observed["network_deny_after_cached_approval"] = net.evaluate("https://blocked.invalid").name
    assert observed["network_deny_after_cached_approval"] == "ALLOW"

    # Exercise fetch_url through an in-memory HTTP transport. No DNS or network.
    visits = []
    def respond(request):
        visits.append(str(request.url))
        if request.url.host == "allowed.invalid":
            return httpx.Response(302, headers={"location": "https://blocked.invalid/data.txt"})
        return httpx.Response(200, text="synthetic response")
    net = NetworkPolicyDecider(NetworkPolicy(allow=["allowed.invalid"], deny=["blocked.invalid"]),
                               audit_path=root / "redirect-audit.log")
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch("deepseek_tui.tools.web.httpx.AsyncClient", return_value=client), \
         patch("deepseek_tui.tools.web._reject_private_fetch_url"):
        fetched = await FetchUrlTool().execute({"url": "https://allowed.invalid/start.txt"},
                         ToolContext(working_directory=root, network_policy=net))
    observed["network_redirect"] = dict(success=fetched.success, visits=visits)
    assert fetched.success and visits[-1] == "https://blocked.invalid/data.txt"

    visits = []
    def extract_response(request):
        visits.append(str(request.url))
        return httpx.Response(200, json={"result": {"content": [{"type": "text", "text": "synthetic"}]}})
    net = NetworkPolicyDecider(NetworkPolicy(allow=["api.anysearch.com"], deny=["blocked.invalid"]),
                               audit_path=root / "extract-audit.log")
    client = httpx.AsyncClient(transport=httpx.MockTransport(extract_response))
    with patch("deepseek_tui.tools.web.httpx.AsyncClient", return_value=client), \
         patch("deepseek_tui.tools.web._reject_private_fetch_url"):
        fetched = await FetchUrlTool(anysearch_api_key="synthetic-key").execute(
            {"url": "https://blocked.invalid/page.html"}, ToolContext(working_directory=root, network_policy=net))
    observed["network_extract_target_not_checked"] = dict(success=fetched.success, visits=visits)
    assert fetched.success and visits == ["https://api.anysearch.com/mcp"]

    # No OS sandbox is claimed for a Python in-process file tool.
    context = ToolContext(working_directory=root, execution_sandbox_policy=ExecutionSandboxPolicy.read_only())
    result = await WriteFileTool().execute({"path": "synthetic-note.txt", "content": "synthetic only"}, context)
    observed["file_tool_under_readonly_shell_policy"] = result.success
    assert result.success
    return observed


async def main():
    with tempfile.TemporaryDirectory(prefix="permissions-review-") as tmp:
        root = Path(tmp)
        with patch.dict(os.environ, {"DEEPSEEK_HOME": str(root), "CLAUDE_PLUGINS_DIR": str(root / "plugins")}):
            observed = await probes(root)
    print(json.dumps(observed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
