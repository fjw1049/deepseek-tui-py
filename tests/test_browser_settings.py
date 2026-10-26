"""Browser settings enforce control without disabling manual browsing or other grants."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.browser.service import BrowserAction, BrowserService
from deepseek_tui.tools.approval import ApprovalCache, ApprovalCacheStatus, build_approval_key
from deepseek_tui.server.threads.manager import RuntimeThreadManager


async def test_disabled_agent_is_persistent_and_manual_status_still_works(tmp_path):
    service = BrowserService(tmp_path / 'artifacts')
    service.configure_agent(False)
    restarted = BrowserService(service.artifact_root)
    with pytest.raises(ValueError, match='disabled'):
        await restarted.action('t', BrowserAction(action='open', url='https://example.com'))
    assert not restarted.runs
    result = await restarted.action('t', BrowserAction(action='status'), actor='user')
    assert result['success']
    restarted.configure_agent(True)
    assert restarted.agent_settings()['agent_enabled']


async def test_cannot_disable_during_a_dispatched_action(tmp_path):
    import asyncio
    service = BrowserService(tmp_path)
    lock = asyncio.Lock()
    service.runs['t'] = SimpleNamespace(lock=lock, transferring=False, demo_status='idle')
    async with lock:
        with pytest.raises(ValueError, match='finish'):
            service.configure_agent(False)
    assert service.agent_settings()['agent_enabled']


def test_revoking_site_does_not_revoke_other_sites_or_shell():
    cache = ApprovalCache()
    first = build_approval_key('browser_use', {'browser_site': 'https://a.test'})
    second = build_approval_key('browser_use', {'browser_site': 'https://b.test'})
    shell = build_approval_key('shell', {'command': 'pwd'})
    cache.insert(first, True, 'https://a.test')
    cache.insert(second, True, 'https://b.test')
    cache.insert(shell, True)
    cache.revoke_browser_site('https://a.test')
    assert cache.check(first) == ApprovalCacheStatus.UNKNOWN
    assert cache.check(second) == cache.check(shell) == ApprovalCacheStatus.APPROVED
    assert cache.browser_sites() == ['https://b.test']


def test_manager_refuses_revocation_while_task_is_active():
    cache = ApprovalCache()
    key = build_approval_key('browser_use', {'browser_site': 'https://a.test'})
    cache.insert(key, True, 'https://a.test')
    state = SimpleNamespace(engine=SimpleNamespace(approval_cache=cache), active_turn=object())
    manager = SimpleNamespace(_active={'t': state}, store=SimpleNamespace(load_thread=lambda _: SimpleNamespace(title='Example')))
    with pytest.raises(ValueError, match='Stop'):
        RuntimeThreadManager.revoke_browser_site(manager, 't', 'https://a.test')
    assert RuntimeThreadManager.browser_site_grants(manager) == [{'thread_id': 't', 'thread_title': 'Example', 'site': 'https://a.test'}]
    state.active_turn = None
    RuntimeThreadManager.revoke_browser_site(manager, 't', 'https://a.test')
    assert RuntimeThreadManager.browser_site_grants(manager) == []


async def test_real_approval_gate_remembers_site_and_asks_again_after_revoke(tmp_path):
    from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.tools.approval import ApprovalDecision, ApprovalRequest, RiskLevel, ToolCategory
    from deepseek_tui.tools.registry import ToolContext
    gate = ToolExecutionMixin()
    gate.tool_context = ToolContext(working_directory=tmp_path, metadata={
        'browser_service': BrowserService(tmp_path), 'runtime_thread_id': 't'})
    gate.approval_cache = ApprovalCache()
    gate.handle = SimpleNamespace(emit=AsyncMock())
    gate.approval_handler = SimpleNamespace(auto_approve_enabled=AsyncMock(return_value=False),
        request_approval=AsyncMock(return_value=ApprovalDecision.APPROVED_SESSION))
    async def ask():
        request = ApprovalRequest(tool_name='browser_use', risk_level=RiskLevel.MEDIUM,
                                  category=ToolCategory.NETWORK, reason='Browser')
        return await gate._handle_approval_flow(ToolCall(id='1', name='browser_use',
            arguments={'action': 'open', 'url': 'https://example.com'}), request)
    assert not await ask()
    assert gate.approval_cache.browser_sites() == ['https://example.com']
    assert not await ask()
    assert gate.approval_handler.request_approval.await_count == 1
    gate.approval_cache.revoke_browser_site('https://example.com')
    assert not await ask()
    assert gate.approval_handler.request_approval.await_count == 2
