"""Octop recording with replay confined to the current Workbench session."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any

from browser.service import BrowserAction, BrowserRun, BrowserService


def recording_store(service: BrowserService, thread_id: str):
    from octop_browser.record.settings import RecordReplaySettings
    from octop_browser.record.store import RecordingStore

    return RecordingStore(
        RecordReplaySettings(base_dir=service.artifact_root / thread_id / "flows")
    )


def read_workflow(service: BrowserService, thread_id: str, recording_id: str):
    if not re.fullmatch(r"rec_[A-Za-z0-9_]+", recording_id):
        raise ValueError("Invalid workflow ID")
    return recording_store(service, thread_id).read_steps(recording_id)


async def start_recording(service: BrowserService, thread_id: str) -> dict[str, Any]:
    from octop_browser.record.models import PrivacySettings
    from octop_browser.record.recorder import RecordController

    run = service.runs.get(thread_id)
    if not run or not run.session:
        raise ValueError("Open a browser page first")
    async with run.lock:
        if run.owner != "user" or run.recorder or (run.demo_task and not run.demo_task.done()):
            raise ValueError("Take control and finish the current workflow first")
        controller = RecordController(
            store=recording_store(service, thread_id),
            settings=run.settings,
            profile_manager=run.profiles,
        )
        run.recorder, result = await controller.start_in_process(
            profile="workbench", privacy=PrivacySettings(input_policy="mask-all")
        )
        return result


async def finish_recording(run: BrowserRun) -> dict[str, Any]:
    from octop_browser.record.semantic import SemanticProcessor

    recorder, run.recorder = run.recorder, None
    if recorder is None:
        raise ValueError("No workflow is being recorded")
    try:
        result = await recorder.stop(generate_steps=False)
        recording_id = result["recordingId"]
        steps = SemanticProcessor(recording_id, recorder.store.read_events(recording_id)).process()
        recorder.store.write_steps(recording_id, steps)
        recorder.manifest.stats.steps = len(steps.steps)
        recorder.store.write_manifest(recorder.manifest)
        return {"recordingId": recording_id, "steps": len(steps.steps)}
    finally:
        await recorder.close()


def _demo_url(url: str) -> str:
    directory = Path(__file__).parent
    legacy = directory.parent / "deepseek_tui" / "browser_demo.html"
    return (directory / "browser_demo.html").as_uri() if url == legacy.as_uri() else url


def _url(url: str) -> str:
    url = _demo_url(url)
    if url != (Path(__file__).parent / "browser_demo.html").as_uri():
        BrowserAction(action="open", url=url)
    return url


async def start_replay(
    service: BrowserService, thread_id: str, recording_id: str, inputs: dict[str, str]
) -> dict[str, Any]:
    doc = read_workflow(service, thread_id, recording_id)
    if not doc.steps or len(doc.steps) > 200:
        raise ValueError("Workflow must contain 1–200 steps")
    supported = {"open", "navigate", "click", "fill", "press", "set_checked", "select"}
    for step in doc.steps:
        if step.kind not in supported:
            raise ValueError(f"Unsupported replay step: {step.kind}")
        if step.kind in {"open", "navigate"}:
            _url(step.url or "")
        if step.kind in {"fill", "select"}:
            for name in re.findall(r"\{\{([^{}]+)\}\}", step.value or ""):
                if name not in inputs:
                    raise ValueError(f"Missing replay input: {name}")
    if any(rule.get("type") != "url_contains" for rule in doc.verification):
        raise ValueError("Unsupported recorded verification rule")
    run = await service.ensure(thread_id)
    async with run.lock:
        if (
            run.owner != "user"
            or run.recorder
            or run.recording
            or (run.demo_task and not run.demo_task.done())
        ):
            raise ValueError("Take control and finish the current workflow first")
        run.owner = "agent"
        run.generation += 1
        run.activity, run.demo_status, run.error = "replay", "running", None
        run.demo_step, run.demo_total = 0, len(doc.steps)
        run.log.clear()
        service._persist(run)
        run.demo_task = asyncio.create_task(_replay(service, run, doc, inputs))
    return service.state(thread_id)


async def _step(run: BrowserRun, step: Any, inputs: dict[str, str]):
    session = run.session
    if step.kind in {"open", "navigate"}:
        return await session.navigate(_url(step.url or ""))
    if step.kind == "press":
        return await session.press(step.key or "Enter")
    target = step.target or {}
    selectors = target.get("selectorCandidates") or []
    selector = next((s for s in selectors if isinstance(s, str) and s), None)
    if not selector and target.get("id"):
        selector = "[id=" + json.dumps(target["id"]) + "]"
    if not selector:
        raise ValueError("Replay target has no stable selector; record this step again")
    matches = await session.eval_js(f"document.querySelectorAll({json.dumps(selector)}).length")
    if not matches.success or json.loads(matches.content) != 1:
        raise ValueError("Replay selector must match exactly one element")
    value = re.sub(r"\{\{([^{}]+)\}\}", lambda m: inputs[m[1]], step.value or "")
    if step.kind == "fill":
        return await session.fill(selector=selector, text=value)
    if step.kind == "select":
        return await session.select(selector=selector, value=value)
    if step.kind == "set_checked":
        result = await session.eval_js(
            f"document.querySelector({json.dumps(selector)})?.checked ?? null"
        )
        checked = json.loads(result.content) if result.success else None
        if not isinstance(checked, bool) or value not in {"true", "false"}:
            raise ValueError("Checkbox state unavailable")
        if checked == (value == "true"):
            return result
    return await session.click(selector=selector)


async def _replay(service: BrowserService, run: BrowserRun, doc: Any, inputs: dict[str, str]):
    try:
        async with run.lock:
            run.frames.clear()
            run.recording = True
        for index, step in enumerate(doc.steps, 1):
            async with run.lock:
                if run.owner != "agent":
                    raise ValueError("Browser control changed")
                run.demo_step = index
                run.revision += 1
                result = await asyncio.wait_for(_step(run, step, inputs), timeout=30)
                if not result.success:
                    raise ValueError(result.error or "Replay action failed")
                if index == 1 and shutil.which("ffmpeg") and run.video is None:
                    await service.start_video(run)
                if step.expect and step.expect.get("urlContains"):
                    result = await run.session.wait(
                        url_contains=_demo_url(step.expect["urlContains"]), timeout_ms=10000
                    )
                    if not result.success:
                        raise ValueError(result.error or "Navigation check failed")
                run.log.append({"action": step.kind, "success": True})
                if run.recording:
                    run.frames.append(await service._capture(run))
                    if len(run.frames) >= 40:
                        service._finish_recording(run)
                service._persist(run)
            await asyncio.sleep(0.2)
        async with run.lock:
            for rule in doc.verification:
                result = await run.session.wait(
                    url_contains=_demo_url(rule["value"]), timeout_ms=10000
                )
                if not result.success:
                    raise ValueError(result.error or "Final URL verification failed")
            service._save(run, await service._capture(run), ".jpg", "页面截图")
        run.demo_status = "passed"
    except asyncio.CancelledError:
        run.demo_status = "stopped"
        raise
    except Exception as exc:
        run.demo_status, run.error = "failed", str(exc)
        run.log.append({"action": "replay", "success": False})
        try:
            async with run.lock:
                service._save(run, await service._capture(run), ".jpg", "失败现场")
        except Exception:
            pass
    finally:
        await service.stop_video(run)
        if run.recording:
            service._finish_recording(run)
        service._persist(run)
