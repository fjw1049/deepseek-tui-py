"""Desktop handoff is host-owned and cannot race another conversation's input."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import CuaConfig
from deepseek_tui.cua import session as sessions
from deepseek_tui.cua.session import CuaSession, DesktopLease
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.server.threads.manager import RuntimeThreadManager
from deepseek_tui.tools.registry import ToolError


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, 'LOCK_DIR', tmp_path)
    monkeypatch.setenv('DEEPSEEK_HOME', str(tmp_path / 'home'))
    manager = RuntimeThreadManager.__new__(RuntimeThreadManager)
    manager._active_lock = asyncio.Lock()
    manager._pending_user_inputs = {}
    handle = EngineHandle()
    session = CuaSession(CuaConfig(), tmp_path, 'session', owner_id='thread')
    session.turn_used = True  # The running turn has called computer use.
    state = SimpleNamespace(handle=handle, active_turn=SimpleNamespace(turn_id='turn'),
                            engine=SimpleNamespace(_cua_session=session, reply_locale='en'))
    manager._active = {'thread': state}
    return manager, state, session


async def test_transfer_holds_desktop_until_explicit_return(desktop):
    manager, state, session = desktop
    other = DesktopLease()
    try:
        result = await manager.control_cua('thread', 'user', 0, 'turn')
        assert result['owner'] == 'user' and state.handle.pause.paused
        assert result['holder']['thread_id'] == 'thread'
        with pytest.raises(ToolError, match='desktop is in use'):
            await other.acquire(timeout=0.01)
        with pytest.raises(ValueError, match='changed'):
            await manager.control_cua('thread', 'assistant', 0, 'turn')
        await manager.control_cua('thread', 'assistant', result['revision'], 'turn')
        assert not state.handle.pause.paused
        assert 'observe again' in state.handle.resume_context
        await other.acquire(timeout=0.1)
    finally:
        other.release()
        session.release_human()
        await session.close()


async def test_failed_takeover_keeps_task_paused_without_claiming_user_control(desktop):
    manager, state, session = desktop
    session.reserve_human = AsyncMock(side_effect=ToolError('desktop busy'))
    with pytest.raises(ToolError):
        await manager.control_cua('thread', 'user', 0, 'turn')
    assert state.handle.pause.paused
    assert manager.cua_task_state('thread')['owner'] == 'idle'


async def test_old_turn_cannot_pause_new_work(desktop):
    manager, state, _ = desktop
    with pytest.raises(ValueError, match='original task'):
        await manager.control_cua('thread', 'user', 0, 'old-turn')
    assert not state.handle.pause.paused


async def test_review_is_bound_to_receipt_and_survives_task_end(desktop):
    manager, state, session = desktop
    await session.record_outcome('turn', 'submit', 'unknown')
    state.active_turn = None
    with pytest.raises(ToolError, match='changed'):
        await manager.control_cua(
            'thread', 'assistant', session.control_revision, 'turn', 'different'
        )
    assert session.unresolved
    result = await manager.control_cua(
        'thread', 'assistant', session.control_revision, 'turn', 'submit'
    )
    assert result['unresolved'] is None
    assert not result['active']


async def test_stop_releases_human_reservation(desktop):
    manager, state, session = desktop
    await manager.control_cua('thread', 'user', 0, 'turn')
    await manager.control_cua('thread', 'stopped', session.control_revision, 'turn')
    assert state.handle.cancel_event.is_set()
    assert session.lease.fd is None and not session.human_reserved


async def test_panel_continue_resolves_existing_manual_request(desktop):
    manager, state, session = desktop
    await session.reserve_human('Log in', 'request')
    future = asyncio.get_running_loop().create_future()
    state.handle.pending_user_inputs['request'] = future
    try:
        await manager.control_cua('thread', 'assistant', session.control_revision, 'turn')
        assert future.result() == {'answers': [{'question_id': 'desktop_action', 'label': 'Done'}]}
        # The waiting tool releases the reservation; the UI must not fabricate it.
        assert session.human_reserved
    finally:
        session.release_human()


async def test_crash_during_dispatched_call_restores_uncertainty(desktop, tmp_path):
    _, _, session = desktop
    await session.record_outcome('turn', 'submit', 'in_progress')
    assert session.unresolved is None
    recovered = CuaSession(CuaConfig(), tmp_path, 'different-session', owner_id='thread')
    assert recovered.unresolved['call_id'] == 'submit'
    with pytest.raises(ToolError, match='unknown outcome'):
        await recovered.call('js', {'code': 'submit again'}, 'turn2', 'call2')


async def test_child_uncertainty_is_reviewable_from_parent(desktop, tmp_path):
    manager, state, parent = desktop
    child = CuaSession(CuaConfig(), tmp_path, 'child')
    await child.record_outcome('child-turn', 'child-submit', 'unknown')
    state.engine.tool_context = SimpleNamespace(
        subagent_manager=SimpleNamespace(cua_sessions={'child': child})
    )
    snapshot = manager.cua_task_state('thread')
    assert snapshot['unresolved']['call_id'] == 'child-submit'
    await manager.control_cua('thread', 'user', snapshot['revision'], 'turn')
    try:
        snapshot = manager.cua_task_state('thread')
        await manager.control_cua(
            'thread', 'assistant', snapshot['revision'], 'turn', 'child-submit'
        )
        assert child.unresolved is None and not parent.human_reserved
    finally:
        parent.release_human()


async def test_transfer_does_not_claim_user_control_until_native_close(desktop):
    manager, _, session = desktop
    closing = asyncio.Event()
    finish = asyncio.Event()

    async def close():
        closing.set()
        await finish.wait()

    session.close = close
    transfer = asyncio.create_task(manager.control_cua('thread', 'user', 0, 'turn'))
    try:
        await closing.wait()
        snapshot = manager.cua_task_state('thread')
        assert snapshot['transferring'] and snapshot['owner'] != 'user'
        finish.set()
        assert (await transfer)['owner'] == 'user'
    finally:
        finish.set()
        await transfer
        session.release_human()


async def test_stop_and_takeover_do_not_lose_the_race_with_running_calls(desktop):
    manager, state, session = desktop
    polled = manager.cua_task_state('thread')['revision']
    # A call started between the panel's poll and the click.
    await session.record_outcome('turn', 'call-1', 'in_progress')
    try:
        assert (await manager.control_cua('thread', 'user', polled, 'turn'))['owner'] == 'user'
        await manager.control_cua('thread', 'stopped', polled, 'turn')
        assert state.handle.cancel_event.is_set()
    finally:
        session.release_human()


async def test_resume_still_requires_the_current_revision(desktop):
    manager, state, session = desktop
    result = await manager.control_cua('thread', 'user', 0, 'turn')
    try:
        with pytest.raises(ValueError, match='changed'):
            await manager.control_cua('thread', 'assistant', result['revision'] - 1, 'turn')
        assert state.handle.pause.paused
    finally:
        session.release_human()


async def test_takeover_is_refused_for_a_turn_without_computer_use(desktop):
    manager, state, session = desktop
    session.turn_used = False
    session.last_activity = 1.0  # An earlier turn used it.
    snapshot = manager.cua_task_state('thread')
    assert not snapshot['used']
    with pytest.raises(ValueError, match='not using computer control'):
        await manager.control_cua('thread', 'user', snapshot['revision'], 'turn')
    assert not state.handle.pause.paused and session.lease.fd is None


async def test_assistance_return_reviews_unknown_outcome_first(desktop):
    manager, state, session = desktop
    await session.reserve_human('Log in', 'request')
    future = asyncio.get_running_loop().create_future()
    state.handle.pending_user_inputs['request'] = future
    try:
        await session.record_outcome('turn', 'submit', 'unknown')
        with pytest.raises(ValueError, match='uncertain'):
            await manager.control_cua(
                'thread', 'assistant', manager.cua_task_state('thread')['revision'], 'turn')
        assert not future.done()
        await manager.control_cua(
            'thread', 'assistant', manager.cua_task_state('thread')['revision'], 'turn', 'submit')
        assert session.unresolved is None and future.done()
    finally:
        session.release_human()


async def test_assistance_waits_until_every_child_outcome_is_reviewed(desktop, tmp_path):
    manager, state, session = desktop
    first = CuaSession(CuaConfig(), tmp_path, 'child-a')
    second = CuaSession(CuaConfig(), tmp_path, 'child-b')
    await first.record_outcome('a', 'call-a', 'unknown')
    await second.record_outcome('b', 'call-b', 'unknown')
    state.engine.tool_context = SimpleNamespace(
        subagent_manager=SimpleNamespace(cua_sessions={'a': first, 'b': second}))
    await session.reserve_human('Log in', 'request')
    future = asyncio.get_running_loop().create_future()
    state.handle.pending_user_inputs['request'] = future
    try:
        snapshot = manager.cua_task_state('thread')
        await manager.control_cua('thread', 'assistant', snapshot['revision'], 'turn',
                                  snapshot['unresolved']['call_id'])
        assert not future.done()
        snapshot = manager.cua_task_state('thread')
        await manager.control_cua('thread', 'assistant', snapshot['revision'], 'turn',
                                  snapshot['unresolved']['call_id'])
        assert future.done() and not first.unresolved and not second.unresolved
    finally:
        session.release_human()


async def test_failed_takeover_keeps_the_running_call_lease(desktop):
    _, _, session = desktop
    await session.lease.acquire()
    other = DesktopLease()
    try:
        async with session.lock:  # A call is still running.
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(session.reserve_human(), timeout=0.05)
            assert session.lease.fd is not None and not session.human_reserved
            with pytest.raises(ToolError, match='desktop is in use'):
                await other.acquire(timeout=0.01)
    finally:
        other.release()
        session.lease.release()
