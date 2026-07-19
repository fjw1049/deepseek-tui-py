"""L3 elevation bridge + /v1/jobs snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.server.approval import (
    ElevationBridge,
    PendingElevationRecord,
)
from deepseek_tui.policy.sandbox import (
    ExecutionSandboxPolicy,
    elevation_kind_label,
    suggest_elevation_policy,
)
from deepseek_tui.engine.events import ElevationRequiredEvent
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.tools.registry import ToolResult


class TestSuggestElevationPolicy:
    def test_network_denial_enables_network(self, tmp_path: Path) -> None:
        policy = ExecutionSandboxPolicy.workspace_write(
            writable_roots=(tmp_path.resolve(),),
            network_access=False,
        )
        elevated = suggest_elevation_policy(
            policy,
            "Sandbox blocked network access",
            workspace=tmp_path,
        )
        assert elevated is not None
        assert elevated.has_network_access()
        assert elevation_kind_label(elevated) == "network"

    def test_full_access_offers_no_further_elevation(self, tmp_path: Path) -> None:
        policy = ExecutionSandboxPolicy.danger_full_access()
        assert (
            suggest_elevation_policy(policy, "Sandbox blocked", workspace=tmp_path)
            is None
        )


class TestElevationBridge:
    @pytest.mark.asyncio
    async def test_resolve_unblocks_waiter(self) -> None:
        bridge = ElevationBridge()
        fut = bridge.register(
            "tc1",
            meta=PendingElevationRecord(
                thread_id="th1",
                tool_name="exec_shell",
                reason="network",
                elevation_kind="network",
            ),
        )
        assert bridge.resolve("tc1", True)
        assert await fut is True


class TestEngineSandboxDeniedDetection:
    def test_detects_metadata_flag(self) -> None:
        result = ToolResult(
            success=False,
            content="denied",
            metadata={"sandbox_denied": True},
        )
        assert Engine._is_sandbox_denied_tool_result("exec_shell", result)
        assert not Engine._is_sandbox_denied_tool_result("read_file", result)


class TestElevationEvent:
    def test_fields(self) -> None:
        ev = ElevationRequiredEvent(
            tool_call_id="tc",
            tool_name="exec_shell",
            reason="blocked",
            elevation_kind="network",
            command_preview="curl example.com",
        )
        assert ev.elevation_kind == "network"
