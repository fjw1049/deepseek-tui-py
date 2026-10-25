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
    data = response.json()
    assert {k: data[k] for k in ('supported', 'installed', 'enabled')} == {
        'supported': True, 'installed': installed, 'enabled': False,
    }
    assert data['readiness'] == 'needs_setup'
    assert data['permissions'] == 'unknown'
    assert data['connection'] == 'unchecked'


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


@pytest.mark.asyncio
async def test_cua_permissions_name_entries_and_open_only_listed_ones(
    client, monkeypatch, tmp_path
):
    import asyncio

    helper = '/Applications/ChatGPT.app/Contents/Resources/x/Codex Computer Use.app'
    lcu = tmp_path / 'lcu'
    lcu.write_text(
        '#!/bin/sh\n'
        'echo "Review these entries in System Settings > Privacy & Security:"\n'
        f'echo "  Accessibility: ChatGPT Computer Use ({helper})"\n'
        'echo "  Screen & System Audio Recording, or Screen Recording: '
        'ChatGPT (/Applications/ChatGPT.app)"\n'
    )
    lcu.chmod(0o755)
    monkeypatch.setattr('sys.platform', 'darwin')
    monkeypatch.setattr(CuaSession, '_paths', staticmethod(lambda _: ('node', 'client', lcu)))
    opened = []
    real_exec = asyncio.create_subprocess_exec

    async def exec_(program, *args, **kwargs):
        if program == 'open':
            opened.append(list(args))
            return await real_exec('true')
        return await real_exec(program, *args, **kwargs)

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', exec_)

    listed = await client.get('/v1/cua/permissions')
    assert listed.json() == {'permissions': [
        {'id': 'accessibility', 'name': 'ChatGPT Computer Use', 'path': helper},
        {'id': 'screen', 'name': 'ChatGPT', 'path': '/Applications/ChatGPT.app'},
    ]}
    unknown = await client.post('/v1/cua/permissions/open', json={'id': '/bin/sh'})
    assert unknown.status_code == 400
    opening = await client.post('/v1/cua/permissions/open', json={'id': 'screen'})
    assert opening.status_code == 200
    from deepseek_tui.server.routes import _PRIVACY_PANES
    assert opened == [
        [_PRIVACY_PANES['screen']],
    ]


@pytest.mark.asyncio
async def test_cua_preview_frame_serves_only_the_items_own_screenshots(client, runtime_app):
    import base64
    import io

    from PIL import Image

    from deepseek_tui.media import import_image
    from deepseek_tui.server.threads.models import (
        TurnItemKind,
        TurnItemLifecycleStatus,
        TurnItemRecord,
    )

    def stored(size):
        out = io.BytesIO()
        Image.new("RGB", size, "white").save(out, "PNG")
        return import_image(out.getvalue())

    shot, other = stored((1920, 1200)), stored((40, 40))
    image = shot.model_dump()
    image["source"] = {"kind": "cua", "tool": "cua_js"}
    item = TurnItemRecord(
        id="item-cua", turn_id="turn-a", kind=TurnItemKind.TOOL_CALL,
        status=TurnItemLifecycleStatus.COMPLETED, summary="cua_js",
        metadata={"images": [image]},
    )
    runtime_app.state.thread_manager.store.save_item(item)

    response = await client.get(f"/v1/cua/frames/item-cua/{shot.asset_id}")
    assert response.status_code == 200
    frame = response.json()
    assert (frame["mime_type"], frame["width"], frame["height"]) == ("image/jpeg", 960, 600)
    with Image.open(io.BytesIO(base64.b64decode(frame["data"]))) as decoded:
        assert decoded.size == (960, 600)

    assert (await client.get(f"/v1/cua/frames/item-cua/{other.asset_id}")).status_code == 404
    assert (await client.get(f"/v1/cua/frames/missing/{shot.asset_id}")).status_code == 404
    assert (await client.get("/v1/cua/frames/item-cua/..")).status_code in {400, 404}


@pytest.mark.asyncio
async def test_cua_preview_frame_requires_the_runtime_token(authed_runtime_app):
    from httpx import ASGITransport, AsyncClient

    app, token = authed_runtime_app
    path = "/v1/cua/frames/item/" + "a" * 64
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        authorized = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert authorized.status_code == 404


def test_privacy_app_name_uses_installed_bundle_name(tmp_path):
    import plistlib
    from deepseek_tui.server.routes import _privacy_app_name

    bundle = tmp_path / "Codex Computer Use.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleName": "Codex Computer Use",
        "CFBundleDisplayName": "ChatGPT Computer Use",
    }))
    assert _privacy_app_name(str(bundle), "old runtime label") == "Codex Computer Use"
    assert _privacy_app_name(str(tmp_path / "Missing.app"), "reported") == "reported"

@pytest.mark.asyncio
@pytest.mark.parametrize("kind,pane", [("screen", "ScreenCapture"), ("accessibility", "Accessibility")])
async def test_permission_open_does_not_wait_for_component_diagnostics(client, monkeypatch, kind, pane):
    import asyncio
    from deepseek_tui.server import routes

    async def entries(_):
        raise AssertionError("Opening settings must not run diagnostics")

    calls = []
    real_exec = asyncio.create_subprocess_exec

    async def execute(program, *args, **kwargs):
        assert program == "open"
        calls.append(list(args))
        return await real_exec("true")

    monkeypatch.setattr('sys.platform', 'darwin')
    monkeypatch.setattr(routes, "cua_permissions", entries)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", execute)
    response = await client.post('/v1/cua/permissions/open', json={"id": kind, "path": "/ignored.app"})
    assert response.status_code == 200
    assert calls == [[routes._PRIVACY_PANES[kind]]]
    denied = await client.post('/v1/cua/permissions/open', json={"id": "file:///tmp/other"})
    assert denied.status_code == 400 and len(calls) == 1

@pytest.mark.asyncio
async def test_permission_open_times_out_and_reaps_launcher(client, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, Mock

    process = Mock(returncode=None)
    process.wait = AsyncMock(return_value=-9)
    monkeypatch.setattr('sys.platform', 'darwin')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))

    async def timed_out(awaitable, timeout):
        assert timeout == 5
        await awaitable
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, 'wait_for', timed_out)
    response = await client.post('/v1/cua/permissions/open', json={'id': 'screen'})
    assert response.status_code == 504
    process.kill.assert_called_once()
    assert process.wait.await_count == 2


@pytest.mark.parametrize("version,pane", [
    ("12.7", "com.apple.preference.security"),
    ("13.0", "com.apple.settings.PrivacySecurity.extension"),
    ("27.0", "com.apple.settings.PrivacySecurity.extension"),
])
def test_privacy_settings_route_matches_macos_version(monkeypatch, version, pane):
    from deepseek_tui.server import routes
    monkeypatch.setattr(routes.platform, "mac_ver", lambda: (version, (), ""))
    assert routes._privacy_pane_prefix() == f"x-apple.systempreferences:{pane}?Privacy_"
