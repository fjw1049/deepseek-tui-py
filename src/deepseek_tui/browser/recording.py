"""Scoped Workbench capture using Octop's validated recording transport and store."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from octop_browser.cdp.client import CDPClient
from octop_browser.record.models import (
    PrivacySettings,
    RecordingManifest,
    RecordingTarget,
    SemanticStep,
)
from octop_browser.record.privacy import is_sensitive_target, redact_url
from octop_browser.record.recorder import RecordSession
from octop_browser.record.semantic import SemanticProcessor, _stable_input_name

from deepseek_tui.browser.frames import FrameContext, discover_frames
from deepseek_tui.browser.observation import (
    ACCESSIBLE_NAME,
    CANONICAL_ROLE,
    READ_TEXT,
    SCOPE_CONTEXT,
    VISIBLE,
    DocumentContext,
    document_identity,
    evaluate,
)

RECORDER_WORLD = "deepseek-recorder"


class ScopedSemanticProcessor(SemanticProcessor):
    def _filter_events(self, events):
        useful = {id(event) for event in super()._filter_events(events)}
        return [
            event for event in events if id(event) in useful or event.get("kind") == "native_dialog"
        ]

    def _build_steps(self, events, start_url):
        # Octop compares IDs/names across trees. Compile contiguous scopes separately
        # so a shadow input cannot consume a same-named input in the parent page.
        blocks, block, scope = [], [], None
        for original in events:
            event = dict(original)
            target = event.get("target") or {}
            if event.get("kind") == "native_dialog":
                if block:
                    blocks.append(block)
                blocks.append([event])
                block, scope = [], None
                continue
            if target:
                current = (
                    event.get("targetId"),
                    json.dumps(target.get("framePath") or [], sort_keys=True),
                    tuple(target.get("shadowPath") or []),
                    target.get("frameUrl"),
                    json.dumps(target.get("scope"), sort_keys=True),
                )
                if block and current != scope:
                    blocks.append(block)
                    block = []
                scope = current
            if event.get("redacted") and event.get("kind") in {"input", "change"}:
                # Masked values are all equal; equality cannot prove edits are duplicates.
                event["value"] = "{{recorded_input_" + str(event["seq"]) + "}}"
            block.append(event)
        if block:
            blocks.append(block)
        steps, aliases, active_tab = [], {}, None
        for index, block in enumerate(blocks):
            tab = next((e.get("targetId") for e in block if e.get("targetId")), None)
            if tab and tab != active_tab:
                if tab not in aliases:
                    alias = "main" if not aliases else "tab_" + str(len(aliases))
                    aliases[tab] = alias
                    if steps:
                        url = next(
                            (
                                e.get("page", {}).get("url")
                                for e in block
                                if e.get("page", {}).get("url")
                            ),
                            "",
                        )
                        steps.append(
                            SemanticStep(
                                id="pending",
                                kind="new_tab",
                                url=url,
                                target={"tabAlias": alias},
                                description="Open recorded task tab",
                            )
                        )
                elif steps:
                    steps.append(
                        SemanticStep(
                            id="pending",
                            kind="switch_tab",
                            target={"tabAlias": aliases[tab]},
                            description="Return to recorded task tab",
                        )
                    )
                active_tab = tab
            compiled = super()._build_steps(block, start_url)
            for event in block:
                if event.get("kind") == "native_dialog":
                    compiled.append(
                        SemanticStep(
                            id="pending",
                            kind="handle_dialog",
                            value="{{dialog_answer_" + str(event.get("seq", 0)) + "}}"
                            if event.get("value")
                            else "",
                            target={"accept": event["accept"]},
                            description="Answer the recorded native dialog",
                        )
                    )
            frame_url = next(
                (
                    (e.get("target") or {}).get("frameUrl")
                    for e in block
                    if (e.get("target") or {}).get("frameUrl")
                ),
                None,
            )
            for step in compiled:
                if tab:
                    step.target = {**(step.target or {}), "tabAlias": aliases[tab]}
                original = next(
                    (
                        e.get("target")
                        for e in block
                        if e.get("target")
                        and (
                            e["target"].get("selectorCandidates")
                            == (step.target or {}).get("selectorCandidates")
                            or e["target"].get("id")
                            and e["target"].get("id") == (step.target or {}).get("id")
                        )
                    ),
                    None,
                )
                if original:
                    for key in ("framePath", "shadowPath", "scope"):
                        if key in original:
                            step.target[key] = original[key]
                    if original.get("type") == "file" and step.kind == "fill":
                        step.kind = "upload"
                if frame_url and (step.target or {}).get("framePath"):
                    step.target["frameUrl"] = frame_url
            if index and compiled and compiled[0].kind == "open":
                compiled.pop(0)
            # Interactions scroll their own target into view; a recorded page offset
            # is not a replayable step and would block the whole workflow.
            compiled = [step for step in compiled if step.kind not in {"new_tab", "scroll_to"}]
            steps.extend(compiled)
        for index, step in enumerate(steps, 1):
            step.id = f"step_{index:03d}"
        return steps

    def _infer_variables(self, steps):
        # Every value is masked, so Octop would name them all "sensitive_value";
        # name them by field instead and flag only secret-looking fields.
        inputs, known = [], set()
        for step in steps:
            if step.kind not in {"fill", "select"} or not step.value:
                continue
            base = _stable_input_name(step.target, "")
            name, index = base, 2
            while name in known:
                name, index = f"{base}_{index}", index + 1
            known.add(name)
            step.value = "{{" + name + "}}"
            target = step.target or {}
            secret = is_sensitive_target(target) or target.get("type") == "password"
            inputs.append({"name": name, "kind": "secret" if secret else "string",
                           "required": True, "sensitive": secret})
        for step in steps:
            if step.kind not in {"upload", "handle_dialog"}:
                continue
            for name in re.findall(r"\{\{([^{}]+)\}\}", step.value or ""):
                if name not in known:
                    inputs.append(
                        {
                            "name": name,
                            "required": True,
                            "sensitive": True,
                            "kind": "files" if step.kind == "upload" else "text",
                            "description": "JSON list of explicit file paths"
                            if step.kind == "upload"
                            else "Native prompt answer",
                        }
                    )
                    known.add(name)
        return steps, inputs


class WorkbenchRecordSession(RecordSession):
    # Seconds a stop waits for pages still loading (often after the last click) to get a recorder.
    flush_wait = 3.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scripts = {}
        self.frames = {}
        self.frame_changed = asyncio.Event()
        self.frame_lock = asyncio.Lock()
        self.capture_warnings = set()
        self.navigations = set()
        # "user" for a demonstration, "agent" for capturing the agent's own run.
        self.actor = "user"
        self.workbench = None
        self.target_lock = asyncio.Lock()
        # Workbench tabs open before recording started were not opened by it.
        self.initial_tabs = set()
        # Tabs the recorder could not attach to yet, with the reason shown to the user.
        self.tab_errors = {}

    def _append(self, event):
        event = dict(event)
        if event.get("kind") == "capture_warning":
            self.capture_warnings.add(event.get("error", "Incomplete browser capture"))
        if (event.get("target") or {}).get("frameUrl"):
            event["target"] = {
                **event["target"],
                "frameUrl": redact_url(event["target"]["frameUrl"], self.manifest.privacy),
            }
        super()._append(event)

    def _on_binding_called(self, params):
        if (
            self.active
            and params.get("name") == self.binding_name
            and len(str(params.get("payload", "")).encode("utf-8"))
            > self.rr_settings.max_event_bytes
        ):
            self._warn("Recording event exceeded the capture size limit")
            return
        try:
            super()._on_binding_called(params)
        except Exception:
            with suppress(Exception):
                self._warn("Recording event could not be stored")

    def _rate_limit_ok(self):
        allowed = super()._rate_limit_ok()
        if not allowed:
            self._warn("Recording event rate exceeded the capture limit")
        return allowed

    def _warn(self, message):
        if message not in self.capture_warnings:
            self.capture_warnings.add(message)
            self._append({"kind": "capture_warning", "error": message})

    def _recorder_source(self, target_id=None, *, frame_path=None, page=None):
        config = {
            "recordingId": self.manifest.recording_id,
            "bindingName": self.binding_name,
            "nonce": self.nonce,
            "targetId": target_id or "",
            "framePath": frame_path or [],
            "page": page,
        }
        source = Path(__file__).with_suffix(".js").read_text()
        source = source.replace("__VISIBLE__", VISIBLE).replace("__READ_TEXT__", READ_TEXT)
        source = source.replace("__NAME__", ACCESSIBLE_NAME).replace("__ROLE__", CANONICAL_ROLE)
        source = source.replace("__SCOPE_CONTEXT__", SCOPE_CONTEXT)
        return "globalThis.__HBR_RECORDER_CONFIG__=" + json.dumps(config) + ";\n" + source

    async def _install_on_client(self, client, target_id):
        client.on("Runtime.bindingCalled", self._on_binding_called)
        client.on("Page.frameNavigated", lambda params: self._frame_navigated(params, target_id))
        client.on("Page.frameAttached", lambda params: self.frame_changed.set())
        for domain in ("Runtime", "Page", "DOM"):
            await client.enable_domain(domain)
        world = await self._world(client)
        main_frame = world.identity[0]
        # History API changes are invisible to the isolated recorder; CDP reports them.
        def within_document(params):
            if params.get("frameId") == main_frame:
                task = asyncio.create_task(
                    self._navigated_within_document(client, params.get("url"), target_id)
                )
                self.navigations.add(task)
                task.add_done_callback(self.navigations.discard)

        client.on("Page.navigatedWithinDocument", within_document)
        # Page scripts must not reach the binding or nonce, or they could forge steps.
        await client.send(
            "Runtime.addBinding",
            {"name": self.binding_name, "executionContextName": RECORDER_WORLD},
        )
        source = self._recorder_source(target_id)
        script = await client.send(
            "Page.addScriptToEvaluateOnNewDocument", {"source": source, "worldName": RECORDER_WORLD}
        )
        self.scripts[id(client)] = script["identifier"]
        await evaluate(world, "(()=>{" + source + ";return true})()")

    async def _navigated_within_document(self, client, url, target_id):
        # Flush debounced edits first so a live-search entry precedes its URL change.
        with suppress(Exception):
            await evaluate(
                await self._world(client),
                "(()=>{globalThis.__deepseekRecorder?.flush();return true})()",
            )
        self._on_frame_navigated({"frame": {"url": url}}, target_id)

    async def _world(self, client):
        """The top document's recorder world; the same name always yields the same context."""
        frame = (await client.send("Page.getFrameTree"))["frameTree"]["frame"]["id"]
        world = await client.send(
            "Page.createIsolatedWorld", {"frameId": frame, "worldName": RECORDER_WORLD}
        )
        return DocumentContext(client, (frame, ""), world["executionContextId"])

    def _frame_navigated(self, params, target_id):
        self.frame_changed.set()
        if not params.get("frame", {}).get("parentId"):
            self._on_frame_navigated(params, target_id)

    async def start(self):
        if self.workbench:
            self.initial_tabs = {target["id"] for target in await self._target_infos()}
        await super().start()
        await self._sync_frames()
        if self.workbench and self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_targets())

    async def _target_infos(self):
        if self.workbench is None:
            return await super()._target_infos()
        from deepseek_tui.browser.workbench import control, tab_url

        bridge, browser_id = self.workbench
        listing = await control(bridge, "Workbench.listTabs", {"browserId": browser_id})
        return [{"id": tab["tab_id"], "url": tab["url"], "title": tab["title"],
                 "webSocketDebuggerUrl": tab_url(bridge, tab["tab_id"])}
                for tab in listing["tabs"]]

    async def _attach_known_targets(self, targets=None):
        if self.workbench is None:
            return await super()._attach_known_targets()
        async with self.target_lock:
            for target in targets if targets is not None else await self._target_infos():
                target_id = target["id"]
                if target_id in self._clients:
                    continue
                client = CDPClient(timeout=self.client._timeout)
                try:
                    await client.connect(target["webSocketDebuggerUrl"])
                    await self._install_on_client(client, target_id)
                except BaseException as exc:
                    with suppress(Exception):
                        await client.close()
                    if not isinstance(exc, Exception):
                        raise
                    # Retried on every poll; the tab stays blocked with this reason meanwhile.
                    self.tab_errors[target_id] = str(exc) or type(exc).__name__
                    self._warn(f"Could not record Workbench tab: {exc}")
                    continue
                self.tab_errors.pop(target_id, None)
                self._clients[target_id] = client
                self._client_target_ids[id(client)] = target_id
                if target_id not in self.initial_tabs:
                    self._append({"kind": "page_opened", "targetId": target_id,
                                  "url": target["url"], "title": target["title"],
                                  "initial": False})

    async def _sync_frames(self):
        async with self.frame_lock:
            await self._sync_frames_locked()

    async def _install_on_frame(self, client, target_id, frame_id, key, page):
        context = await FrameContext.create(client, frame_id)
        try:
            path = await context.owner_path()
            await context._send("Runtime.enable")
            if context.session_id:
                context.on("Runtime.bindingCalled", self._on_binding_called)
            await context._send(
                "Runtime.addBinding",
                {"name": self.binding_name, "executionContextId": context.context_id},
            )
            source = self._recorder_source(target_id, frame_path=path, page=page)
            await evaluate(context, "(()=>{" + source + ";return true})()")
            self.frames[key] = context, await document_identity(context)
        except BaseException:
            await context.close()
            raise

    async def _sync_frames_locked(self):
        alive = set()
        for target_id, client in list(self._clients.items()):
            frames = await discover_frames(client)
            page = await evaluate(client, "({url:location.href,title:document.title})")
            for frame in frames[1:]:
                key = (target_id, frame["id"])
                alive.add(key)
                existing = self.frames.get(key)
                if existing:
                    context, identity = existing
                    try:
                        if await document_identity(context) == identity:
                            config = json.dumps(
                                {"page": page, "framePath": await context.owner_path()}
                            )
                            refreshed = await evaluate(
                                context,
                                "(()=>{const r=globalThis.__deepseekRecorder;"
                                "if(!r)return false;Object.assign(r.config,"
                                + config
                                + ");r.refresh();return true})()",
                            )
                            if refreshed is True:
                                continue
                    except Exception:
                        pass
                    await context.close()
                    self.frames.pop(key, None)
                try:
                    await self._install_on_frame(client, target_id, frame["id"], key, page)
                except Exception:
                    # A frame torn down between listing and attaching (a navigation) is gone,
                    # not missed: nothing more can happen in it. A frame still there is a gap.
                    if any(f["id"] == frame["id"] for f in await discover_frames(client)):
                        raise
                    alive.discard(key)
        for key in self.frames.keys() - alive:
            context, _ = self.frames.pop(key)
            await context.close()

    async def _poll_targets(self):
        while self.active:
            try:
                # One listing per poll: each is a separate Workbench control request.
                targets = await self._target_infos()
                await self._attach_known_targets(targets)
                async with self.target_lock:
                    alive = {str(t.get("id") or "") for t in targets}
                    for target_id in self.tab_errors.keys() - alive:
                        self.tab_errors.pop(target_id)
                    for target_id in self._clients.keys() - alive:
                        client = self._clients.pop(target_id)
                        self._client_target_ids.pop(id(client), None)
                        await client.close()
                await self._sync_frames()
            except Exception as exc:
                self._warn(str(exc))
            try:
                await asyncio.wait_for(self.frame_changed.wait(), timeout=0.5)
            except TimeoutError:
                pass
            self.frame_changed.clear()

    async def _dispose(self):
        if self._poll_task:
            self._poll_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._poll_task
            self._poll_task = None
        await asyncio.gather(*self.navigations, return_exceptions=True)
        clients = list({id(c): c for c in [self.client, *self._clients.values()]}.values())
        for client in [*clients, *(c for c, _ in self.frames.values())]:
            if id(client) not in self.scripts and not any(
                client is c for c, _ in self.frames.values()
            ):
                continue
            try:
                if not isinstance(client, FrameContext):
                    client = await self._world(client)
                flushed = await evaluate(
                    client,
                    "(()=>{const r=globalThis.__deepseekRecorder;"
                    "if(!r || r.config.recordingId!=="
                    + json.dumps(self.manifest.recording_id)
                    + ")return false;r.dispose();return true})()",
                )
                if self.active and flushed is not True:
                    self._warn("Recording stopped before pending input could be confirmed")
                # A CDP response after synchronous binding emission is our transport drain barrier.
                await evaluate(client, "true")
            except Exception:
                if self.active:
                    # Keep the evidence and warning even when a page/connection disappears.
                    with suppress(Exception):
                        self._warn("Recording stopped before pending input could be confirmed")
        for client in clients:
            script = self.scripts.get(id(client))
            with suppress(Exception):
                if script:
                    await client.send(
                        "Page.removeScriptToEvaluateOnNewDocument", {"identifier": script}
                    )
            with suppress(Exception):
                await client.send("Runtime.removeBinding", {"name": self.binding_name})

    async def _pages_recording(self):
        clients = list({id(c): c for c in [self.client, *self._clients.values()]}.values())
        for client in clients:
            if id(client) not in self.scripts:
                continue
            # The same world name yields the current document's world, even after a navigation.
            ready = await evaluate(
                await self._world(client),
                "(()=>{const r=globalThis.__deepseekRecorder;return document.readyState!=='loading'"
                "&&!!r&&r.config.recordingId===" + json.dumps(self.manifest.recording_id) + "})()",
            )
            if ready is not True:
                return False
        return True

    async def _settle_before_stop(self):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.flush_wait
        while self.active:
            try:
                if await self._pages_recording():
                    # Drops frames that went away, so the flush only checks live ones.
                    await self._sync_frames()
                    return
            except Exception:
                pass  # A page or frame between documents; checked again until the deadline.
            if loop.time() >= deadline:
                return
            await asyncio.sleep(0.2)

    async def stop(self, **kwargs):
        await self._settle_before_stop()
        await self._dispose()
        return await super().stop(**kwargs)

    async def close(self):
        await self._dispose()
        for context, _ in self.frames.values():
            await context.close()
        self.frames.clear()
        await super().close()


async def create_recording(run, store, actor="user"):
    info = await evaluate(
        run.session._internal.client, "({url:location.href,title:document.title})"
    )
    target = (await run.session._internal.client.send("Target.getTargetInfo"))["targetInfo"][
        "targetId"
    ]
    profile = run.profiles.get_or_create("workbench")
    # A Workbench tab is reached only through the app's bridge, one page at a time.
    native = getattr(run, "native", False)
    if native:
        target = run.session.tab_id
    client = CDPClient(timeout=run.settings.cdp_timeout)
    manifest = RecordingManifest(
        recordingId="rec_" + uuid.uuid4().hex,
        createdAt=datetime.now(timezone.utc).isoformat(),
        profile="workbench",
        target=RecordingTarget(
            target_id=target, start_url=redact_url(info["url"]), title=info["title"]
        ),
        privacy=PrivacySettings(input_policy="mask-all"),
    )
    session = WorkbenchRecordSession(
        client,
        store,
        manifest,
        cdp_host=None if native else run.settings.cdp_host,
        cdp_port=None if native else profile.cdp_port,
        initial_target_id=target,
    )
    session.actor = actor
    if native:
        session.workbench = run.session.bridge, run.thread_id
    try:
        if native:
            from deepseek_tui.browser.workbench import tab_url

            await client.connect(tab_url(run.session.bridge, run.session.tab_id))
        else:
            await client.connect(
                f"ws://{run.settings.cdp_host}:{profile.cdp_port}/devtools/page/{target}"
            )
        directory = store.create(manifest)
        await session.start()
    except BaseException:
        manifest.status = "failed"
        manifest.ended_at = datetime.now(timezone.utc).isoformat()
        with suppress(Exception):
            store.write_manifest(manifest)
        await session.close()
        raise
    return session, {
        "ok": True,
        "recordingId": manifest.recording_id,
        "store": str(directory),
        "startUrl": manifest.target.start_url,
        "name": "",
    }
