"""Desktop handoff is host-owned and cannot race another conversation's input."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config.models import CuaConfig
from deepseek_tui.cua import session as sessions
from deepseek_tui.cua.session import CuaSession, DesktopLease, _code_fingerprint
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
        assert 'Use cua_observe before' in state.handle.resume_context
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
    await session.record_outcome('turn', 'submit', 'in_progress',
                                 code=_code_fingerprint({'code': 'submit()'}))
    assert session.unresolved is None
    recovered = CuaSession(CuaConfig(), tmp_path, 'different-session', owner_id='thread')
    assert recovered.unresolved['call_id'] == 'submit'
    result = {}
    assert recovered._annotate(result)
    assert 'unknown outcome' in result['content'][0]['text']


async def test_unknown_outcome_settles_once_the_model_is_told(desktop, tmp_path):
    _, _, session = desktop
    await session.record_outcome('turn', 'submit', 'unknown')
    result = {}
    assert session._annotate(result)
    assert 'operation panel' not in result['content'][0]['text']
    await session.record_outcome('turn2', 'next', 'returned', settle=True)
    assert session.unresolved is None
    # Settled for good: a restart does not bring it back, and later results stay quiet.
    reloaded = CuaSession(CuaConfig(), tmp_path, 'different-session', owner_id='thread')
    assert reloaded.unresolved is None
    later = {}
    assert not reloaded._annotate(later) and 'content' not in later


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


async def test_raising_the_app_flags_the_task_without_taking_control(desktop):
    manager, state, session = desktop
    try:
        result = manager.note_cua_app_raised('thread')
        assert result['owner'] == 'idle' and not state.handle.pause.paused
        assert 'front' in session.outside_change
        state.active_turn = None
        session.outside_change = ''
        manager.note_cua_app_raised('thread')  # A finished task has nothing to warn.
        assert session.outside_change == ''
    finally:
        await session.close()


async def test_resume_tells_the_model_what_the_host_knows_about_the_desktop(desktop, monkeypatch):
    from deepseek_tui.cua import apps

    monkeypatch.setattr(apps, 'on_screen_apps', lambda: ['com.apple.mail', 'com.apple.finder'])
    manager, state, session = desktop
    session.last_surface = {'kind': 'app', 'app_id': 'com.apple.TextEdit'}
    try:
        result = await manager.control_cua('thread', 'user', 0, 'turn')
        assert session.human_since is not None
        await manager.control_cua('thread', 'assistant', result['revision'], 'turn')
        context = state.handle.resume_context
        assert 'The user held the desktop for 0s and may have changed anything' in context
        assert 'Your last target was com.apple.TextEdit.' in context
        assert 'front to back: com.apple.mail, com.apple.finder.' in context
        assert 'Use cua_observe before' in context
        assert session.human_since is None
    finally:
        session.release_human()
        await session.close()


async def test_resume_notice_stands_without_desktop_facts(monkeypatch):
    from deepseek_tui.cua import apps
    from deepseek_tui.cua.tools import HANDOFF_NOTICE, handoff_notice

    monkeypatch.setattr(apps, 'on_screen_apps', lambda: [])
    notice = await handoff_notice(None, {'kind': 'browser'})
    assert notice == ('[The user held the desktop and may have changed anything on it, including '
                      'which app or window is in front. Your last target was the browser.]\n'
                      + HANDOFF_NOTICE)


def test_on_screen_apps_leaves_out_apps_computer_use_cannot_reach(monkeypatch):
    from deepseek_tui.cua import apps

    monkeypatch.setattr(apps.sys, 'platform', 'darwin')
    listed = '["com.xingyuzhong.deepseekgui", "com.apple.mail", "com.apple.Terminal"]'
    monkeypatch.setattr(apps.subprocess, 'run',
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=listed))
    assert apps.on_screen_apps() == ['com.apple.mail']


async def test_stop_ends_a_transfer_that_is_still_waiting_for_the_desktop(desktop, tmp_path):
    manager, state, session = desktop
    other = DesktopLease()
    await other.acquire(timeout=0.1)
    try:
        transfer = asyncio.create_task(manager.control_cua('thread', 'user', 0, 'turn'))
        await asyncio.sleep(0.05)
        assert session.human_reserved and session.control_lock.locked()

        async def cancel(reason):
            state.handle.cancel_event.set()
            transfer.cancel()

        state.handle.cancel = cancel
        result = await asyncio.wait_for(manager.control_cua('thread', 'stopped', 0, 'turn'), 2)
        assert result['owner'] == 'idle' and not session.human_reserved
        assert not state.handle.pause.paused
        await asyncio.gather(transfer, return_exceptions=True)
    finally:
        other.release()
        session.release_human()
        await session.close()


async def test_preview_frame_is_only_taken_between_calls_of_a_live_task(desktop):
    _, _, session = desktop
    session.process = SimpleNamespace(returncode=None)
    session._bound = True
    session.turn_id, session.runtime_turn_id = 'turn', 'turn:cua:1'
    session._request = AsyncMock(return_value={'image': {'data': 'AA=='}})
    assert await session.preview_frame() == {'data': 'AA=='}
    assert session._request.await_args.args == ('preview',)

    async with session.lock:
        assert await session.preview_frame() is None
    session.human_reserved = True
    assert await session.preview_frame() is None
    session.human_reserved = False
    session.turn_id = None
    assert await session.preview_frame() is None
    session.turn_id = 'turn'
    session._request.side_effect = ToolError('CUA preview timed out')
    assert await session.preview_frame() is None
    session.process = None


async def test_panel_frame_comes_from_the_session_that_acted_last(desktop):
    manager, state, session = desktop
    child = SimpleNamespace(last_activity=9, preview_frame=AsyncMock(return_value={'data': 'child'}))
    session.last_activity = 1
    state.engine.tool_context = SimpleNamespace(
        subagent_manager=SimpleNamespace(cua_sessions={'a': child}))
    assert await manager.cua_preview_frame('thread') == {'data': 'child'}
    state.active_turn = None
    assert await manager.cua_preview_frame('thread') is None


async def test_multiple_unknown_outcomes_survive_restart_and_individual_review(desktop, tmp_path):
    _, _, session = desktop
    await session.record_outcome('t', 'first', 'unknown')
    await session.record_outcome('t', 'second', 'unknown')
    await session.record_outcome('t', 'third', 'in_progress')
    import json
    receipt = json.loads(session.receipt_path.read_text())
    assert [r['call_id'] for r in receipt['unresolved']] == ['first', 'second']
    recovered = CuaSession(session.config, tmp_path, session.session_id, owner_id=session.lease.owner)
    for call_id in ('first', 'second', 'third'):
        assert recovered.unresolved['call_id'] == call_id
        await recovered.acknowledge(call_id)
    assert recovered.unresolved is None


def test_code_fingerprint_preserves_literal_whitespace():
    assert _code_fingerprint({'code': 'await app.typeText("a  b")'}) != _code_fingerprint(
        {'code': 'await app.typeText("a b")'})


async def test_external_panel_stop_wakes_idle_owner_and_preserves_other_app(desktop, tmp_path):
    _, state, session = desktop
    from deepseek_tui.cua.session import DesktopLease

    session.stop_task = state.handle.cancel
    session.lease.can_stop = True
    other = DesktopLease()
    await session.lease.acquire(app="com.soda.music")
    await other.acquire(app="com.apple.calculator")
    key = session.lease.info["key"]
    try:
        # A task between native calls still has a stop monitor.
        await session.run(lambda: asyncio.sleep(0), [state.handle.cancel_event])
        assert DesktopLease().signal(key, "stop")
        await asyncio.wait_for(state.handle.cancel_event.wait(), 2)
        await asyncio.wait_for(session._monitor, 2)
        assert session.lease.fd is None
        assert other.fd is not None and not other.stop_requested()
    finally:
        await session.close()
        other.release()


async def test_panel_stop_after_human_takeover_releases_waiter(desktop):
    manager, state, session = desktop
    session.stop_task = state.handle.cancel
    session.lease.can_stop = True
    other = DesktopLease()
    try:
        await session.run(lambda: asyncio.sleep(0), [state.handle.cancel_event])
        await manager.control_cua("thread", "user", 0, "turn")
        key = session.lease.info["key"]
        assert other.signal(key, "stop")
        await asyncio.wait_for(state.handle.cancel_event.wait(), 1.5)
        await other.acquire(app="com.soda.music", timeout=1)
        assert not session.human_reserved
        assert not other.signal(key, "stop")
    finally:
        other.release()
        session.release_human()
        await session.close()
