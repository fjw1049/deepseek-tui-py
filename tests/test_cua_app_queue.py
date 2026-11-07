import asyncio
import os
import sys

import pytest

from deepseek_tui.cua import app_scope
from deepseek_tui.cua.session import DesktopLease


# Child runtimes import this checkout's package even when it is not installed.
CHILD_ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}


async def wait_records(lease, count):
    for _ in range(300):
        if len(lease.records()) == count:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"Expected {count} queue records")


async def test_three_places_fifo_and_cancelled_music_waiter(tmp_path):
    music, second, cancelled, last, notes, calculator, mail = [
        DesktopLease(tmp_path / "desktop.lock") for _ in range(7)
    ]
    pending = []
    try:
        await music.acquire(app="com.soda.music")
        for index, lease in enumerate((second, cancelled, last)):
            pending.append(asyncio.create_task(lease.acquire(app="com.soda.music")))
            await wait_records(music, index + 2)
        await asyncio.wait_for(notes.acquire(app="com.apple.Notes"), 1)
        await asyncio.wait_for(calculator.acquire(app="com.apple.calculator"), 1)
        pending.append(asyncio.create_task(mail.acquire(app="com.apple.mail")))
        await wait_records(music, 7)
        assert all(not task.done() for task in pending)
        pending[1].cancel()
        await asyncio.gather(pending[1], return_exceptions=True)
        notes.release()
        await asyncio.wait_for(pending[3], 1)
        music.release()
        await asyncio.wait_for(pending[0], 1)
        assert not pending[2].done()
        second.release()
        await asyncio.wait_for(pending[2], 1)
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for lease in (music, second, cancelled, last, notes, calculator, mail):
            lease.release()


async def test_separate_runtime_stop_and_crash_cleanup(tmp_path):
    path = tmp_path / "desktop.lock"
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        """
import asyncio, sys
from pathlib import Path
from deepseek_tui.cua.session import DesktopLease
async def run():
    lease = DesktopLease(Path(sys.argv[1]))
    lease.owner = 'background-music-evaluation'
    lease.can_stop = True
    await lease.acquire(app='com.soda.music')
    while not lease.stop_requested():
        await asyncio.sleep(.01)
    # Exit without calling release(), exercising OS cleanup.
asyncio.run(run())
""",
        str(path),
        env=CHILD_ENV,
    )
    waiter = DesktopLease(path)
    try:
        await wait_records(waiter, 1)
        key = waiter.records()[0]["key"]
        next_task = asyncio.create_task(waiter.acquire(app="com.soda.music"))
        await wait_records(waiter, 2)
        assert waiter.signal(key, "stop")
        await asyncio.wait_for(next_task, 3)
        assert await asyncio.wait_for(child.wait(), 2) == 0
        assert not waiter.signal(key, "stop")
        assert not waiter.stop_requested()
    finally:
        if child.returncode is None:
            child.terminate()
        await asyncio.wait_for(child.wait(), 3)
        waiter.release()


async def test_global_action_drains_running_apps_and_blocks_new_arrivals(tmp_path):
    player, text, system, calculator = [DesktopLease(tmp_path / "desktop.lock") for _ in range(4)]
    await player.acquire(app="com.soda.music")
    await text.acquire(app="com.apple.TextEdit")
    global_task = asyncio.create_task(system.acquire())
    await wait_records(system, 3)
    later = asyncio.create_task(calculator.acquire(app="com.apple.calculator"))
    await wait_records(system, 4)
    player.release()
    assert not global_task.done()
    text.release()
    await asyncio.wait_for(global_task, 2)
    assert not later.done()
    system.release()
    await asyncio.wait_for(later, 2)
    calculator.release()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ('let app = await cua.getApp("汽水音乐"); await app.click(29);', "com.soda.music"),
        ('await app.typeText("我不知为何"); await app.pressKey("Return");', "com.soda.music"),
        ("await app.getAXState({disableDiffing: true});", "com.soda.music"),
        ("await app.click(getIndex());", None),
        ('await app.pressKey("super+Tab");', None),
        ("await app.click(1); await notes.click(1);", None),
        ("await app.typeText(`hello ${await notes.click(1)}`);", None),
        ('await app.click(1); const mail = await cua.getApp("Mail");', None),
        ("await app.click(123456789012345678901234567890 + unknown);", None),
    ],
)
def test_only_proven_native_calls_share_the_desktop(code, expected, monkeypatch):
    monkeypatch.setattr(
        app_scope, "native_app", lambda name: "com.soda.music" if name == "汽水音乐" else None
    )
    assert (
        app_scope.js_scope(code, {"app": "com.soda.music", "notes": "com.apple.Notes"})[0]
        == expected
    )


async def test_http_queue_controls_distinguish_cancel_wait_from_stop(tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from deepseek_tui.cua import session
    from deepseek_tui.server.routes import router_mcp
    from deepseek_tui.tools.registry import ToolError

    monkeypatch.setattr(session, "LOCK_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router_mcp)
    owner, other, waiter = DesktopLease(), DesktopLease(), DesktopLease()
    owner.can_stop = other.can_stop = True
    await owner.acquire(app="com.soda.music")
    await other.acquire(app="com.apple.calculator")
    queued = asyncio.create_task(waiter.acquire(app="com.soda.music"))
    try:
        await wait_records(owner, 3)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            tasks = (await client.get("/v1/cua/tasks")).json()["tasks"]
            first, calc, pending = [task["key"] for task in tasks]
            assert [task["waiting"] for task in tasks] == [False, False, True]
            assert (await client.post(f"/v1/cua/tasks/{pending}/cancel")).is_success
            with pytest.raises(ToolError, match="cancelled this desktop wait"):
                await queued
            assert not owner.stop_requested() and not other.stop_requested()
            assert (await client.post(f"/v1/cua/tasks/{calc}/stop")).is_success
            assert other.stop_requested() and not owner.stop_requested()
            owner.release()
            await waiter.acquire(app="com.soda.music")
            assert (await client.post(f"/v1/cua/tasks/{first}/stop")).status_code == 409
            assert not waiter.stop_requested()
    finally:
        queued.cancel()
        await asyncio.gather(queued, return_exceptions=True)
        for lease in (owner, other, waiter):
            lease.release()


async def test_legacy_process_is_visible_and_blocks_every_app(tmp_path):
    import fcntl
    import json

    path = tmp_path / "desktop.lock"
    with path.open("w") as old:
        fcntl.flock(old, fcntl.LOCK_EX)
        json.dump({"owner": "assistant", "thread_id": "old-workbench"}, old)
        old.flush()
        player = DesktopLease(path)
        pending = asyncio.create_task(player.acquire(app="com.soda.music"))
        await wait_records(player, 2)
        legacy, queued = player.records()
        assert legacy["thread_id"] == "old-workbench" and not legacy["can_stop"]
        assert queued["waiting"]
    try:
        await asyncio.wait_for(pending, 2)
        assert len(player.records()) == 1
    finally:
        player.release()


def test_capture_failure_is_distinct_from_desktop_contention():
    from deepseek_tui.cua.tools import runtime_error

    for error in ["The screen capture failed.", "SCStreamErrorDomain Code=-3811"]:
        kind, _ = runtime_error("Computer Use server error -10005: " + error)
        assert kind == "screenshot_unavailable"


async def test_external_preview_http_is_private_and_expires_with_ticket(tmp_path, monkeypatch):
    import io
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI
    from PIL import Image

    from deepseek_tui.cua import session
    from deepseek_tui.server.routes import router_mcp

    monkeypatch.setattr(session, "LOCK_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router_mcp)
    app.state.thread_manager = SimpleNamespace(cua_ticket_session=lambda key: None)
    observer = DesktopLease()
    data = io.BytesIO()
    Image.new("RGB", (43, 71), "red").save(data, "PNG")
    screen = tmp_path / "screen.png"
    screen.write_bytes(data.getvalue())
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-c", """
import asyncio, sys
from pathlib import Path
from deepseek_tui.cua.session import DesktopLease
async def main():
    owner = DesktopLease(Path(sys.argv[1]))
    await owner.acquire(app="com.apple.TextEdit")
    owner.note_surface(preview=True)
    while True:
        if owner.ticket.with_suffix(".preview").exists():
            frame = owner.ticket.with_suffix(".frame")
            assert frame.stat().st_mode & 0o077 == 0
            owner.answer_preview(owner.ticket.stem, Path(sys.argv[2]).read_bytes())
        await asyncio.sleep(.01)
asyncio.run(main())
""", str(observer.path), str(screen), env=CHILD_ENV,
    )
    try:
        await wait_records(observer, 1)
        key = observer.records()[0]["key"]
        path = f"/v1/cua/tasks/{key}/frame"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            frames = await asyncio.gather(client.get(path), client.get(path))
            for frame in frames:
                assert frame.status_code == 200
                assert (frame.json()["width"], frame.json()["height"]) == (43, 71)
            assert not list(observer.directory.glob("*.frame"))
            child.kill()
            await child.wait()
            await observer.acquire(app="com.apple.TextEdit", timeout=1)
            assert (await client.get(path)).status_code == 404
            replacement = f'/v1/cua/tasks/{observer.info["key"]}/frame'
            assert (await client.get(replacement)).status_code == 404
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()
        observer.release()
