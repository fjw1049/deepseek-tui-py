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


@pytest.mark.asyncio
async def test_cua_apps_lists_and_revokes_only_listed_identities(client, monkeypatch, tmp_path):
    import json

    calls = tmp_path / 'calls.txt'
    state = tmp_path / 'apps.json'
    state.write_text(json.dumps({'apps': [
        {'name': 'Notes', 'bundleId': 'com.apple.Notes', 'installed': True, 'risk': None,
         'blocked': False, 'extra': 'dropped'}], 'file': '/private/approvals.json'}))
    lcu = tmp_path / 'lcu'
    lcu.write_text(
        '#!/bin/sh\n'
        f'echo "$@" >> "{calls}"\n'
        f'if [ "$2" = revoke ]; then echo \'{{"apps": []}}\' > "{state}"; exit 0; fi\n'
        f'cat "{state}"\n'
    )
    lcu.chmod(0o755)
    monkeypatch.setattr(CuaSession, '_paths', staticmethod(lambda _: ('node', 'client', lcu)))

    listed = await client.get('/v1/cua/apps')
    assert listed.status_code == 200
    assert listed.json() == {'apps': [{'name': 'Notes', 'bundleId': 'com.apple.Notes',
                                       'installed': True, 'risk': None, 'blocked': False}]}
    rejected = await client.post('/v1/cua/apps/revoke', json={'app': '--unattended'})
    assert rejected.status_code == 400
    revoked = await client.post('/v1/cua/apps/revoke', json={'app': 'com.apple.Notes'})
    assert revoked.status_code == 200 and revoked.json() == {'apps': []}
    assert 'apps revoke com.apple.Notes' in calls.read_text()
    assert '--unattended' not in calls.read_text()
