import pytest
from deepseek_tui.cua.session import CuaSession
from deepseek_tui.tools.registry import ToolError


@pytest.mark.asyncio
@pytest.mark.parametrize('installed', [False, True])
async def test_cua_status_checks_files_without_connecting(client, monkeypatch, installed):
    def paths(_installation):
        if not installed:
            raise ToolError('missing')
        return 'node', 'client', 'lcu'

    async def no_connect(*args):
        pytest.fail('Status must not connect to the desktop')

    monkeypatch.setattr('sys.platform', 'darwin')
    monkeypatch.setattr(CuaSession, '_paths', staticmethod(paths))
    monkeypatch.setattr(CuaSession, 'connect', no_connect)
    response = await client.get('/v1/cua/status')
    assert response.status_code == 200
    assert response.json() == {'supported': True, 'installed': installed, 'enabled': False}
