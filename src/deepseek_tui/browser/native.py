"""Native dialogs, explicit file choices and thread-owned download artifacts."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from deepseek_tui.browser.observation import SCOPE_CONTEXT, document_identity, root_context


class NativeBrowserEvents:
    def __init__(self, run, service):
        self.run, self.service = run, service
        self.clients = set()
        self.dialog = None
        self.chooser = None
        self.downloads = {
            d["id"]: d for d in service._saved_state(run.thread_id).get("downloads", [])
        }
        self.changed = asyncio.Event()
        self.requests = {}  # Document/XHR/Fetch requests in flight: id -> (client, seen at)
        self.loading = set()  # Clients whose main frame is loading a document

    async def install(self, client):
        if client in self.clients:
            return
        # A tab switch replaces the client; forget the closed ones.
        self.clients = {known for known in self.clients if getattr(known, "_ws", True) is not None}
        self.loading &= self.clients
        directory = self.service.artifact_root / self.run.thread_id / "downloads"
        directory.mkdir(parents=True, exist_ok=True)
        await client.send("Page.enable")
        await client.send("Page.setInterceptFileChooserDialog", {"enabled": True})
        from deepseek_tui.browser.frames import FrameContext, frame_entries

        if not isinstance(client, FrameContext):
            await client.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allowAndName",
                    "downloadPath": str(directory.resolve()),
                    "eventsEnabled": True,
                },
            )
            # Only request lifecycles are needed; keep no response bodies.
            await client.send(
                "Network.enable", {"maxTotalBufferSize": 0, "maxResourceBufferSize": 0}
            )
        identity = await document_identity(client)
        tree = (await client.send("Page.getFrameTree"))["frameTree"]
        state = {
            "identity": identity,
            "frames": {f["id"]: f.get("loaderId") for f in frame_entries(tree)},
        }

        def navigated(params):
            frame = params.get("frame", {})
            if frame.get("id"):
                state["frames"][frame["id"]] = frame.get("loaderId")
            if not frame.get("parentId"):
                state["identity"] = (frame.get("id"), frame.get("loaderId"))
            if self.chooser and self.chooser["client"] is client:
                self.chooser = None

        def dialog_opened(params):
            self.dialog = {
                "id": uuid.uuid4().hex,
                "type": params["type"],
                "message": params.get("message", "")[:1000],
                "generation": self.run.generation,
                "client": client,
            }
            self.changed.set()

        def chooser_opened(params):
            self.chooser = {
                "id": uuid.uuid4().hex,
                "frame_id": params["frameId"],
                "backend_node_id": params.get("backendNodeId"),
                "mode": params["mode"],
                "generation": self.run.generation,
                "identity": state["identity"],
                "client": client,
                "frame_document_id": state["frames"].get(params["frameId"]),
            }
            snapshot = asyncio.create_task(self._chooser_scope(self.chooser))
            snapshot.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            self.chooser["snapshot"] = snapshot

        def download_started(params):
            if params["guid"] in self.downloads:
                return
            if len(self.downloads) >= 40:
                expired = next(
                    (k for k, d in self.downloads.items() if d["state"] != "inProgress"), None
                )
                if expired:
                    self.downloads.pop(expired)
            self.downloads[params["guid"]] = {
                "id": params["guid"],
                "state": "inProgress",
                "filename": Path(params.get("suggestedFilename", "download")).name[:300],
                "frame_id": params.get("frameId"),
                "received_bytes": 0,
            }

        def download_progress(params):
            item = self.downloads.get(params["guid"])
            if item is None:
                return
            item.update(
                state=params["state"],
                received_bytes=params.get("receivedBytes", 0),
                total_bytes=params.get("totalBytes", 0),
            )
            path = (Path(params["filePath"]) if self.run.native and params.get("filePath")
                    else directory / params["guid"])
            if params["state"] == "completed" and path.is_file() and not path.is_symlink():
                item["path"] = str(path)
                self.service._persist(self.run)

        def request_sent(params):
            if params.get("type") in {"Document", "XHR", "Fetch"}:
                self.requests[params["requestId"]] = (
                    client, asyncio.get_running_loop().time()
                )
                while len(self.requests) > 200:
                    self.requests.pop(next(iter(self.requests)))

        def request_done(params):
            self.requests.pop(params.get("requestId"), None)

        def popup_blocked(params):
            blocked = self.run.popups_blocked
            blocked.append(str(params.get("url") or "about:blank")[:300])
            del blocked[:-20]

        def loading(started):
            def update(params):
                if params.get("frameId") != state["identity"][0]:
                    return
                if started:
                    self.loading.add(client)
                else:
                    self.loading.discard(client)
            return update

        for event, callback in {
            "Network.requestWillBeSent": request_sent,
            "Network.loadingFinished": request_done,
            "Network.loadingFailed": request_done,
            "Page.frameNavigated": navigated,
            "Page.frameStartedLoading": loading(True),
            "Page.frameStoppedLoading": loading(False),
            "Page.javascriptDialogOpening": dialog_opened,
            "Page.javascriptDialogClosed": lambda _: setattr(self, "dialog", None),
            "Page.fileChooserOpened": chooser_opened,
            "Browser.downloadWillBegin": download_started,
            "Browser.downloadProgress": download_progress,
            "Workbench.popupBlocked": popup_blocked,
        }.items():
            client.on(event, callback)
        self.clients.add(client)
        if self.run.native and not isinstance(client, FrameContext):
            result = await client.send("Workbench.getDownloads")
            for item in result.get("downloads", []):
                download_started(item["begin"])
                if item.get("progress"):
                    download_progress(item["progress"])

    def pending_requests(self, client, since):
        """Page requests started after ``since`` (loop time) that have not finished."""
        return any(c is client and seen >= since for c, seen in self.requests.values())

    def state(self):
        return {
            "dialog": {k: v for k, v in self.dialog.items() if k != "client"}
            if self.dialog
            else None,
            "file_chooser": {
                k: v
                for k, v in self.chooser.items()
                if k not in {"client", "backend_node_id", "identity", "snapshot"}
            }
            if self.chooser
            else None,
            "downloads": list(self.downloads.values())[-40:],
            "loading": getattr(getattr(self.run.session, "_internal", None), "client", None)
            in self.loading,
        }

    async def handle_dialog(self, action):
        dialog = self.dialog
        if (
            not dialog
            or dialog["id"] != action.dialog_id
            or dialog["generation"] != self.run.generation
        ):
            raise ValueError("Dialog changed; inspect its current ID before answering")
        action._dispatched = True
        await dialog["client"].send(
            "Page.handleJavaScriptDialog", {"accept": action.accept, "promptText": action.text}
        )
        if self.run.recorder:
            event = {
                "kind": "native_dialog",
                "accept": action.accept,
                "targetId": next(
                    (tab["tab_id"] for tab in self.run.tabs if tab.get("active")), ""
                ),
            }
            # Masking turns any "value" key into a placeholder, so only a prompt
            # (which has an answer to supply) may carry one.
            if dialog["type"] == "prompt":
                event["value"] = "{{dialog_answer}}"
            self.run.recorder._append(event)
        self.dialog = None

    async def upload(self, action, *, user_selected=False):
        def resolve_files():
            files, root = [], self.run.upload_root
            for filename in action.files:
                path = Path(filename).expanduser().resolve(strict=True)
                if not path.is_file():
                    raise ValueError("Upload path must be a regular file")
                if not user_selected and (root is None or not path.is_relative_to(root.resolve())):
                    raise ValueError("Agent uploads must stay inside the task workspace")
                files.append(str(path))
            return files

        files = await asyncio.to_thread(resolve_files)
        if action.chooser_id:
            chooser = self.chooser
            if (
                not chooser
                or chooser["id"] != action.chooser_id
                or chooser["generation"] != self.run.generation
            ):
                raise ValueError(
                    "File chooser changed; inspect the current chooser before uploading"
                )
            if not chooser["backend_node_id"]:
                raise ValueError("File chooser document changed")
            if chooser["mode"] != "selectMultiple" and len(files) > 1:
                raise ValueError("File chooser accepts one file")
            captured = await chooser["snapshot"]
            if captured != await self._chooser_scope(chooser):
                raise ValueError("File chooser business scope changed")
            client, temporary = await self._chooser_context(chooser)
            try:
                action._dispatched = True
                await client.send(
                    "DOM.setFileInputFiles",
                    {"backendNodeId": chooser["backend_node_id"], "files": files},
                )
            finally:
                if temporary:
                    await client.close()
            self.chooser = None
            return
        await self.service._dispatch_guard(self.run, action)
        client = (
            self.run.observation_context if action.frame_id else self.run.observation_root_context
        )
        response = await client.send(
            "Runtime.evaluate", {"expression": "window.__deepseekTarget", "returnByValue": False}
        )
        object_id = response.get("result", {}).get("objectId")
        if not object_id:
            raise ValueError("Observed file input is unavailable")
        try:
            ready = await client.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "returnByValue": True,
                    "functionDeclaration": "function(n){return this.isConnected &&"
                    "this.tagName==='INPUT' && this.type==='file' && !this.disabled && (this.multiple || n<=1)}",
                    "arguments": [{"value": len(files)}],
                },
            )
            if ready.get("result", {}).get("value") is not True:
                raise ValueError(
                    "Upload requires a current, enabled file input with compatible multiplicity"
                )
            action._dispatched = True
            await client.send("DOM.setFileInputFiles", {"objectId": object_id, "files": files})
        finally:
            await client.send("Runtime.releaseObject", {"objectId": object_id})

    async def _chooser_context(self, chooser):
        from deepseek_tui.browser.frames import FrameContext

        root = await root_context(self.run)
        if root.identity[0] == chooser["frame_id"]:
            client, temporary = root, False
        else:
            client, temporary = (
                await FrameContext.create(self.run.session._internal.client, chooser["frame_id"]),
                True,
            )
        if await document_identity(client) != (chooser["frame_id"], chooser["frame_document_id"]):
            if temporary:
                await client.close()
            raise ValueError("File chooser frame document changed")
        return client, temporary

    async def _chooser_scope(self, chooser):
        client, temporary = await self._chooser_context(chooser)
        object_id = None
        try:
            obj = await client.send(
                "DOM.resolveNode",
                {
                    "backendNodeId": chooser["backend_node_id"],
                    "executionContextId": client.context_id,
                },
            )
            object_id = obj["object"]["objectId"]
            result = await client.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "returnByValue": True,
                    "functionDeclaration": "function(){const s=("
                    + SCOPE_CONTEXT
                    + ")(this);return {"
                    "connected:this.isConnected,scope:s?{id:s.id,text:s.text,keys:s.keys}:null}}",
                },
            )
            value = result.get("result", {}).get("value")
            if not value or value["connected"] is not True:
                raise ValueError("File chooser input detached")
            from deepseek_tui.browser.frames import FrameContext

            ancestor = client
            value["ancestors"] = []
            while isinstance(ancestor, FrameContext):
                value["ancestors"].append((ancestor.frame_id, ancestor.parent_identity, ancestor.owner_binding))
                ancestor = ancestor.parent
            return value
        finally:
            if object_id:
                await client.send("Runtime.releaseObject", {"objectId": object_id})
            if temporary:
                await client.close()
