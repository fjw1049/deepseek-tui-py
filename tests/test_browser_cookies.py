"""Synthetic credentials only: never read the developer's Chrome or keychain."""

import json
import sqlite3
from copy import deepcopy
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from zipfile import ZipFile

import pytest

from deepseek_tui.browser.chrome_cookies import read_chrome
from deepseek_tui.browser.cookies import CookieStore, cookie_key, cookie_params
from deepseek_tui.browser.service import BrowserRun, BrowserService
from deepseek_tui.server.data_bundle import create_backup, export_bundle


def cookie(value="PRIVATE_COOKIE_SENTINEL"):
    return {
        "name": "login",
        "value": value,
        "domain": "example.test",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "expires": -1,
    }


def run_at(root: Path, name="one"):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    jar = {}

    async def send(method, params=None):
        if method == "Storage.getCookies":
            return {"cookies": deepcopy(list(jar.values()))}
        if method == "Network.clearBrowserCookies":
            jar.clear()
        if method == "Network.setCookies":
            for item in params["cookies"]:
                item = deepcopy(item)
                if "url" in item:
                    item["domain"] = urlsplit(item.pop("url")).hostname
                item.setdefault("expires", -1)
                jar[cookie_key(item)] = item
        return {}

    run = BrowserRun(
        name,
        directory,
        session=SimpleNamespace(
            _internal=SimpleNamespace(client=SimpleNamespace(send=AsyncMock(side_effect=send)))
        ),
        profiles=SimpleNamespace(get_or_create=lambda _: SimpleNamespace(data_dir=directory)),
        url="https://example.test/account",
    )
    return run, jar


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "deepseek_tui.browser.cookies.profiles", lambda: [{"id": "Default", "name": "Personal"}]
    )
    result = CookieStore(tmp_path / "private")
    result.read_source = AsyncMock(
        return_value={"cookies": [cookie_params(cookie())], "skipped": 0}
    )
    return result


async def test_consent_required_and_empty_source_does_not_erase(store, tmp_path):
    run, jar = run_at(tmp_path)
    await store.restore(run)
    await store.sync(run)
    store.read_source.assert_not_called()
    store.configure("enabled", "Default")
    await store.sync(run)
    assert len(jar) == 1
    store.read_source.return_value = {"cookies": [], "skipped": 0}
    await store.sync(run)
    assert len(jar) == 1 and store.state()["status"] == "empty"
    assert "PRIVATE_COOKIE_SENTINEL" not in json.dumps(store.state())
    assert b"PRIVATE_COOKIE_SENTINEL" not in (store.root / "cookies.enc").read_bytes()


async def test_signin_survives_new_chat_and_logout_is_not_reimported(store, tmp_path):
    run, jar = run_at(tmp_path)
    await store.restore(run)
    jar[cookie_key(cookie())] = cookie()
    await store.capture(run)
    restored = CookieStore(store.root)
    restored.read_source = store.read_source
    other, other_jar = run_at(tmp_path, "two")
    await restored.restore(other)
    assert other_jar == jar
    restored.configure("enabled", "Default")
    other_jar.clear()
    await restored.capture(other)
    restored.read_source.assert_not_called()
    # Saving an unchanged old chat cannot resurrect the deleted login.
    await store.capture(run)
    third, third_jar = run_at(tmp_path, "three")
    await restored.restore(third)
    assert third_jar == {}


async def test_stale_chat_does_not_delete_newer_cookie(store, tmp_path):
    first, jar = run_at(tmp_path)
    await store.restore(first)
    jar[cookie_key(cookie())] = cookie()
    await store.capture(first)
    second, second_jar = run_at(tmp_path, "two")
    await store.restore(second)
    second_jar[cookie_key(cookie())] = cookie("new")
    await store.capture(second)
    jar.clear()
    await store.capture(first)
    third, third_jar = run_at(tmp_path, "three")
    await store.restore(third)
    assert next(iter(third_jar.values()))["value"] == "new"


async def test_clear_does_not_recover_native_or_chrome_cookies(store, tmp_path):
    run, jar = run_at(tmp_path)
    await store.restore(run)
    jar[cookie_key(cookie())] = cookie()
    await store.capture(run)
    await store.clear()
    old, old_jar = run_at(tmp_path, "unmigrated")
    old_jar[cookie_key(cookie())] = cookie()
    await store.restore(old)
    assert old_jar == {}
    store.configure("enabled", "Default")
    store.read_source.assert_not_called()


async def test_failure_is_reported_and_disabling_revokes_inflight_import(store, tmp_path):
    run, jar = run_at(tmp_path)
    await store.restore(run)
    store.configure("enabled", "Default")
    store.read_source.side_effect = RuntimeError("PRIVATE_COOKIE_SENTINEL")
    await store.sync(run)
    assert store.read_source.await_count == 1
    assert store.state()["status"] == "unavailable"
    assert "PRIVATE_COOKIE_SENTINEL" not in json.dumps(store.state())

    async def delayed(*args):
        store.configure("disabled", None)
        return {"cookies": [cookie_params(cookie())], "skipped": 0}

    store.read_source.side_effect = delayed
    await store.sync(run)
    assert not jar


async def test_worker_rejects_paths_without_reading_chrome(tmp_path):
    store = CookieStore(tmp_path)
    assert await store.read_source("../not-a-profile") == {"error": "unavailable"}


async def test_corrupt_store_cannot_block_navigation(store, tmp_path):
    store.configure("enabled", "Default")
    (store.root / "cookies.enc").write_bytes(b"broken")
    run, _ = run_at(tmp_path)
    await store.sync(run)
    assert store.state()["status"] == "unavailable"
    store.read_source.assert_not_called()
    await store.clear()
    assert store.state()["consent"] == "disabled"
    assert store._read()["cookies"] == {}


async def test_clear_removes_native_cookie_copies_but_preserves_other_data(tmp_path):
    service = BrowserService(tmp_path / "artifacts")
    profile = service.profile_root / "profiles/one/workbench/Default"
    profile.mkdir(parents=True)
    for name in ("Cookies", "Cookies-wal", "Cookies-shm", "Local Storage"):
        (profile / name).write_text("synthetic")
    await service.clear_cookies()
    assert (profile / "Local Storage").read_text() == "synthetic"
    assert not list(profile.glob("Cookies*"))


def test_host_only_and_partition_key_are_preserved():
    value = cookie()
    value["partitionKey"] = {"topLevelSite": "https://parent.test", "hasCrossSiteAncestor": True}
    params = cookie_params(value)
    assert params["url"] == "https://example.test/"
    assert "expires" not in params and "domain" not in params
    assert params["partitionKey"] == value["partitionKey"]


def test_source_snapshot_imports_all_domains_and_preserves_flags(tmp_path, monkeypatch):
    import browser_cookie3

    source = tmp_path / "Cookies"
    with sqlite3.connect(source) as db:
        db.execute(
            "CREATE TABLE cookies(host_key, path, name, value, is_httponly, "
            "samesite, top_frame_site_key)"
        )
        db.executemany(
            "INSERT INTO cookies VALUES (?,?,?,?,?,?,?)",
            [
                (".example.test", "/", "login", "test", 1, 2, ""),
                (".example.test", "/", "partitioned", "test", 1, 0, "https://parent.test"),
                (".unrelated.test", "/", "other", "test", 0, -1, ""),
            ],
        )
    monkeypatch.setattr("deepseek_tui.browser.chrome_cookies.cookie_file", lambda _: source)
    monkeypatch.setattr("deepseek_tui.browser.chrome_cookies.chrome_root", lambda: tmp_path)

    def load(cookie_file, key_file):
        with sqlite3.connect(cookie_file) as db:
            assert db.execute("SELECT count(*) FROM cookies").fetchone()[0] == 2
        jar = CookieJar()
        jar.set_cookie(
            Cookie(
                0,
                "login",
                "test",
                None,
                False,
                ".example.test",
                True,
                True,
                "/",
                True,
                True,
                None,
                True,
                None,
                None,
                {"HTTPOnly": ""},
            )
        )
        other = deepcopy(next(iter(jar)))
        other.domain, other.name = ".unrelated.test", "other"
        jar.set_cookie(other)
        return jar

    monkeypatch.setattr(browser_cookie3, "chrome", load)
    result = read_chrome("Default")
    assert {c["domain"] for c in result["cookies"]} == {".example.test", ".unrelated.test"}
    assert result["skipped"] == 1
    assert result["cookies"][0]["sameSite"] == "Strict"
    assert result["cookies"][0]["httpOnly"] is True
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT count(*) FROM cookies").fetchone()[0] == 3


def test_conversation_export_excludes_legacy_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    profile = tmp_path / "threads/browser-artifacts/one/profile/workbench"
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("PRIVATE_COOKIE_SENTINEL")
    (profile / "SingletonLock").symlink_to("missing-lock")
    (profile.parent.parent / "result.json").write_text("{}")
    archive = tmp_path / "export.zip"
    export_bundle(archive, threads_dir=tmp_path / "threads", sessions_dir=tmp_path / "sessions")
    with ZipFile(archive) as bundle:
        assert not any("/profile/" in name for name in bundle.namelist())
        assert "threads/browser-artifacts/one/result.json" in bundle.namelist()
    backup = create_backup(
        directory=tmp_path / "backups",
        threads_dir=tmp_path / "threads",
        sessions_dir=tmp_path / "sessions",
    )
    assert not list(Path(backup["path"]).rglob("Cookies"))


@pytest.mark.e2e
async def test_real_cookie_persistence_across_chats(tmp_path, monkeypatch):
    import os

    if os.environ.get("DEEPSEEK_BROWSER_E2E") != "1":
        pytest.skip("Set DEEPSEEK_BROWSER_E2E=1 for actual Chrome")
    service = BrowserService(tmp_path / "artifacts")
    monkeypatch.setattr("deepseek_tui.browser.cookies.profiles", lambda: [{"id": "Default"}])
    service.cookies.configure("enabled", "Default")
    service.cookies.read_source = AsyncMock(
        return_value={"cookies": [cookie_params(cookie())], "skipped": 0}
    )
    try:
        one = await service.ensure("one")
        assert one.url in {"", "about:blank"}
        one.owner = "user"
        result = await service.sync_cookies("one")
        assert result["status"] == "synced" and result["count"] == 1
        await service.close("one")
        service = BrowserService(tmp_path / "artifacts")
        service.cookies.read_source = AsyncMock(
            side_effect=AssertionError("Must not read real Chrome")
        )
        two = await service.ensure("two")
        cookies = (await two.session._internal.client.send("Storage.getCookies"))["cookies"]
        saved = next(c for c in cookies if c["name"] == "login")
        assert saved["value"] == "PRIVATE_COOKIE_SENTINEL" and saved["httpOnly"]
        assert saved["sameSite"] == "Lax" and saved["session"]
        two.url = "https://example.test"
        await two.session._internal.client.send("Network.clearBrowserCookies")
        await service.close("two")
        three = await service.ensure("three")
        assert (await three.session._internal.client.send("Storage.getCookies"))["cookies"] == []
        service.cookies.read_source.assert_not_called()
    finally:
        await service.close_all()


async def test_import_without_browser_saves_all_domains_and_survives_restart(store, tmp_path):
    other = {**cookie("OTHER_PRIVATE_SENTINEL"), "domain": ".other.test"}
    store.read_source.return_value = {
        "cookies": [cookie_params(cookie()), cookie_params(other)], "skipped": 2,
    }
    store.configure("enabled", "Default")
    service = BrowserService(tmp_path / "artifacts")
    service.cookies = store
    result = await service.sync_cookies("not-open")
    assert (result["status"], result["count"], result["domains"], result["skipped"]) == (
        "partial", 2, 2, 2,
    )
    store.read_source.assert_awaited_once_with("Default")
    assert not service.runs
    restarted = CookieStore(store.root)
    assert restarted.state() == result
    run, jar = run_at(tmp_path)
    run.url = "about:blank"
    await restarted.restore(run)
    assert {c["domain"] for c in jar.values()} == {"example.test", ".other.test"}
    assert "PRIVATE_SENTINEL" not in (store.root / "sync.json").read_text()


async def test_blank_page_import_merges_without_erasing_app_cookies(store, tmp_path):
    run, jar = run_at(tmp_path)
    run.url = "about:blank"
    await store.restore(run)
    existing = {**cookie("app"), "domain": "app.test"}
    jar[cookie_key(existing)] = existing
    store.configure("enabled", "Default")
    service = BrowserService(tmp_path / "artifacts")
    service.cookies = store
    service.runs[run.thread_id] = run
    run.owner = "user"
    result = await service.sync_cookies(run.thread_id)
    assert (result["status"], result["count"], result["domains"]) == ("synced", 1, 1)
    assert {c["domain"] for c in jar.values()} == {"example.test", "app.test"}
    assert len(store._read()["cookies"]) == 2


async def test_save_failure_is_not_reported_as_import_success(store, monkeypatch):
    store.configure("enabled", "Default")
    def fail(_):
        raise OSError("disk full")
    monkeypatch.setattr(store, "_write", fail)
    await store.sync()
    assert store.state()["status"] == "save_failed"
    assert store.state()["count"] == 0


async def test_unchanged_cookies_do_not_read_or_rewrite_vault(store, tmp_path, monkeypatch):
    run, jar = run_at(tmp_path)
    await store.restore(run)
    jar[cookie_key(cookie())] = cookie()
    await store.capture(run)
    def unexpected_read():
        raise AssertionError("Unchanged browser cookies must not decrypt the vault")
    monkeypatch.setattr(store, "_read", unexpected_read)
    await store.capture(run)
