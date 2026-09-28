"""Cross-machine sharing: real storage/HTTP routes and cold context reconstruction."""

import base64
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from deepseek_tui.media import import_image
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.server import share_routes
from deepseek_tui.server.session_snapshot import (
    ProjectSnapshot,
    SnapshotFile,
    build_snapshot,
    capture_project,
    git,
    import_snapshot,
    restore_project,
    validate_snapshot,
)
from deepseek_tui.server.sessions import import_messages_into_store
from deepseek_tui.server.share_service import create_app
from deepseek_tui.server.threads import (
    CreateThreadRequest,
    RuntimeThreadStore,
    RuntimeTurnStatus,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    reconstruct_messages_from_turns,
)


async def test_restore_unexpected_failure_removes_scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(share_routes, "user_deepseek_dir", lambda: tmp_path)

    def fail_import(*_):
        raise RuntimeError("invalid snapshot")

    monkeypatch.setattr(share_routes, "import_snapshot", fail_import)
    req = SimpleNamespace(workspace=None, restore_project=False)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        thread_manager=SimpleNamespace(store=object())
    )))
    with pytest.raises(RuntimeError, match="invalid snapshot"):
        await share_routes._restore_downloaded(req, request, "token", SimpleNamespace(project=None))
    assert not list((tmp_path / "workspace").glob("shared-*"))


async def seed(manager):
    thread = await manager.create_thread(CreateThreadRequest(title="Continue at home"))
    messages = [
        Message.user("Fix login"),
        Message.assistant_with_tools(
            [ToolUseBlock(id="tool-1", name="read_file", input={"path": "login.py"})]
        ),
        Message.tool_result("tool-1", "original code"),
        Message.assistant("Next: add tests"),
    ]
    import_messages_into_store(manager.store, thread_id=thread.id, messages=messages)
    return thread


async def test_snapshot_roundtrip_retains_context_and_isolates_ids(runtime_app, tmp_path):
    manager = runtime_app.state.thread_manager
    thread = await seed(manager)
    thread.trust_mode = True
    thread.auto_approve = True
    thread.allow_shell = True
    thread.goal = {"objective": "Finish login", "status": "active"}
    snapshot = build_snapshot(manager.store, thread)
    source_json = snapshot.model_dump_json()
    target = RuntimeThreadStore(tmp_path / "home-store")
    imported = import_snapshot(target, snapshot, tmp_path, "share-token")
    second = import_snapshot(target, snapshot, tmp_path, "share-token")
    assert imported.id != thread.id != second.id
    assert imported.id != second.id
    assert not imported.trust_mode and not imported.auto_approve and not imported.allow_shell
    assert imported.goal == thread.goal
    assert imported.source_share_id == "share-token"
    assert imported.workspace == str(tmp_path)
    original = reconstruct_messages_from_turns(manager.store, thread.id)
    restored = reconstruct_messages_from_turns(target, imported.id)
    assert [m.model_dump() for m in restored] == [m.model_dump() for m in original]
    assert source_json == snapshot.model_dump_json()
    original_ids = {i.id for i in snapshot.items}
    assert not original_ids.intersection(
        i.id
        for t in target.list_turns_for_thread(imported.id)
        for i in target.list_items_for_turn(t.id)
    )


async def test_compaction_and_image_survive_snapshot(runtime_app, tmp_path, monkeypatch):
    manager = runtime_app.state.thread_manager
    thread = await seed(manager)
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format="PNG")
    image = import_image(buffer.getvalue())
    turn = manager.store.list_turns_for_thread(thread.id)[-1]
    messages = [Message.user("We changed login; tests remain").model_dump(mode="json")]
    messages[0]["content"].append(image.model_dump(mode="json"))
    item = TurnItemRecord(
        id="compact",
        turn_id=turn.id,
        kind=TurnItemKind.CONTEXT_COMPACTION,
        status=TurnItemLifecycleStatus.COMPLETED,
        summary="compacted",
        metadata={"session_messages": messages},
    )
    manager.store.save_item(item)
    turn.item_ids.append(item.id)
    manager.store.save_turn(turn)
    snapshot = build_snapshot(manager.store, thread)
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "other-home"))
    target = RuntimeThreadStore(tmp_path / "other-store")
    imported = import_snapshot(target, snapshot, tmp_path, "token")
    from deepseek_tui.config.paths import user_media_dir

    assert (user_media_dir() / image.asset_id).read_bytes() == buffer.getvalue()
    restored = reconstruct_messages_from_turns(target, imported.id)
    assert len(restored) == 1
    assert restored[0].content[0].text == "We changed login; tests remain"
    assert len(target.list_items_for_turn(imported.latest_turn_id)) == len(snapshot.items)


async def test_unfinished_and_invalid_snapshots_rejected(runtime_app):
    manager = runtime_app.state.thread_manager
    thread = await seed(manager)
    snapshot = build_snapshot(manager.store, thread)
    snapshot.items[0].turn_id = "unrelated"
    with pytest.raises(ValueError):
        validate_snapshot(snapshot)
    turn = manager.store.list_turns_for_thread(thread.id)[-1]
    turn.status = RuntimeTurnStatus.IN_PROGRESS
    manager.store.save_turn(turn)
    with pytest.raises(ValueError, match="finish"):
        build_snapshot(manager.store, thread)


def init_repo(path):
    path.mkdir()
    git(path, "init")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    (path / "login.py").write_text("before\n")
    (path / "remove.txt").write_text("delete me")
    (path / ".gitignore").write_text(".env\n")
    git(path, "add", ".")
    git(path, "commit", "-m", "base")


def test_project_restores_binary_new_deleted_and_executable_without_touching_checkout(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "login.py").write_text("after\n")
    (repo / "login.py").chmod(0o755)
    (repo / "remove.txt").unlink()
    (repo / "new.bin").write_bytes(b"\x00\xff\x01")
    (repo / ".env").write_text("SECRET")
    snapshot = capture_project(repo)
    assert ".env" not in [f.path for f in snapshot.files]
    target = tmp_path / "restored"
    restore_project(snapshot, repo, target)
    assert (target / "login.py").read_text() == "after\n"
    assert (target / "login.py").stat().st_mode & 0o111
    assert (target / "new.bin").read_bytes() == b"\x00\xff\x01"
    assert not (target / "remove.txt").exists()
    assert not (target / ".env").exists()
    assert (repo / ".env").read_text() == "SECRET"
    assert (repo / "login.py").read_text() == "after\n"


@pytest.mark.parametrize(
    "name", ["../escape", "/tmp/escape", ".git/config", "a/../../escape", "C:/x"]
)
def test_project_rejects_unsafe_paths(tmp_path, name):
    repo = tmp_path / "repo"
    init_repo(repo)
    project = ProjectSnapshot(
        commit=git(repo, "rev-parse", "HEAD").decode().strip(),
        files=[SnapshotFile(path=name, content=base64.b64encode(b"x").decode())],
    )
    target = tmp_path / "restored"
    with pytest.raises(ValueError):
        restore_project(project, repo, target)
    assert not target.exists()


async def test_link_service_and_local_runtime_end_to_end(
    client, runtime_app, tmp_path, monkeypatch
):
    service = create_app(storage=tmp_path / "shares", upload_key="k" * 32)
    transport = httpx.ASGITransport(app=service)
    real_client = httpx.AsyncClient
    # Run the real runtime HTTP bridge against the real standalone storage app.
    monkeypatch.setattr(
        share_routes.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    manager = runtime_app.state.thread_manager
    thread = await seed(manager)
    r = await client.put(
        "/v1/sharing/settings",
        json={"service_url": "https://shares.example.com", "upload_key": "k" * 32},
    )
    assert r.status_code == 200
    assert "upload_key" not in (await client.get("/v1/sharing/settings")).json()
    r = await client.post("/v1/sharing/shares", json={"thread_id": thread.id})
    assert r.status_code == 201, r.text
    url = r.json()["url"]
    preview = await client.post("/v1/sharing/preview", json={"url": url})
    assert preview.status_code == 200, preview.text
    assert preview.json()["title"] == "Continue at home"
    # A receiving machine needs no configuration at all.
    share_routes.settings_path().unlink()
    restored = await client.post("/v1/sharing/restore", json={"url": url})
    assert restored.status_code == 201, restored.text
    assert restored.json()["id"] != thread.id
    assert Path(restored.json()["workspace"]).is_dir()
    assert restored.json()["workspace"] != thread.workspace
    assert len(reconstruct_messages_from_turns(manager.store, restored.json()["id"])) == 4
    rejected = await client.post(
        "/v1/sharing/preview", json={"url": url.replace("shares.example.com", "other.example.com")}
    )
    assert rejected.status_code == 200  # Receiving links does not require origin configuration.
    assert (await client.post("/v1/sharing/revoke", json={"url": url})).status_code == 400
    await client.put(
        "/v1/sharing/settings",
        json={"service_url": "https://shares.example.com", "upload_key": "k" * 32},
    )
    assert (await client.post("/v1/sharing/revoke", json={"url": url})).status_code == 200
    assert (await client.post("/v1/sharing/preview", json={"url": url})).status_code == 404
    assert manager.store.load_thread(restored.json()["id"])


async def test_service_auth_expiry_and_bad_format(runtime_app, tmp_path):
    app = create_app(storage=tmp_path / "shares", upload_key="k" * 32)
    manager = runtime_app.state.thread_manager
    snapshot = build_snapshot(manager.store, await seed(manager))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://shares.test"
    ) as client:
        payload = {"snapshot": snapshot.model_dump(mode="json")}
        assert (await client.post("/v1/shares", json=payload)).status_code == 401
        headers = {"Authorization": "Bearer " + "k" * 32}
        r = await client.post("/v1/shares", json=payload, headers=headers)
        token = r.json()["token"]
        assert (await client.delete(f"/v1/shares/{token}")).status_code == 401
        path = tmp_path / "shares" / f"{token}.json"
        data = json.loads(path.read_text())
        data["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        path.write_text(json.dumps(data))
        r = await client.get(f"/v1/shares/{token}")
        assert r.status_code == 410
        assert (await client.get(f"/s/{token}")).status_code == 404
        assert r.headers["cache-control"] == "no-store"
        assert not path.exists()
        payload["snapshot"]["version"] = 99
        assert (await client.post("/v1/shares", json=payload, headers=headers)).status_code == 400


async def test_restored_engine_receives_history_and_new_workspace(runtime_app, tmp_path):
    from types import SimpleNamespace

    manager = runtime_app.state.thread_manager
    original = await seed(manager)
    restored = import_snapshot(
        manager.store, build_snapshot(manager.store, original), tmp_path / "home-project", "token"
    )
    captured = {}
    engine = SimpleNamespace(sync_session=lambda messages, **kw: captured.update(messages=messages))
    manager._sync_engine_session(engine, restored)
    messages = captured["messages"]
    assert messages[0].content[0].text == "Fix login"
    assert messages[-2].content[0].text == "Next: add tests"
    assert str(tmp_path / "home-project") in messages[-1].content[0].text
    assert messages[-1].origin.value == "system_reminder"


def test_renames_remove_old_path_on_restore(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    git(repo, "mv", "login.py", "renamed.py")
    target = tmp_path / "restored"
    restore_project(capture_project(repo), repo, target)
    assert not (target / "login.py").exists()
    assert (target / "renamed.py").read_text() == "before\n"


def test_symlink_parent_cannot_write_outside_restored_tree(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    external = tmp_path / "external"
    external.mkdir()
    (external / "protected").write_text("unchanged")
    (repo / "link").symlink_to(external, target_is_directory=True)
    git(repo, "add", "link")
    git(repo, "commit", "-m", "symlink")
    project = ProjectSnapshot(
        commit=git(repo, "rev-parse", "HEAD").decode().strip(),
        files=[SnapshotFile(path="link/protected", content="eA==")],
    )
    target = tmp_path / "restored"
    with pytest.raises(ValueError, match="symlink"):
        restore_project(project, repo, target)
    assert (external / "protected").read_text() == "unchanged"
    assert not target.exists()


async def test_browser_preview_deep_link_and_revoked_page(runtime_app, tmp_path):
    app = create_app(storage=tmp_path / "shares", upload_key="k" * 32)
    manager = runtime_app.state.thread_manager
    thread = await seed(manager)
    thread.title = '<script>alert("test")</script>'
    snapshot = build_snapshot(manager.store, thread)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://shares.test"
    ) as client:
        headers = {"Authorization": "Bearer " + "k" * 32}
        result = await client.post(
            "/v1/shares", headers=headers, json={"snapshot": snapshot.model_dump(mode="json")}
        )
        token = result.json()["token"]
        page = await client.get(f"/s/{token}")
        assert page.status_code == 200
        assert "Fix login" in page.text and "Next: add tests" in page.text
        assert "<script>" not in page.text and "&lt;script&gt;" in page.text
        assert "deepseek-gui://share?url=https%3A%2F%2Fshares.test%2Fs%2F" in page.text
        assert "default-src 'none'" in page.headers["content-security-policy"]
        await client.delete(f"/v1/shares/{token}", headers=headers)
        page = await client.get(f"/s/{token}")
        assert page.status_code == 404 and "分享已失效" in page.text


async def test_external_link_never_receives_stored_upload_key(
    client, runtime_app, tmp_path, monkeypatch
):
    snapshot = build_snapshot(
        runtime_app.state.thread_manager.store, await seed(runtime_app.state.thread_manager)
    )
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json={"snapshot": snapshot.model_dump(mode="json")})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        share_routes.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    await client.put(
        "/v1/sharing/settings",
        json={"service_url": "https://mine.example", "upload_key": "private-upload-key"},
    )
    link = "https://friend.example/s/" + "a" * 43
    response = await client.post("/v1/sharing/preview", json={"url": link})
    assert response.status_code == 200
    assert seen == [("https://friend.example/v1/shares/" + "a" * 43, None)]
    invalid = await client.post(
        "/v1/sharing/preview", json={"url": "https://user:pass@friend.example/s/" + "a" * 43}
    )
    assert invalid.status_code == 400


async def test_hosted_sharing_needs_no_settings_and_revokes_with_per_link_key(
    client, runtime_app, monkeypatch
):
    seen = []
    token, deletion = "a" * 43, "b" * 43

    def handler(request):
        seen.append((str(request.url), request.method, request.headers.get("authorization")))
        if request.method == "POST":
            return httpx.Response(
                201,
                json={"token": token, "delete_key": deletion, "expires_at": "2026-12-01T00:00:00Z"},
            )
        return httpx.Response(204)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        share_routes.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    config = (await client.get("/v1/sharing/settings")).json()
    assert config["ready"] and not config["has_upload_key"]
    thread = await seed(runtime_app.state.thread_manager)
    created = await client.post("/v1/sharing/shares", json={"thread_id": thread.id})
    assert created.status_code == 201, created.text
    assert "delete_key" not in created.json()
    # Changing advanced settings must never send the hosted deletion credential elsewhere.
    await client.put(
        "/v1/sharing/settings",
        json={"service_url": "https://elsewhere.test", "upload_key": "other-key"},
    )
    revoked = await client.post("/v1/sharing/revoke", json={"url": created.json()["url"]})
    assert revoked.status_code == 200
    assert seen == [
        (share_routes.DEFAULT_SERVICE_URL + "/v1/shares", "POST", None),
        (share_routes.DEFAULT_SERVICE_URL + "/v1/shares/" + token, "DELETE", "Bearer " + deletion),
    ]
    assert (
        await client.post("/v1/sharing/revoke", json={"url": created.json()["url"]})
    ).status_code == 403


def test_project_file_directory_replacements(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "folder").mkdir()
    (repo / "folder" / "child.txt").write_text("old")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "folder")
    (repo / "folder" / "child.txt").unlink()
    (repo / "folder").rmdir()
    (repo / "folder").write_text("now a file")
    (repo / "login.py").unlink()
    (repo / "login.py").mkdir()
    (repo / "login.py" / "child.txt").write_text("now a directory")
    target = tmp_path / "restored"
    restore_project(capture_project(repo), repo, target)
    assert (target / "folder").read_text() == "now a file"
    assert (target / "login.py" / "child.txt").read_text() == "now a directory"


async def test_real_http_share_between_independent_homes(
    client, runtime_app, tmp_path, monkeypatch
):
    """Opt-in acceptance against local Worker or the deployed service; synthetic data only."""
    import os
    from types import SimpleNamespace

    origin = os.environ.get("DEEPSEEK_SHARE_TEST_ORIGIN")
    if not origin:
        pytest.skip("Set DEEPSEEK_SHARE_TEST_ORIGIN to run real HTTP acceptance")
    monkeypatch.setattr(share_routes, "DEFAULT_SERVICE_URL", origin.rstrip("/"))
    manager = runtime_app.state.thread_manager
    source = await seed(manager)
    company_home = tmp_path / "company-home"
    monkeypatch.setenv("DEEPSEEK_HOME", str(company_home))
    created = await client.post("/v1/sharing/shares", json={"thread_id": source.id})
    assert created.status_code == 201, created.text
    link = created.json()["url"]
    try:
        # A fresh user's data directory has no sharing settings or deletion credential.
        monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home-computer"))
        assert not share_routes.settings_path().exists()
        preview = await client.post("/v1/sharing/preview", json={"url": link})
        assert preview.status_code == 200, preview.text
        restored = await client.post("/v1/sharing/restore", json={"url": link})
        assert restored.status_code == 201, restored.text
        target = manager.store.load_thread(restored.json()["id"])
        captured = {}
        manager._sync_engine_session(
            SimpleNamespace(sync_session=lambda messages, **kw: captured.update(messages=messages)),
            target,
        )
        assert captured["messages"][0].content[0].text == "Fix login"
        assert captured["messages"][-2].content[0].text == "Next: add tests"
        assert not target.allow_shell and not target.auto_approve
        assert (await client.post("/v1/sharing/revoke", json={"url": link})).status_code == 403
    finally:
        monkeypatch.setenv("DEEPSEEK_HOME", str(company_home))
        result = await client.post("/v1/sharing/revoke", json={"url": link})
        assert result.status_code == 200, result.text
    assert (await client.post("/v1/sharing/preview", json={"url": link})).status_code == 404
    assert reconstruct_messages_from_turns(manager.store, target.id)
