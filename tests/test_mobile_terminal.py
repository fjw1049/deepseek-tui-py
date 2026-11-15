"""PTY transport contract checks with isolated workspaces and no model calls."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from deepseek_tui.mobile import terminal as mobile_terminal


def app_for(root):
    app = FastAPI()
    app.state.thread_manager = SimpleNamespace(store=SimpleNamespace(load_thread=lambda _: SimpleNamespace(workspace=str(root))))
    app.include_router(mobile_terminal.router)
    return app


@pytest.mark.asyncio
async def test_create_requires_confirmation_and_pins_workspace(monkeypatch, tmp_path):
    app = app_for(tmp_path)
    calls = []
    async def call(self, payload):
        calls.append(payload)
        return {'id': 'test-session'}
    monkeypatch.setattr(mobile_terminal.TerminalBridge, 'call', call)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        denied = await client.post('/v1/threads/owner/terminal', json={})
        assert denied.status_code == 400 and not calls
        created = await client.post('/v1/threads/owner/terminal', json={'confirm': True, 'cwd': '/ignored'})
        assert created.status_code == 200
        assert calls[0]['cwd'] == str(tmp_path.resolve())
        assert calls[0]['thread_id'] == 'owner'
        invalid = await client.post('/v1/threads/owner/terminal/test-session/resize', json={'cols': 9999, 'rows': 0})
        assert invalid.status_code == 422
        excessive = await client.post('/v1/threads/owner/terminal/test-session/input', json={'data': 'x' * 8193})
        assert excessive.status_code == 422


@pytest.mark.asyncio
async def test_real_shared_pty_owner_resize_buffer_and_shutdown(tmp_path, monkeypatch):
    helper = os.environ.get('TEST_MOBILE_TERMINAL_HELPER')
    if not helper or not Path(helper).is_file():
        pytest.skip('Build the shared PTY helper and set TEST_MOBILE_TERMINAL_HELPER for isolated native test')
    monkeypatch.setenv('DEEPSEEK_MOBILE_TERMINAL_HELPER', helper)
    app = app_for(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            created = await client.post('/v1/threads/owner/terminal', json={'confirm': True})
            assert created.status_code == 200, created.text
            session = created.json()['id']
            path = f'/v1/threads/owner/terminal/{session}'
            other = await client.post(f'/v1/threads/other/terminal/{session}/input', json={'data': 'echo WRONG\r'})
            assert other.status_code == 409
            resized = await client.post(path + '/resize', json={'cols': 70, 'rows': 20})
            assert resized.status_code == 200
            await client.post(path + '/input', json={'data': "echo PTY_""OK; pwd\r"})
            output = ''
            for _ in range(40):
                response = await client.get(path)
                output = response.json()['text']
                if str(tmp_path.resolve()) in output and 'PTY_OK' in output:
                    break
                await asyncio.sleep(.05)
            assert str(tmp_path.resolve()) in output and 'PTY_OK' in output, output
            cursor = response.json()['offset']
            assert (await client.get(path, params={'offset': cursor})).json()['text'] == ''
            assert (await client.get(f'/v1/threads/other/terminal/{session}')).status_code == 409
            await client.post(path + '/input', json={'data': "printf '%070000d' 0\r"})
            for _ in range(60):
                bounded = (await client.get(path)).json()
                if bounded['truncated']:
                    break
                await asyncio.sleep(.05)
            assert bounded['truncated'] is True
            assert len(bounded['text']) <= 65536
            assert (await client.delete(path)).status_code == 200
            assert (await client.get(path)).status_code == 409
            process = app.state.mobile_terminal.process
    finally:
        await mobile_terminal.close_mobile_terminals(app)
    assert process.returncode is not None
