"""Scoped CDP contexts with validated ancestor chains, including remote renderers."""

from __future__ import annotations

import asyncio
import json
from typing import Any


def frame_entries(tree: dict[str, Any], parent: str | None = None) -> list[dict[str, Any]]:
    frame = {**tree.get("frame", {}), "parent_id": parent}
    return [frame] + [
        item
        for child in tree.get("childFrames", [])
        for item in frame_entries(child, frame.get("id"))
    ]


async def discover_frames(client) -> list[dict[str, Any]]:
    frames = frame_entries((await client.send("Page.getFrameTree")).get("frameTree", {}))
    if not hasattr(client, "on"):
        return frames
    targets = (await client.send("Target.getTargets")).get("targetInfos", [])
    while True:
        known = {f.get("id") for f in frames}
        new = [
            {"id": t["targetId"], "url": t["url"], "parent_id": t["parentFrameId"]}
            for t in targets
            if t["type"] == "iframe"
            and t.get("parentFrameId") in known
            and t["targetId"] not in known
        ]
        if not new:
            return frames
        frames.extend(new)


async def resolve_frame(client, selector: str | dict) -> str:
    """Resolve one current child owner, including owners inside open shadow roots."""
    from deepseek_tui.browser.observation import document_identity

    identity = await document_identity(client)
    locator = {"selector": selector} if isinstance(selector, str) else selector
    if not isinstance(client, FrameContext):
        world = await client.send(
            "Page.createIsolatedWorld",
            {"frameId": identity[0], "worldName": "deepseek-browser-owners"},
        )
        from deepseek_tui.browser.observation import DocumentContext

        client = DocumentContext(client, identity, world["executionContextId"])
    await client.send("DOM.getDocument", {"depth": 0})
    result = await client.send(
        "Runtime.evaluate",
        {
            "expression": "(()=>{let root=document;for(const s of "
            + json.dumps(locator.get("shadowPath", []))
            + "){const h=root.querySelectorAll(s);if(h.length!==1 || !h[0].shadowRoot)return null;root=h[0].shadowRoot;}"
            "const nodes=root.querySelectorAll("
            + json.dumps(locator["selector"])
            + ");return nodes.length===1 && ['IFRAME','FRAME'].includes(nodes[0].tagName)"
            + "?nodes[0]:null})()",
            "returnByValue": False,
        },
    )
    object_id = result.get("result", {}).get("objectId")
    if not object_id:
        raise ValueError("Replay frame path must match one current frame owner")
    try:
        node = await client.send("DOM.describeNode", {"objectId": object_id})
        frame_id = node.get("node", {}).get("frameId")
        frames = await discover_frames(client)
        if await document_identity(client) != identity or not any(
            f.get("id") == frame_id and f.get("parent_id") == identity[0] for f in frames
        ):
            raise ValueError("Replay frame must be a current direct child of this document")
        return frame_id
    finally:
        await client.send("Runtime.releaseObject", {"objectId": object_id})


class FrameContext:
    def __init__(self, parent, frame_id: str):
        self.parent, self.frame_id = parent, frame_id
        self.context_id = None
        self.session_id = None
        self.pending = {}
        self.sequence = 0
        self.offset = (0, 0)
        self.listeners = {}
        self.owns_parent = False
        self.parent_identity = None
        self.owner_binding = None
        self.parent_context_id = None

    @classmethod
    async def create(cls, parent, frame_id: str):
        frames = await discover_frames(parent)
        frame = next((f for f in frames if f["id"] == frame_id), None)
        if not frame or not frame.get("parent_id"):
            raise ValueError("Frame must be a current descendant of this page")
        owns_parent = frame["parent_id"] != frames[0]["id"]
        if owns_parent:
            depth, ancestor = 0, frame
            while ancestor.get("parent_id"):
                depth += 1
                ancestor = next((f for f in frames if f["id"] == ancestor["parent_id"]), {})
            if depth > 8:
                raise ValueError("Frame depth exceeds the supported maximum of 8")
            parent = await cls.create(parent, frame["parent_id"])
        self = cls(parent, frame_id)
        self.owns_parent = owns_parent
        try:
            world = await self._send(
                "Page.createIsolatedWorld",
                {"frameId": frame_id, "worldName": "deepseek-browser-observation"},
            )
        except Exception as exc:
            # Remote renderer targets require their own CDP channel.
            targets = await parent.send("Target.getTargets")
            if not any(
                t["targetId"] == frame_id and t["type"] == "iframe"
                for t in targets.get("targetInfos", [])
            ):
                await self.close()
                raise ValueError(
                    "Frame observation is unavailable; use screenshot or assistance"
                ) from exc
            attached = await parent.send(
                "Target.attachToTarget", {"targetId": frame_id, "flatten": False}
            )
            self.session_id = attached["sessionId"]
            parent.on("Target.receivedMessageFromTarget", self._receive)
            try:
                world = await self._send(
                    "Page.createIsolatedWorld",
                    {"frameId": frame_id, "worldName": "deepseek-browser-observation"},
                )
            except BaseException:
                await self.close()
                raise
        self.context_id = world["executionContextId"]
        from deepseek_tui.browser.observation import document_identity

        try:
            self.parent_identity = await document_identity(parent)
            if isinstance(parent, FrameContext):
                self.parent_context_id = parent.context_id
            else:
                self.parent_context_id = (
                    await parent.send(
                        "Page.createIsolatedWorld",
                        {"frameId": self.parent_identity[0], "worldName": "deepseek-browser-owners"},
                    )
                )["executionContextId"]
            self.owner_binding = await self._owner_facts()
        except BaseException:
            await self.close()
            raise
        return self

    def _receive(self, params):
        if params.get("sessionId") != self.session_id:
            return
        message = json.loads(params["message"])
        future = self.pending.get(message.get("id"))
        if future and not future.done():
            future.set_result(message)
        elif message.get("method"):
            params = {**message.get("params", {}), "__client": self}
            for callback in self.listeners.get(message["method"], []):
                result = callback(params)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)

    def on(self, event, callback):
        if not self.session_id:
            return self.parent.on(event, callback)
        self.listeners.setdefault(event, []).append(callback)

    def off(self, event, callback):
        if not self.session_id:
            return self.parent.off(event, callback)
        if callback in self.listeners.get(event, []):
            self.listeners[event].remove(callback)

    async def _owner_object(self):
        await self.parent.send("DOM.getDocument", {"depth": 0})
        owner = await self.parent.send("DOM.getFrameOwner", {"frameId": self.frame_id})
        obj = await self.parent.send(
            "DOM.resolveNode",
            {"backendNodeId": owner["backendNodeId"], "executionContextId": self.parent_context_id},
        )
        return owner["backendNodeId"], obj["object"]["objectId"]

    async def _owner_facts(self):
        from deepseek_tui.browser.observation import SCOPE_CONTEXT

        node_id, object_id = await self._owner_object()
        try:
            response = await self.parent.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "returnByValue": True,
                    "functionDeclaration": "function(){const s=(" + SCOPE_CONTEXT + ")(this);"
                    "return {scope:s?{id:s.id,keys:s.keys,text:s.text}:null,srcdoc:this.getAttribute('srcdoc')}}",
                },
            )
            return node_id, response.get("result", {}).get("value")
        finally:
            await self.parent.send("Runtime.releaseObject", {"objectId": object_id})

    async def validate_ancestors(self):
        from deepseek_tui.browser.observation import document_identity

        if (
            await document_identity(self.parent) != self.parent_identity
            or await self._owner_facts() != self.owner_binding
        ):
            raise ValueError("Frame ancestor document or business scope changed")
        if isinstance(self.parent, FrameContext):
            await self.parent.validate_ancestors()

    async def owner_selector(self):
        _, object_id = await self._owner_object()
        try:
            result = await self.parent.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "returnByValue": True,
                    "functionDeclaration": """function(){
                  const path=e=>{const parts=[],root=e.getRootNode();
                  for(;e;e=e.parentElement){
                    const tag=e.tagName.toLowerCase();
                    if(e.id && root.querySelectorAll('#'+CSS.escape(e.id)).length===1){
                      parts.unshift(tag+'#'+CSS.escape(e.id));break;
                    }
                    let n=1;
                    for(let s=e.previousElementSibling;s;s=s.previousElementSibling)
                      if(s.tagName===e.tagName)n++;
                    parts.unshift(tag+':nth-of-type('+n+')');
                  }
                  return parts.join(' > ')};
                  const shadowPath=[];let root=this.getRootNode();
                  while(root!==document){if(!root.host || root.mode!=='open')return null;
                    shadowPath.unshift(path(root.host));root=root.host.getRootNode();}
                  return shadowPath.length?{selector:path(this),shadowPath}:path(this);
                }""",
                },
            )
            selector = result.get("result", {}).get("value")
            if not selector:
                raise ValueError("Recording frame owner must be in the parent document")
            return selector
        finally:
            await self.parent.send("Runtime.releaseObject", {"objectId": object_id})

    async def owner_path(self):
        ancestors = await self.parent.owner_path() if isinstance(self.parent, FrameContext) else []
        return [*ancestors, await self.owner_selector()]

    async def _send(self, method, params=None):
        if not self.session_id:
            sender = (
                self.parent._send if isinstance(self.parent, FrameContext) else self.parent.send
            )
            return await sender(method, params)
        self.sequence += 1
        sequence = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[sequence] = future
        try:
            await self.parent.send(
                "Target.sendMessageToTarget",
                {
                    "sessionId": self.session_id,
                    "message": json.dumps(
                        {"id": sequence, "method": method, "params": params or {}}
                    ),
                },
            )
            response = await asyncio.wait_for(future, timeout=5)
            if "error" in response:
                raise RuntimeError("Frame CDP command failed: " + response["error"]["message"])
            return response.get("result", {})
        finally:
            self.pending.pop(sequence, None)

    async def send(self, method, params=None):
        if method in {"Input.dispatchKeyEvent", "Input.insertText"}:
            return await self.parent.send(method, params)
        if method == "Page.getFrameTree":
            frames = await discover_frames(self.parent)
            frame = next((f for f in frames if f["id"] == self.frame_id), None)
            if frame is None:
                raise ValueError("Frame detached; observe the parent page again")
            if self.session_id:
                return await self._send(method, params)
            tree = (await self.parent.send(method, params)).get("frameTree", {})

            def subtree(t):
                if t.get("frame", {}).get("id") == self.frame_id:
                    return t
                return next(
                    (found for child in t.get("childFrames", []) if (found := subtree(child))), None
                )

            return {"frameTree": subtree(tree) or {"frame": frame}}
        if method == "Runtime.evaluate":
            params = {**(params or {}), "contextId": self.context_id}
        if method == "Input.dispatchMouseEvent" and self.session_id:
            params = {
                **params,
                "x": params["x"] - self.offset[0],
                "y": params["y"] - self.offset[1],
            }
        elif method == "Input.dispatchMouseEvent" and isinstance(self.parent, FrameContext):
            return await self.parent.send(method, params)
        return await self._send(method, params)

    async def coordinates(self, x: float, y: float) -> dict[str, Any]:
        await self.validate_ancestors()
        _, object_id = await self._owner_object()
        try:
            response = await self.parent.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "returnByValue": True,
                    "arguments": [{"value": x}, {"value": y}],
                    "functionDeclaration": """function(x,y){
                  this.scrollIntoView({block:'center',inline:'center'});
                  for(let p=this;p;p=p.parentElement || p.getRootNode()?.host){
                    const s=getComputedStyle(p);
                    if(s.transform!=='none' || s.perspective!=='none' || Number(s.zoom || 1)!==1 ||
                       ['translate','rotate','scale'].some(k=>s[k] && s[k]!=='none'))
                      return {error:'frame_coordinates_unavailable'};
                  }
                  const r=this.getBoundingClientRect();
                  if(x<0 || y<0 || x>=this.clientWidth || y>=this.clientHeight)
                    return {error:'frame_coordinates_unavailable'};
                  const px=r.x+this.clientLeft+x, py=r.y+this.clientTop+y;
                  let hit=document.elementFromPoint(px,py);
                  while(hit?.shadowRoot) {const inner=hit.shadowRoot.elementFromPoint(px,py);
                    if(!inner || inner===hit)break;hit=inner;}
                  if(hit!==this) return {error:'target_obscured'};
                  return {x:px,y:py};
                }""",
                },
            )
            coordinates = response.get("result", {}).get("value") or {
                "error": "frame_coordinates_unavailable"
            }
            if not coordinates.get("error"):
                if isinstance(self.parent, FrameContext):
                    coordinates = await self.parent.coordinates(coordinates["x"], coordinates["y"])
                self.offset = (coordinates["x"] - x, coordinates["y"] - y)
            return coordinates
        finally:
            await self.parent.send("Runtime.releaseObject", {"objectId": object_id})

    async def focus_parent(self):
        await self.validate_ancestors()
        if isinstance(self.parent, FrameContext):
            await self.parent.focus_parent()
        _, object_id = await self._owner_object()
        try:
            await self.parent.send(
                "Runtime.callFunctionOn",
                {"objectId": object_id, "functionDeclaration": "function(){this.focus()}"},
            )
        finally:
            await self.parent.send("Runtime.releaseObject", {"objectId": object_id})

    async def parent_focused(self):
        _, object_id = await self._owner_object()
        try:
            result = await self.parent.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "returnByValue": True,
                    "functionDeclaration": "function(){let e=document.activeElement;"
                    "while(e?.shadowRoot?.activeElement)e=e.shadowRoot.activeElement;return e===this}",
                },
            )
            focused = result.get("result", {}).get("value") is True
            return focused and (
                await self.parent.parent_focused()
                if isinstance(self.parent, FrameContext)
                else True
            )
        finally:
            await self.parent.send("Runtime.releaseObject", {"objectId": object_id})

    async def release_observation(self):
        from deepseek_tui.browser.observation import evaluate

        try:
            await asyncio.wait_for(
                evaluate(
                    self,
                    "(()=>{window.__deepseekPageRevision?.observer?.disconnect();"
                    "window.__deepseekObservation=null;window.__deepseekTarget=null;return true})()",
                ),
                1,
            )
        except Exception:
            pass  # Detached documents have already released their DOM handles.

    async def close(self):
        if self.session_id:
            self.parent.off("Target.receivedMessageFromTarget", self._receive)
            try:
                await self.parent.send("Target.detachFromTarget", {"sessionId": self.session_id})
            except Exception:
                pass
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        self.pending.clear()
        self.listeners.clear()
        if self.owns_parent:
            await self.parent.close()


async def resolve_frame_path(client, path):
    """Resolve each owner in its own document; release temporary routing channels."""
    current, contexts = client, []
    try:
        frame_id = ""
        for locator in path:
            frame_id = await resolve_frame(current, locator)
            current = await FrameContext.create(current, frame_id)
            contexts.append(current)
        return frame_id
    finally:
        for context in reversed(contexts):
            await context.close()
