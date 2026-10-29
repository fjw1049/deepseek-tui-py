"""One-click setup: pinned, digest-checked LCU install and the Chrome connector steps."""

import hashlib
import io
import shutil
import tarfile
from pathlib import Path

import pytest

from deepseek_tui.cua import setup
from deepseek_tui.cua.session import CuaSession


def _release(path: Path, installer: str, extra: dict[str, bytes] | None = None) -> bytes:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in {"lcu-0.11.6-darwin-arm64/scripts/install.sh": installer.encode(),
                           **(extra or {})}.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            tar.addfile(info, io.BytesIO(data))
    return path.read_bytes()


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(setup, "target", lambda: "darwin-arm64")
    monkeypatch.setattr(setup, "chatgpt_installed", lambda: True)


def _serve(monkeypatch, archive: bytes):
    def download(url, destination):
        assert url.endswith("/v0.11.6/lcu-0.11.6-darwin-arm64.tar.gz")
        destination.write_bytes(archive)
        return hashlib.sha256(archive).hexdigest()

    monkeypatch.setattr(setup, "_download", download)


def test_connector_state_reads_only_the_connector_line():
    report = ("Chrome extension: could not check. EPERM\n"
              "Chrome connector: configured for this LCU installation.\n")
    assert setup.connector_state(report) == "installed"
    assert setup.connector_state("Chrome connector: missing or outdated.") == "missing"
    assert setup.connector_state("") == "unknown"


def test_installed_version_follows_the_current_release(tmp_path):
    release = tmp_path / "releases/0.11.6-56cc367c3ecc"
    (release / "bin").mkdir(parents=True)
    (release / "bin/lcu").write_text("")
    (release / "node-path").write_text("/node")
    (tmp_path / "current").symlink_to(release)
    assert setup.installed_version(tmp_path / "current") == "0.11.6"
    assert setup.installed_version(tmp_path / "missing") is None


@pytest.mark.asyncio
async def test_a_changed_download_is_never_installed(mac, monkeypatch, tmp_path):
    marker = tmp_path / "ran"
    archive = _release(tmp_path / "a.tgz", f"touch {marker}\n")
    _serve(monkeypatch, archive)
    monkeypatch.setitem(setup.LCU_SHA256, "darwin-arm64", "0" * 64)
    with pytest.raises(setup.SetupError, match="integrity"):
        await setup.install_lcu()
    assert not marker.exists()


@pytest.mark.asyncio
async def test_an_archive_escaping_its_directory_is_rejected(mac, monkeypatch, tmp_path):
    marker = tmp_path / "ran"
    archive = _release(tmp_path / "a.tgz", f"touch {marker}\n", {"../escape": b"x"})
    _serve(monkeypatch, archive)
    monkeypatch.setitem(setup.LCU_SHA256, "darwin-arm64", hashlib.sha256(archive).hexdigest())
    with pytest.raises(setup.SetupError, match="unpacked"):
        await setup.install_lcu()
    assert not marker.exists()


@pytest.mark.asyncio
async def test_a_verified_release_runs_its_installer_for_the_runtime_only(mac, monkeypatch,
                                                                         tmp_path):
    args = tmp_path / "args"
    archive = _release(tmp_path / "a.tgz", f'echo "$@" > {args}\necho installed\n')
    _serve(monkeypatch, archive)
    monkeypatch.setitem(setup.LCU_SHA256, "darwin-arm64", hashlib.sha256(archive).hexdigest())
    assert (await setup.install_lcu())["version"] == "0.11.6"
    assert args.read_text().split() == ["--runtime-only", "--yes"]


@pytest.mark.asyncio
async def test_failed_installer_reports_its_last_line(mac, monkeypatch, tmp_path):
    archive = _release(tmp_path / "a.tgz", "echo starting\necho 'needs permission' >&2\nexit 3\n")
    _serve(monkeypatch, archive)
    monkeypatch.setitem(setup.LCU_SHA256, "darwin-arm64", hashlib.sha256(archive).hexdigest())
    with pytest.raises(setup.SetupError, match="needs permission"):
        await setup.install_lcu()


@pytest.mark.asyncio
async def test_one_click_needs_a_supported_mac_and_the_chatgpt_app(monkeypatch):
    monkeypatch.setattr(setup, "target", lambda: None)
    with pytest.raises(setup.SetupError, match="Apple Silicon"):
        await setup.install_lcu()
    monkeypatch.setattr(setup, "target", lambda: "darwin-arm64")
    monkeypatch.setattr(setup, "chatgpt_installed", lambda: False)
    with pytest.raises(setup.SetupError, match="ChatGPT"):
        await setup.install_lcu()


@pytest.mark.asyncio
@pytest.mark.parametrize(("families", "expected"), [
    (["chrome"], {"connected": True, "reason": None}),
    ([], {"connected": False, "reason": "extension"}),
    (None, {"connected": False, "reason": "runtime"}),
])
async def test_chrome_check_lists_browsers_only(tmp_path, families, expected):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    calls = tmp_path / "calls.txt"
    client = tmp_path / "client.mjs"
    client.write_text(
        "import { appendFileSync } from 'node:fs';\n"
        "export function createCuaClient({ command }) { return {\n"
        f"  async connect() {{ appendFileSync({str(calls)!r},"
        " JSON.stringify(command) + '\\n'); },\n"
        "  async call(name, args) {\n"
        f"    appendFileSync({str(calls)!r}, args.code + '\\n');\n"
        + ("    throw new Error('runtime down');\n" if families is None else
           "    return { content: [{ type: 'text', text: '@@' + "
           f"JSON.stringify({families}) }}] }};\n")
        + "  },\n  async turnEnded() {}, async close() {} }; }\n")
    result = await setup.verify_chrome(node, client, Path("/opt/lcu/bin/lcu"))
    assert result == expected
    logged = calls.read_text()
    assert '["/opt/lcu/bin/lcu","--chrome"]' in logged
    assert "listTabs" not in logged and "getTab" not in logged


@pytest.mark.asyncio
async def test_setup_routes_report_steps_and_run_only_their_commands(client, monkeypatch,
                                                                    tmp_path):
    calls = tmp_path / "calls.txt"
    lcu = tmp_path / "lcu"
    lcu.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{calls}"\n'
        'if [ "$2" = status ]; then\n'
        "  echo 'Chrome extension: could not check.'\n"
        "  echo 'Chrome connector: configured for this LCU installation.'\n"
        "  exit 1\n"
        "fi\n")
    lcu.chmod(0o755)
    monkeypatch.setattr(CuaSession, "_paths", staticmethod(lambda _: ("node", "client", lcu)))
    monkeypatch.setattr(setup, "installed_version", lambda _: "0.11.6")
    monkeypatch.setattr(setup, "chatgpt_installed", lambda: True)
    monkeypatch.setattr(setup, "target", lambda: "darwin-arm64")

    state = (await client.get("/v1/cua/setup")).json()
    assert state["lcu"] == {"installed": True, "version": "0.11.6", "pinned": "0.11.6"}
    assert state["chromeConnector"] == "installed" and state["chatgpt"] is True
    assert (await client.post("/v1/cua/setup/chrome")).json() == {"ok": True}
    assert calls.read_text().split("\n")[:2] == ["browser status", "browser install"]

    async def verify(*args):
        return {"connected": True, "reason": None}

    monkeypatch.setattr(setup, "verify_chrome", verify)
    assert (await client.post("/v1/cua/setup/chrome/verify")).json()["connected"] is True

    async def failing():
        raise setup.SetupError("The LCU download failed its integrity check.")

    monkeypatch.setattr(setup, "install_lcu", failing)
    failed = await client.post("/v1/cua/setup/lcu")
    assert failed.status_code == 502 and "integrity" in failed.text
