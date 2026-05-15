"""Parity tests for Sub-agent manager + mailbox (Stage 3.2).

Mirror of Rust ``crates/tui/src/tools/subagent/{mod,mailbox,tests}.rs``
(3,604 + 478 + 1,309 lines). Covers:

- SubAgentType alias parsing (Rust ``SubAgentType::from_str``)
- SubAgentStatus discriminants (Running/Completed/Interrupted/Failed/Cancelled)
- SubAgentManager.spawn/cancel/resume/close round-trips
- list filter behavior against prior-session session_boot_id
- persistence + reload (Running → Interrupted)
- Mailbox monotonic seq + cancel-on-close semantics
- wait mode: any / all / first
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from deepseek_tui.tools.subagent import (
    Mailbox,
    MailboxMessage,
    MailboxMessageKind,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentStatus,
    SubAgentStatusKind,
    SubAgentType,
)


class TestSubAgentType:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("general", SubAgentType.GENERAL),
            ("general-purpose", SubAgentType.GENERAL),
            ("general_purpose", SubAgentType.GENERAL),
            ("worker", SubAgentType.GENERAL),
            ("explorer", SubAgentType.EXPLORE),
            ("code-review", SubAgentType.REVIEW),
            ("tester", SubAgentType.VERIFIER),
            ("implement", SubAgentType.IMPLEMENTER),
            ("custom", SubAgentType.CUSTOM),
        ],
    )
    def test_parse_aliases(self, raw: str, expected: SubAgentType) -> None:
        assert SubAgentType.parse(raw) is expected

    def test_parse_unknown_returns_none(self) -> None:
        assert SubAgentType.parse("nonsense") is None


class TestSubAgentStatus:
    def test_terminal_states(self) -> None:
        assert SubAgentStatus.running().is_terminal() is False
        assert SubAgentStatus.completed().is_terminal() is True
        assert SubAgentStatus.failed("boom").is_terminal() is True
        assert SubAgentStatus.cancelled().is_terminal() is True
        assert SubAgentStatus.interrupted("ctrl-c").is_terminal() is True

    def test_roundtrip_dict(self) -> None:
        status = SubAgentStatus.failed("boom")
        data = status.to_dict()
        reconstructed = SubAgentStatus.from_dict(data)
        assert reconstructed.kind is SubAgentStatusKind.FAILED
        assert reconstructed.message == "boom"


class TestMailbox:
    async def test_monotonic_seq(self) -> None:
        mb = Mailbox()
        mb.send(MailboxMessage.started("a", "general"))
        mb.send(MailboxMessage.progress("a", "thinking"))
        mb.send(MailboxMessage.completed("a", "done"))
        drained = await mb.drain_available()
        assert [e.seq for e in drained] == [1, 2, 3]
        kinds = [e.message.kind for e in drained]
        assert kinds == [
            MailboxMessageKind.STARTED,
            MailboxMessageKind.PROGRESS,
            MailboxMessageKind.COMPLETED,
        ]

    async def test_close_sets_cancel_token(self) -> None:
        mb = Mailbox()
        assert mb.cancel_token.is_set() is False
        mb.close()
        assert mb.is_closed() is True
        assert mb.cancel_token.is_set() is True

    async def test_send_after_close_returns_false(self) -> None:
        mb = Mailbox()
        mb.close()
        assert mb.send(MailboxMessage.progress("a", "x")) is False

    async def test_child_spawned_keys_on_child(self) -> None:
        msg = MailboxMessage.child_spawned("parent", "child")
        assert msg.agent_id == "child"
        assert msg.parent_id == "parent"


@pytest_asyncio.fixture
async def manager(tmp_path: Path) -> AsyncIterator[SubAgentManager]:
    mb = Mailbox()
    mgr = SubAgentManager(
        workspace=tmp_path,
        state_path=tmp_path / "subagents.v1.json",
        mailbox=mb,
    )
    try:
        yield mgr
    finally:
        await mgr.shutdown()


def _spawn_request(
    prompt: str = "explore", agent_type: SubAgentType = SubAgentType.GENERAL
) -> SpawnRequest:
    return SpawnRequest(
        prompt=prompt,
        agent_type=agent_type,
        assignment=SubAgentAssignment(objective=prompt),
    )


class TestSpawnAndComplete:
    async def test_spawn_assigns_agent_id(self, manager: SubAgentManager) -> None:
        snap = await manager.spawn(_spawn_request())
        assert snap.agent_id.startswith("agent_")
        assert len(snap.agent_id) == len("agent_") + 8

    async def test_stub_executor_completes(self, manager: SubAgentManager) -> None:
        snap = await manager.spawn(_spawn_request("hello"))
        for _ in range(50):
            snap = await manager.get_result(snap.agent_id)
            if snap.status.is_terminal():
                break
            await asyncio.sleep(0.05)
        assert snap.status.kind is SubAgentStatusKind.COMPLETED
        assert snap.result is not None
        assert "[stub]" in snap.result

    async def test_max_agents_cap(self, tmp_path: Path) -> None:
        async def never_finish(_agent, cancel):
            await cancel.wait()
            return ""

        mgr = SubAgentManager(
            workspace=tmp_path, max_agents=2, executor=never_finish
        )
        try:
            await mgr.spawn(_spawn_request("a"))
            await mgr.spawn(_spawn_request("b"))
            with pytest.raises(RuntimeError, match="Too many sub-agents"):
                await mgr.spawn(_spawn_request("c"))
        finally:
            await mgr.shutdown()


class TestCancelResumeClose:
    async def test_cancel_blocks_completion(self, tmp_path: Path) -> None:
        async def slow_executor(_agent, cancel):
            await asyncio.wait_for(cancel.wait(), timeout=5.0)
            raise asyncio.CancelledError

        mgr = SubAgentManager(workspace=tmp_path, executor=slow_executor)
        try:
            snap = await mgr.spawn(_spawn_request())
            await asyncio.sleep(0.02)
            final = await mgr.cancel(snap.agent_id)
            assert final.status.kind is SubAgentStatusKind.CANCELLED
        finally:
            await mgr.shutdown()

    async def test_close_removes_from_list(self, manager: SubAgentManager) -> None:
        snap = await manager.spawn(_spawn_request())
        await manager.close(snap.agent_id)
        listing = manager.list_agents()
        assert all(a.agent_id != snap.agent_id for a in listing)

    async def test_resume_from_terminal(self, manager: SubAgentManager) -> None:
        snap = await manager.spawn(_spawn_request("original"))
        # Wait until done
        for _ in range(50):
            got = await manager.get_result(snap.agent_id)
            if got.status.is_terminal():
                break
            await asyncio.sleep(0.05)
        resumed = await manager.resume(snap.agent_id)
        assert resumed.status.kind is SubAgentStatusKind.RUNNING


class TestListFiltering:
    async def test_list_excludes_prior_session_by_default(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "agents": [
                        {
                            "id": "agent_oldsess",
                            "agent_type": "general",
                            "prompt": "old",
                            "assignment": {"objective": "old", "role": None},
                            "model": "m",
                            "nickname": None,
                            "status": {"kind": "completed"},
                            "result": "done",
                            "steps_taken": 1,
                            "duration_ms": 0,
                            "allowed_tools": [],
                            "updated_at_ms": 0,
                            "session_boot_id": "boot_old",
                        }
                    ],
                }
            )
        )
        mgr = SubAgentManager(workspace=tmp_path, state_path=state_path)
        try:
            assert mgr.list_agents() == []
            archived = mgr.list_filtered(include_archived=True)
            assert len(archived) == 1
            assert archived[0].from_prior_session is True
        finally:
            await mgr.shutdown()


class TestPersistenceReload:
    async def test_running_on_disk_becomes_interrupted(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "agents": [
                        {
                            "id": "agent_restart1",
                            "agent_type": "general",
                            "prompt": "ongoing",
                            "assignment": {"objective": "ongoing", "role": None},
                            "model": "m",
                            "nickname": None,
                            "status": {"kind": "running"},
                            "result": None,
                            "steps_taken": 3,
                            "duration_ms": 1000,
                            "allowed_tools": [],
                            "updated_at_ms": 0,
                            "session_boot_id": "boot_prev",
                        }
                    ],
                }
            )
        )
        mgr = SubAgentManager(workspace=tmp_path, state_path=state_path)
        try:
            archived = mgr.list_filtered(include_archived=True)
            assert len(archived) == 1
            status = archived[0].status
            assert status.kind is SubAgentStatusKind.INTERRUPTED
            assert (
                status.message
                == "Interrupted by process restart"
            )
        finally:
            await mgr.shutdown()

    async def test_schema_mismatch_raises(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text(
            json.dumps({"schema_version": 99, "agents": []})
        )
        with pytest.raises(RuntimeError, match="Unsupported"):
            SubAgentManager(workspace=tmp_path, state_path=state_path)


class TestWaitMode:
    async def test_wait_any_returns_when_first_terminal(
        self, tmp_path: Path
    ) -> None:
        # Executor that sleeps for (i+1)*0.1 seconds by agent order
        spawn_counter = {"i": 0}

        async def indexed_executor(agent, cancel):
            idx = spawn_counter["i"]
            spawn_counter["i"] += 1
            try:
                await asyncio.wait_for(cancel.wait(), timeout=0.1 * (idx + 1))
            except asyncio.TimeoutError:
                return f"done-{idx}"
            raise asyncio.CancelledError

        mgr = SubAgentManager(workspace=tmp_path, executor=indexed_executor)
        try:
            a = await mgr.spawn(_spawn_request("fast"))
            b = await mgr.spawn(_spawn_request("slow"))
            results = await mgr.wait(
                [a.agent_id, b.agent_id], mode="any", timeout_ms=5000
            )
            # At least one terminal.
            assert any(r.status.is_terminal() for r in results)
        finally:
            await mgr.shutdown()

    async def test_wait_all_blocks_until_all(self, manager: SubAgentManager) -> None:
        a = await manager.spawn(_spawn_request("a"))
        b = await manager.spawn(_spawn_request("b"))
        results = await manager.wait(
            [a.agent_id, b.agent_id], mode="all", timeout_ms=5000
        )
        assert all(r.status.is_terminal() for r in results)

    async def test_wait_unknown_mode_raises(self, manager: SubAgentManager) -> None:
        a = await manager.spawn(_spawn_request())
        with pytest.raises(ValueError):
            await manager.wait([a.agent_id], mode="nonsense", timeout_ms=1000)


class TestSpawnDepth:
    """``DEFAULT_MAX_SPAWN_DEPTH`` must be enforced on the main spawn path,
    not just on the (currently unused) ``SubAgentRuntime.child`` helper.

    Mirrors Rust ``SubAgentManager::spawn`` (mod.rs:~750) where a child's
    ``parent.spawn_depth + 1`` is rejected past the cap.
    """

    async def test_top_level_spawn_records_depth_one(
        self, manager: SubAgentManager
    ) -> None:
        snap = await manager.spawn(_spawn_request("root"))
        agent = manager._agents[snap.agent_id]
        assert agent.spawn_depth == 1

    async def test_nested_spawn_increments_depth(
        self, manager: SubAgentManager
    ) -> None:
        from deepseek_tui.tools.subagent.manager import DEFAULT_MAX_SPAWN_DEPTH

        # parent_depth=1 → child depth 2, still ≤ cap
        req = _spawn_request("nested")
        req = SpawnRequest(
            prompt=req.prompt,
            agent_type=req.agent_type,
            assignment=req.assignment,
            parent_depth=1,
        )
        snap = await manager.spawn(req)
        agent = manager._agents[snap.agent_id]
        assert agent.spawn_depth == 2
        assert DEFAULT_MAX_SPAWN_DEPTH >= 2

    async def test_spawn_at_cap_is_rejected(
        self, manager: SubAgentManager
    ) -> None:
        from deepseek_tui.tools.subagent.manager import DEFAULT_MAX_SPAWN_DEPTH

        # parent_depth = cap → child = cap+1 → reject
        req = SpawnRequest(
            prompt="too-deep",
            agent_type=SubAgentType.GENERAL,
            assignment=SubAgentAssignment(objective="too-deep"),
            parent_depth=DEFAULT_MAX_SPAWN_DEPTH,
        )
        with pytest.raises(RuntimeError, match="max sub-agent spawn depth"):
            await manager.spawn(req)

    async def test_spawn_depth_persists_across_reload(self, tmp_path: Path) -> None:
        state_path = tmp_path / "subagents.json"
        mgr = SubAgentManager(workspace=tmp_path, state_path=state_path)
        try:
            req = SpawnRequest(
                prompt="persist-me",
                agent_type=SubAgentType.GENERAL,
                assignment=SubAgentAssignment(objective="persist-me"),
                parent_depth=1,
            )
            snap = await mgr.spawn(req)
            agent_id = snap.agent_id
            await asyncio.sleep(0.1)  # let executor finish so persisted record is final
        finally:
            await mgr.shutdown()

        mgr2 = SubAgentManager(workspace=tmp_path, state_path=state_path)
        try:
            assert mgr2._agents[agent_id].spawn_depth == 2
        finally:
            await mgr2.shutdown()
