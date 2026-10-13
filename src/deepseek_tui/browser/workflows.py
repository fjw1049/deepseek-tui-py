"""Octop recording with replay confined to the current Workbench session."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from deepseek_tui.browser.service import BrowserAction, BrowserRun, BrowserService


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


def assert_capture_complete(service: BrowserService, thread_id: str, recording_id: str):
    store = recording_store(service, thread_id)
    try:
        manifest = store.read_manifest(recording_id)
    except FileNotFoundError:
        manifest = None  # Legacy/test documents may not have a manifest.
    if manifest is not None and manifest.status != "stopped":
        raise ValueError("Recording contains incomplete browser capture; inspect it before replay")
    if any(
        event.get("kind") == "capture_warning"
        for event in store.read_events(recording_id)
    ):
        raise ValueError("Recording contains incomplete browser capture; inspect it before replay")


def validate_scope(target):
    target = target or {}
    frame_path = target.get("framePath")
    shadow_path = target.get("shadowPath")
    frame_path = [] if frame_path is None else frame_path
    shadow_path = [] if shadow_path is None else shadow_path
    BrowserAction(action="observe", frame_path=frame_path)
    BrowserAction(action="observe", shadow_path=shadow_path)
    frame_url = target.get("frameUrl")
    if frame_url is not None and (not isinstance(frame_url, str) or not 0 < len(frame_url) <= 4096):
        raise ValueError("Recorded frame URL must be a nonempty string of at most 4096 characters")
    return frame_path, shadow_path


async def start_recording(service: BrowserService, thread_id: str) -> dict[str, Any]:
    from deepseek_tui.browser.recording import create_recording

    run = service.runs.get(thread_id)
    if not run or not run.session:
        raise ValueError("Open a browser page first")
    async with run.lock:
        if run.owner != "user" or run.recorder or (run.demo_task and not run.demo_task.done()):
            raise ValueError("Take control and finish the current workflow first")
        run.recorder, result = await create_recording(run, recording_store(service, thread_id))
        return result


async def finish_recording(run: BrowserRun) -> dict[str, Any]:
    from deepseek_tui.browser.recording import ScopedSemanticProcessor

    recorder, run.recorder = run.recorder, None
    if recorder is None:
        raise ValueError("No workflow is being recorded")
    try:
        result = await recorder.stop(generate_steps=False)
        recording_id = result["recordingId"]
        steps = ScopedSemanticProcessor(
            recording_id, recorder.store.read_events(recording_id)
        ).process()
        recorder.store.write_steps(recording_id, steps)
        recorder.manifest.stats.steps = len(steps.steps)
        if getattr(recorder, "capture_warnings", None):
            recorder.manifest.status = "failed"
        recorder.store.write_manifest(recorder.manifest)
        if recorder.manifest.status == "failed":
            raise ValueError(
                "Recording contains incomplete browser capture; saved evidence requires review"
            )
        return {"recordingId": recording_id, "steps": len(steps.steps)}
    finally:
        await recorder.close()


def _demo_url(url: str) -> str:
    directory = Path(__file__).parent
    legacy = {
        (directory.parent / "browser_demo.html").as_uri(),
        (directory.parent.parent / "browser" / "browser_demo.html").as_uri(),
    }
    return (directory / "browser_demo.html").as_uri() if url in legacy else url


def _url(url: str) -> str:
    url = _demo_url(url)
    if url != (Path(__file__).parent / "browser_demo.html").as_uri():
        BrowserAction(action="open", url=url)
    return url


async def start_replay(
    service: BrowserService, thread_id: str, recording_id: str, inputs: dict[str, str]
) -> dict[str, Any]:
    doc = read_workflow(service, thread_id, recording_id)
    assert_capture_complete(service, thread_id, recording_id)
    doc = compile_workflow(doc, inputs)
    run = await service.ensure(thread_id)
    async with run.lock:
        if run.unresolved:
            raise ValueError("Review unresolved browser operations before replay")
        if (
            run.owner != "user"
            or run.recorder
            or run.recording
            or (run.demo_task and not run.demo_task.done())
        ):
            raise ValueError("Take control and finish the current workflow first")
        # CSS grammar checks are read-only and precede ownership or page changes.
        from deepseek_tui.browser.observation import evaluate, root_context

        selectors = []
        for step in doc.steps:
            selectors.extend(_selectors(step.target or {}))
            frames, shadows = validate_scope(step.target)
            selectors.extend(shadows)
            for frame in frames:
                selectors.extend([frame] if isinstance(frame, str) else
                                 [frame["selector"], *frame.get("shadowPath", [])])
        for rule in doc.verification:
            selectors.extend([rule["selector"]] if rule.get("selector") else [])
            if rule["type"] == "selector_exists":
                selectors.append(rule["value"])
        if selectors:
            valid = await evaluate(await root_context(run), "(()=>{try{for(const s of " +
                json.dumps(selectors) + ")document.querySelectorAll(s);return true}catch{return false}})()")
            if valid is not True:
                raise ValueError("Workflow contains invalid CSS selector syntax; no step was executed")
        run.owner = "agent"
        run.generation += 1
        run.activity, run.demo_status, run.error = "replay", "running", None
        run.demo_step, run.demo_total = 0, len(doc.steps)
        run.log.clear()
        run.replay_tabs.clear()
        run.replay_upload_files = frozenset(path for step in doc.steps if step.kind == "upload"
                                           for path in json.loads(step.value or "[]"))
        service._persist(run)
        run.demo_task = asyncio.create_task(_replay(service, run, doc, None))
    return service.state(thread_id)


def _selectors(target):
    selectors = target.get("selectorCandidates")
    if selectors is None or selectors == []:
        identifier = target.get("id")
        selectors = ["[id=" + json.dumps(identifier) + "]"] if identifier else []
    if not isinstance(selectors, list) or any(
        not isinstance(s, str) or not s.strip() for s in selectors
    ):
        raise ValueError("Replay selectors must be a list of nonempty strings")
    for selector in selectors:
        BrowserAction(action="observe", selector=selector)
    return selectors


def compile_workflow(doc, inputs):
    """Freeze and validate all static inputs before acquiring browser control."""
    def substitute(value):
        if isinstance(value, str):
            def replace(match):
                if match[1] not in inputs or not isinstance(inputs[match[1]], str):
                    raise ValueError("Missing string replay input: " + match[1])
                return inputs[match[1]]
            return re.sub(r"\{\{([^{}]+)\}\}", replace, value)
        if isinstance(value, list):
            return [substitute(v) for v in value]
        if isinstance(value, dict):
            return {k: substitute(v) for k, v in value.items()}
        return value
    # Substitute effect and verification fields once; never write real inputs back to storage.
    data = doc.model_dump()
    data["steps"] = substitute(data["steps"])
    data["verification"] = substitute(data["verification"])
    doc = type(doc).model_validate(data)
    if not doc.steps or len(doc.steps) > 200:
        raise ValueError("Workflow must contain 1–200 steps")
    supported = {"open", "navigate", "new_tab", "switch_tab", "click", "fill", "press", "set_checked", "select", "upload", "handle_dialog"}
    aliases = {"main"}
    for step in doc.steps:
        if step.kind not in supported:
            raise ValueError(f"Unsupported replay step: {step.kind}")
        try:
            target = step.target or {}
            alias = target.get("tabAlias", "main")
            if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,49}", alias):
                raise ValueError("Invalid replay tab alias")
            if step.kind == "new_tab":
                if alias in aliases:
                    raise ValueError("Replay tab alias must be newly declared")
                aliases.add(alias)
            elif alias not in aliases:
                raise ValueError("Replay tab alias must be declared before use")
            validate_scope(target)
            for key in ("id", "tag", "type", "role", "accessibleName", "name", "label", "text"):
                if key in target and not isinstance(target[key], str):
                    raise ValueError("Replay target descriptors must contain strings")
            selectors = _selectors(target)
            step.value = step.value or ""
            if step.kind in {"open", "navigate", "new_tab"}:
                step.url = _url(step.url or "")
            elif step.kind == "switch_tab":
                BrowserAction(action="switch_tab", tab_id=alias)
            elif step.kind == "handle_dialog":
                BrowserAction(action="handle_dialog", dialog_id="current", accept=target.get("accept"), text=step.value)
            else:
                if not selectors and (step.kind != "press" or target):
                    raise ValueError("Replay target requires a selector candidate")
                if step.kind == "set_checked" and step.value not in {"true", "false"}:
                    raise ValueError("Checkbox state must be true or false")
                files = []
                if step.kind == "upload":
                    try:
                        files = json.loads(step.value)
                    except ValueError:
                        raise ValueError("Upload input must be a JSON list of explicit file paths") from None
                    BrowserAction(action="upload", selector=selectors[0], files=files)
                    for filename in files:
                        if not Path(filename).expanduser().is_file():
                            raise ValueError("Upload file does not exist")
                    files = [str(Path(filename).expanduser().resolve(strict=True)) for filename in files]
                    step.value = json.dumps(files)
                BrowserAction(
                    action=step.kind, selector=selectors[0] if selectors else None,
                    text=step.value, key=step.key or "Enter",
                    checked=(step.value == "true") if step.kind == "set_checked" else None,
                )
            if step.expect:
                if set(step.expect) != {"urlContains"}:
                    raise ValueError("Unsupported recorded step expectation")
                BrowserAction(action="wait", url_contains=step.expect["urlContains"])
        except ValidationError as exc:
            # Pydantic's default rendering includes the actual (potentially private) input.
            errors = exc.errors(include_input=False, include_url=False)
            raise ValueError("Invalid replay step " + step.id + ": " +
                             "; ".join(e["msg"] for e in errors)) from None
    for rule in doc.verification:
        if rule.get("tabAlias", "main") not in aliases:
            raise ValueError("Verification tab alias must be declared before use")
        if rule.get("type") not in {
            "url_contains",
            "text_contains",
            "selector_exists",
            "title_contains",
            "element_text_contains",
            "input_value_equals",
            "checked_equals",
            "selected_equals",
        }:
            raise ValueError("Unsupported recorded verification rule")
        if rule["type"] == "checked_equals":
            if not isinstance(rule.get("value"), bool):
                raise ValueError("checked_equals requires a boolean value")
        elif not isinstance(rule.get("value"), str):
            raise ValueError("Verification requires a string value")
        if rule["type"] in {"element_text_contains", "input_value_equals", "checked_equals", "selected_equals"} and not rule.get(
            "selector"
        ):
            raise ValueError("Verification requires a unique selector")
        kind, value = rule["type"], rule["value"]
        validate_scope(rule)
        try:
            if kind == "url_contains":
                BrowserAction(action="wait", url_contains=value)
            elif kind == "selector_exists":
                BrowserAction(action="wait", selector=value)
            elif kind == "checked_equals":
                BrowserAction(action="wait", condition=kind, selector=rule["selector"], checked=value)
            else:
                BrowserAction(action="fill" if kind == "input_value_equals" else "wait",
                              text=value, selector=rule.get("selector"))
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
            raise ValueError("Invalid replay verification: " +
                             "; ".join(e["msg"] for e in errors)) from None
    return doc


async def _step(service: BrowserService, run: BrowserRun, step: Any, inputs: dict[str, str] | None):
    generation = run.generation
    alias = (step.target or {}).get("tabAlias", "main")
    if step.kind == "handle_dialog":
        dialog = run.native_events.dialog if run.native_events else None
        if not dialog:
            raise ValueError("Recorded native dialog did not appear")
        return await service.action(run.thread_id, BrowserAction(action="handle_dialog", dialog_id=dialog["id"],
            accept=(step.target or {}).get("accept"), text=step.value or "", generation=generation))
    if step.kind != "new_tab" and alias in run.replay_tabs:
        current = next((tab for tab in run.tabs if tab.get("active")), {})
        if current.get("tab_id") != run.replay_tabs[alias]:
            switched = await service.action(run.thread_id, BrowserAction(action="switch_tab",
                tab_id=run.replay_tabs[alias], generation=generation))
            if not switched["success"]:
                return switched
    if step.kind == "switch_tab":
        if alias not in run.replay_tabs:
            raise ValueError("Recorded task tab was not opened in this replay")
        return {"success": True, "content": "Recorded task tab selected"}
    if step.kind in {"open", "navigate", "new_tab"}:
        # _url permits only HTTP(S) and the bundled demonstration fixture.
        action = BrowserAction(action="new_tab" if step.kind == "new_tab" else "open", url="http://localhost").model_copy(
            update={"url": _url(step.url or ""), "generation": generation}
        )
        result = await service.action(run.thread_id, action)
        if result["success"]:
            tab = next((tab["tab_id"] for tab in run.tabs if tab.get("active")), None)
            if tab:
                run.replay_tabs[alias] = tab
        return result
    target = step.target or {}
    frame_path, shadow_path = validate_scope(target)
    frame_id = ""
    if frame_path:
        from deepseek_tui.browser.frames import resolve_frame_path

        async with run.lock:
            if run.owner != "agent" or run.generation != generation:
                raise ValueError("Browser control changed")
            frame_id = await resolve_frame_path(run.session._internal.client, frame_path)
    selector = None
    selectors = _selectors(target)
    observation = None
    for candidate in selectors:
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            observed = await service.action(
                run.thread_id,
                BrowserAction(
                    action="observe", selector=candidate, level="full", generation=generation,
                    shadow_path=shadow_path,
                    frame_id=frame_id,
                ),
            )
        except RuntimeError:
            continue
        if frame_id and target.get("frameUrl") is not None:
            from octop_browser.record.privacy import redact_url

            if redact_url(observed["observation"]["url"]) != target["frameUrl"]:
                raise ValueError("Recorded frame URL changed; no target action was sent")
        elements = observed["observation"]["elements"]
        expected_name = (
            target.get("accessibleName")
            or target.get("name")
            or target.get("label")
            or target.get("text")
        )
        if not elements or (expected_name and elements[0]["name"] != expected_name.strip()[:300]):
            continue
        element = elements[0]
        if target.get("scope") and target["scope"] != element.get("scope"):
            raise ValueError("Recorded business scope changed; no target action was sent")
        if any(
            target.get(k) and target[k].lower() != element.get(k, "").lower()
            for k in ("tag", "type")
        ):
            continue
        role = element["role"]
        if role == element.get("tag"):
            role = {"a": "link", "textarea": "textbox", "select": "combobox"}.get(role, role)
            if role == "input":
                role = {
                    "checkbox": "checkbox",
                    "radio": "radio",
                    "range": "slider",
                    "submit": "button",
                    "reset": "button",
                    "button": "button",
                    "image": "button",
                }.get(element.get("type"), "textbox")
        if target.get("role") and target["role"] != role:
            continue
        selector, observation = candidate, observed["observation"]
        break
    if not selector and (step.kind != "press" or target):
        raise ValueError("Replay target must have one current, matching, observable element")
    if observation is None:
        observation = (
            await service.action(
                run.thread_id, BrowserAction(action="observe", generation=generation)
            )
        )["observation"]
    value = step.value or ""
    if inputs is not None:
        value = re.sub(r"\{\{([^{}]+)\}\}", lambda m: inputs[m[1]], value)
    action = BrowserAction(
        action=step.kind,
        selector=None if shadow_path or frame_id else selector,
        ref=observation["elements"][0]["ref"] if shadow_path or frame_id else None,
        frame_id=frame_id,
        observation_id=observation["observation_id"],
        generation=generation,
        text=value,
        key=step.key or "Enter",
        checked=(value == "true") if step.kind == "set_checked" else None,
        files=json.loads(value) if step.kind == "upload" else [],
    )
    if step.kind == "set_checked" and value not in {"true", "false"}:
        raise ValueError("Checkbox state must be true or false")
    return await service.action(run.thread_id, action, require_observation=True)


async def _verify(service: BrowserService, run: BrowserRun, rule: dict[str, Any]) -> None:
    kind, value = rule["type"], rule["value"]
    args = {"generation": run.generation, "timeout_ms": 10000}
    if rule.get("tabAlias"):
        alias = rule["tabAlias"]
        if alias not in run.replay_tabs:
            raise ValueError("Verification task tab was not opened")
        await service.action(run.thread_id, BrowserAction(action="switch_tab",
            tab_id=run.replay_tabs[alias], generation=run.generation))
    frame_path, shadow_path = validate_scope(rule)
    args["shadow_path"] = shadow_path
    if frame_path:
        args["frame_path"] = frame_path
    if kind == "url_contains":
        args["url_contains"] = _demo_url(value)
    elif kind == "selector_exists":
        args["selector"] = value
    elif kind == "checked_equals":
        args.update(selector=rule["selector"], checked=value)
    else:
        args["text"] = value
        if rule.get("selector"):
            args["selector"] = rule["selector"]
    args["condition"] = "text_contains" if kind == "element_text_contains" else kind
    result = await service.action(run.thread_id, BrowserAction(action="wait", **args))
    passed = result["success"]
    run.log.append({"action": "verify", "success": passed is True, "effect":
                    "confirmed" if passed is True else "not_confirmed"})
    if passed is not True:
        raise ValueError("Recorded verification failed: " + kind)


async def _replay(service: BrowserService, run: BrowserRun, doc: Any, inputs: dict[str, str] | None):
    try:
        async with run.lock:
            run.frames.clear()
            run.recording = True
        for index, step in enumerate(doc.steps, 1):
            if run.owner != "agent":
                raise ValueError("Browser control changed")
            run.demo_step = index
            result = await _step(service, run, step, inputs)
            if not result["success"]:
                raise ValueError(str(result.get("content") or "Replay action failed"))
            if index == 1 and shutil.which("ffmpeg") and run.video is None:
                try:
                    await service.start_video(run)
                except Exception as exc:
                    run.log.append({"action": "evidence", "success": False, "error": str(exc)})
            if step.expect and step.expect.get("urlContains"):
                await _verify(
                    service, run, {"type": "url_contains", "value": step.expect["urlContains"]}
                )
        for rule in doc.verification:
            await _verify(service, run, rule)
        async with run.lock:
            try:
                service._save(run, await service._capture(run), ".jpg", "页面截图")
            except Exception as exc:
                run.log.append({"action": "evidence", "success": False, "error": str(exc)})
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
        run.replay_upload_files = frozenset()
        try:
            await service.stop_video(run)
        except Exception as exc:
            run.log.append({"action": "evidence", "success": False, "error": str(exc)})
        if run.recording or run.frames:
            try:
                service._finish_recording(run)
            except Exception as exc:
                run.log.append({"action": "evidence", "success": False, "error": str(exc)})
        try:
            service._persist(run)
        except OSError as exc:
            run.log.append({"action": "evidence", "success": False, "error": str(exc)})
