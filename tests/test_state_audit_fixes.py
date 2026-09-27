"""Regressions for audit 08; all credentials and storage are synthetic."""

import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from deepseek_tui.state import session
from deepseek_tui.state.context import ContextConfig, UserTurnInput, process_turn_input
from deepseek_tui.state.paste_file import write_paste_txt
from deepseek_tui.state.secrets import write_api_key, write_config_value

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))


def payload(workspace, identity):
    return {"metadata": {"workspace": str(workspace), "id": identity}, "messages": []}


def test_checkpoint_isolation_and_clear(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    session.save_checkpoint(payload(a, "first"))
    session.save_checkpoint(payload(b, "other"))
    session.save_checkpoint(payload(a, "second"))
    assert session.load_checkpoint(workspace=a)["metadata"]["id"] == "second"
    assert session.load_checkpoint(workspace=a, session_id="first")["metadata"]["id"] == "first"
    session.clear_checkpoint(workspace=a, session_id="first")
    assert session.load_checkpoint(workspace=b)["metadata"]["id"] == "other"
    assert session.load_checkpoint(workspace=a)["metadata"]["id"] == "second"


def test_legacy_checkpoint_only_migrates_to_matching_workspace(tmp_path):
    data = payload(tmp_path / "a", "legacy")
    session.save_checkpoint(data)
    session.checkpoint_path().parent.mkdir(parents=True, exist_ok=True)
    session.checkpoint_path().write_text(json.dumps(data))
    assert session.load_checkpoint(workspace=tmp_path / "b") is None
    # Remove the new scoped target to exercise actual legacy migration.
    session.checkpoint_path(workspace=tmp_path / "a").unlink()
    session.clear_checkpoint(workspace=tmp_path / "a", session_id="legacy")
    assert session.load_checkpoint(workspace=tmp_path / "a")["metadata"]["id"] == "legacy"
    session.clear_checkpoint(workspace=tmp_path / "a", session_id="legacy")
    assert session.load_checkpoint(workspace=tmp_path / "a") is None


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"schema_version": "1"},
        {"metadata": []},
        {"messages": {}},
        {"schema_version": 999},
        {"metadata": {"workspace": 123}},
        {"metadata": {"id": True}},
    ],
)
def test_malformed_checkpoint_is_value_error(raw):
    path = session.checkpoint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        session.load_checkpoint()
    assert path.exists()


def test_checkpoint_version_owned_by_writer_and_size_bounded(monkeypatch):
    session.save_checkpoint({"schema_version": 999})
    assert session.load_checkpoint()["schema_version"] == 1
    monkeypatch.setattr(session, "MAX_CHECKPOINT_BYTES", 10)
    with pytest.raises(ValueError):
        session.load_checkpoint()


def test_concurrent_pastes_are_exclusive(tmp_path):
    class Clock:
        @classmethod
        def now(cls):
            return datetime(2026, 9, 27, 12)

    barrier = threading.Barrier(2)
    original = Path.open

    def opening(path, mode="r", *args, **kwargs):
        if path.name == "paste-20260927-120000.txt" and mode == "x":
            barrier.wait(timeout=3)
        return original(path, mode, *args, **kwargs)

    with (
        patch("deepseek_tui.state.paste_file.datetime", Clock),
        patch.object(Path, "open", opening),
        ThreadPoolExecutor(2) as pool,
    ):
        paths = list(pool.map(lambda text: write_paste_txt(text, tmp_path), ["one", "two"]))
    assert len(set(paths)) == 2
    assert {path.read_text() for path in paths} == {"one", "two"}


def test_rendered_directory_and_escaped_file_share_budget(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "long-name").touch()
    (tmp_path / "data.txt").write_text("<&>" * 200)
    result = process_turn_input(
        UserTurnInput("@folder @data.txt"),
        workspace=tmp_path,
        cwd=tmp_path,
        config=ContextConfig(max_total_inline_bytes=250),
    )
    expansion = result.model_text.split("<local_context>\n", 1)[1].split("\n</local_context>")[0]
    assert len(expansion.encode()) <= 250
    assert result.warnings


@pytest.mark.parametrize("kind", ["image", "text"])
def test_disappearing_files_preserve_query(tmp_path, kind):
    name = "image.png" if kind == "image" else "text.txt"
    (tmp_path / name).write_text("fixture")
    target = (
        "deepseek_tui.media.import_image_path"
        if kind == "image"
        else "deepseek_tui.state.context._read_text_budget"
    )
    with patch(target, side_effect=FileNotFoundError("removed")):
        result = process_turn_input(
            UserTurnInput(f"question @{name}"), workspace=tmp_path, cwd=tmp_path
        )
    assert "question" in result.model_text
    assert not result.references[0].expanded


def test_semantically_equivalent_toml_header(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('provider="deepseek"\n[providers . "deepseek"] # comment\napi_key="fake-old"\n')
    write_api_key("deepseek", "fake-new", path=path)
    result = tomllib.loads(path.read_text())
    assert result["providers"]["deepseek"]["api_key"] == "fake-new"
    assert "# comment" in path.read_text()


def test_multiline_toml_is_never_silently_corrupted(tmp_path):
    path = tmp_path / "config.toml"
    original = 'note = """\napi_key="not-a-setting"\n"""\n'
    path.write_text(original)
    with pytest.raises(ValueError):
        write_api_key("deepseek", "fake-new", path=path)
    assert path.read_text() == original


def test_concurrent_config_updates_preserve_both_values(tmp_path):
    path = tmp_path / "config.toml"
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda key: write_config_value(key, "yes", path=path), ["alpha", "beta"]))
    assert tomllib.loads(path.read_text()) == {"alpha": "yes", "beta": "yes"}


@pytest.mark.parametrize("provider", ["deepseek", "anthropic"])
def test_media_variant_is_reused_per_payload_and_discarded_between_requests(provider):
    from deepseek_tui import media
    from deepseek_tui.client.anthropic import AnthropicCompatClient
    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.protocol.messages import Message, MessageRequest

    data = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(data, format="PNG")
    block = media.import_image(data.getvalue())
    request = MessageRequest(model="x", messages=[Message.user("image", images=[block])])
    client_type = DeepSeekClient if provider == "deepseek" else AnthropicCompatClient
    client = client_type(api_key="fake", base_url="https://example.invalid")
    with patch(
        "deepseek_tui.media._encode_image_data_url", wraps=media._encode_image_data_url
    ) as encode:
        client._build_payload(request)
        assert encode.call_count == 1
        client._build_payload(request)
        assert encode.call_count == 2


def test_media_variant_scope_discards_cache_after_failure():
    from deepseek_tui import media

    data = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(data, format="PNG")
    block = media.import_image(data.getvalue())
    with patch(
        "deepseek_tui.media._encode_image_data_url", wraps=media._encode_image_data_url
    ) as encode:
        with pytest.raises(RuntimeError), media.media_variant_scope():
            media.image_data_url(block)
            raise RuntimeError("serialization failed")
        media.image_data_url(block)
        assert encode.call_count == 2
