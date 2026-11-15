from __future__ import annotations

import base64
import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from deepseek_tui.mobile import files as files
from deepseek_tui.state.context import UserTurnInput, process_turn_input


@pytest.fixture
def mobile(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    root = tmp_path / "workspace"
    root.mkdir()

    def load(thread_id):
        if thread_id not in {"a", "b", "isolated"}:
            raise FileNotFoundError(thread_id)
        return SimpleNamespace(
            workspace=str(root),
            env_mode="worktree" if thread_id == "isolated" else "local",
            worktree_path=None,
        )

    app = FastAPI()
    app.state.thread_manager = SimpleNamespace(store=SimpleNamespace(load_thread=load))
    app.include_router(files.router)
    with TestClient(app) as client:
        yield client, root


def upload(client, name, data, thread="a"):
    return client.post(
        f"/v1/threads/{thread}/attachments",
        json={"name": name, "data_base64": base64.b64encode(data).decode()},
    )


def test_upload_roundtrip_and_thread_attachment_scope(mobile):
    client, root = mobile
    a = upload(client, "中文 notes.txt", b"hello").json()
    b = upload(client, "中文 notes.txt", b"other").json()
    assert a["path"] != b["path"]
    assert (root / a["path"]).read_bytes() == b"hello"
    r = client.get("/v1/threads/a/files/content", params={"path": a["path"]})
    assert base64.b64decode(r.json()["data_base64"]) == b"hello"
    assert client.get("/v1/threads/b/files/content", params={"path": a["path"]}).status_code == 403
    assert client.get("/v1/threads/missing/files").status_code == 404
    assert client.get("/v1/threads/isolated/files").status_code == 409


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/etc/passwd",
        "a/../../outside",
        "a\\outside",
        ".env",
        ".aws/config",
        ".git/config",
        "dir/secrets.json",
    ],
)
def test_rejects_paths(mobile, path):
    client, _ = mobile
    assert client.get("/v1/threads/a/files/content", params={"path": path}).status_code in {
        400,
        403,
    }


def test_symlinks_sensitive_files_and_fifo_hidden_and_unreadable(mobile, tmp_path):
    import os

    client, root = mobile
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("secret")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "alias").symlink_to(outside / "secret")
    (root / ".env").write_text("KEY=secret")
    os.mkfifo(root / "pipe")
    (root / "okay.txt").write_text("fine")
    assert [e["name"] for e in client.get("/v1/threads/a/files").json()["entries"]] == ["okay.txt"]
    for path in ("link/secret", "alias", "pipe"):
        assert client.get("/v1/threads/a/files/content", params={"path": path}).status_code == 403
    assert client.get("/v1/threads/a/files", params={"path": "link"}).status_code == 403
    (root / files.UPLOADS).symlink_to(outside, target_is_directory=True)
    assert upload(client, "file.txt", b"no").status_code == 403
    assert list(outside.iterdir()) == [outside / "secret"]


def test_upload_image_expands_via_original_runtime(mobile):
    client, root = mobile
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), "blue").save(buffer, format="PNG")
    result = upload(client, "photo.png", buffer.getvalue())
    assert result.status_code == 200
    body = result.json()
    processed = process_turn_input(
        UserTurnInput(raw_text=body["mention"]), workspace=root, cwd=root
    )
    assert len(processed.images) == 1
    assert processed.images[0].asset_id == body["image"]["asset_id"]
    assert processed.images[0].width == 4
    assert upload(client, "bad.png", b"fake").status_code == 400


def test_upload_validation_and_limits(mobile, monkeypatch):
    client, root = mobile
    assert upload(client, ".env", b"secret").status_code == 403
    assert upload(client, "../escape.txt", b"x").status_code == 400
    assert (
        client.post("/v1/threads/a/attachments", json={"name": "x", "data_base64": "!"}).status_code
        == 400
    )
    monkeypatch.setattr(files, "MAX_BYTES", 3)
    assert upload(client, "x.txt", b"four").status_code == 413
    (root / "large").write_bytes(b"four")
    assert client.get("/v1/threads/a/files/content", params={"path": "large"}).status_code == 413
    monkeypatch.setattr(files, "MAX_BODY", 4)
    assert client.post("/v1/threads/a/attachments", content=b"12345").status_code == 413
