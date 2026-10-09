"""Validated direct input from the shared browser viewport (never an agent tool)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrowserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: int = Field(ge=0)
    kind: Literal["mouse", "wheel", "key", "text", "resize", "copy", "cut", "pick", "devtools"]
    event: Literal["mousePressed", "mouseReleased", "mouseMoved", "keyDown", "keyUp"] | None = None
    x: float = Field(default=0, ge=0, lt=2400)
    y: float = Field(default=0, ge=0, lt=1600)
    button: Literal["none", "left", "middle", "right"] = "none"
    buttons: int = Field(default=0, ge=0, le=7)
    clicks: int = Field(default=1, ge=0, le=3)
    delta_x: float = Field(default=0, ge=-5000, le=5000)
    delta_y: float = Field(default=0, ge=-5000, le=5000)
    key: str = Field(default="", max_length=50)
    code: str = Field(default="", max_length=50)
    key_code: int = Field(default=0, ge=0, le=255)
    modifiers: int = Field(default=0, ge=0, le=15)
    text: str = Field(default="", max_length=8000)
    width: int = Field(default=1200, ge=320, le=2400)
    height: int = Field(default=760, ge=240, le=1600)

    @model_validator(mode="after")
    def validate_event(self) -> "BrowserInput":
        if self.kind == "mouse" and self.event not in {
            "mousePressed",
            "mouseReleased",
            "mouseMoved",
        }:
            raise ValueError("Invalid mouse event")
        if self.kind == "key" and (self.event not in {"keyDown", "keyUp"} or not self.key):
            raise ValueError("Invalid keyboard event")
        return self


async def dispatch_input(run, body: BrowserInput) -> dict:
    client = run.session._internal.client
    if body.kind == "devtools":
        target = await client.send("Target.getTargetInfo", {})
        target_id = target["targetInfo"]["targetId"]
        port = run.settings.cdp_port_start
        return {
            "url": f"http://127.0.0.1:{port}/devtools/inspector.html?ws=127.0.0.1:{port}/devtools/page/{target_id}"
        }
    if body.kind == "pick":
        from deepseek_tui.browser.picker import pick_element

        if body.x >= run.width or body.y >= run.height:
            raise ValueError("Pointer is outside the current viewport")
        return await pick_element(client, body.x, body.y)
    if body.kind in {"mouse", "wheel"}:
        if body.x >= run.width or body.y >= run.height:
            raise ValueError("Pointer is outside the current viewport")
        params = dict(
            type=body.event,
            x=body.x,
            y=body.y,
            modifiers=body.modifiers,
            button=body.button,
            buttons=body.buttons,
            clickCount=body.clicks,
        )
        if body.kind == "wheel":
            params.update(type="mouseWheel", deltaX=body.delta_x, deltaY=body.delta_y)
        await client.send("Input.dispatchMouseEvent", params)
    elif body.kind == "text":
        await client.send("Input.insertText", {"text": body.text})
    elif body.kind == "key":
        params = {
            "type": "rawKeyDown" if body.event == "keyDown" else "keyUp",
            "key": body.key,
            "code": body.code,
            "windowsVirtualKeyCode": body.key_code,
            "modifiers": body.modifiers,
        }
        if body.event == "keyDown" and body.key == "Enter":
            params.update(type="keyDown", text="\r", unmodifiedText="\r")
        if body.event == "keyDown" and body.modifiers & 6:
            command = {"a": "selectAll", "z": "redo" if body.modifiers & 8 else "undo"}.get(
                body.key.lower()
            )
            if command:
                params["commands"] = [command]
        await client.send(
            "Input.dispatchKeyEvent",
            params,
        )
    elif body.kind == "resize":
        if run.video and (body.width, body.height) != (run.width, run.height):
            raise ValueError("Finish video recording before resizing the webpage")
        await client.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": body.width,
                "height": body.height,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        run.width, run.height = body.width, body.height
    elif body.kind in {"copy", "cut"}:
        # Clipboard content travels only to the user's UI, never into the action log.
        result = await client.send(
            "Runtime.evaluate",
            {
                "expression": """(() => { const e = document.activeElement;
                if (e?.type === 'password') return '';
                if (typeof e?.selectionStart === 'number')
                    return e.value.slice(e.selectionStart, e.selectionEnd);
                return window.getSelection()?.toString() || ''; })()""",
                "returnByValue": True,
            },
        )
        text = result.get("result", {}).get("value", "")
        if body.kind == "cut" and text:
            if text != body.text:
                raise ValueError("Selection changed before cut; nothing was deleted")
            await client.send(
                "Input.dispatchKeyEvent",
                {"type": "rawKeyDown", "key": "Backspace", "windowsVirtualKeyCode": 8},
            )
            await client.send(
                "Input.dispatchKeyEvent",
                {"type": "keyUp", "key": "Backspace", "windowsVirtualKeyCode": 8},
            )
        return {"success": True, "text": text}
    return {"success": True}
