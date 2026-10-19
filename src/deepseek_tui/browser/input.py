"""Validated direct input from the shared browser viewport (never an agent tool)."""

import asyncio
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrowserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: int = Field(ge=0)
    scene_id: str | None = Field(default=None, min_length=1, max_length=200)
    kind: Literal["mouse", "wheel", "key", "text", "resize", "copy", "cut", "pick", "devtools",
                  "release", "stop"]
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


def key_event(chord: str, generation: int = 0) -> BrowserInput:
    # A trailing '+' is the key itself, as in '+' or 'Ctrl++'.
    if chord.endswith("+"):
        parts = (chord[:-2].split("+") if len(chord) > 1 else []) + ["+"]
    else:
        parts = chord.split("+")
    modifiers = 0
    flags = {"ctrl": 2, "control": 2, "alt": 1, "option": 1,
             "shift": 8, "meta": 4, "cmd": 4, "command": 4}
    for part in parts[:-1]:
        if part.lower() not in flags:
            raise ValueError(f"Unsupported key modifier: {part}")
        modifiers |= flags[part.lower()]
    key = parts[-1]
    named = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "Delete": 46,
             "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
             "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34, "Space": 32}
    punctuation = {
        "`": ("Backquote", 192, "~"), "-": ("Minus", 189, "_"),
        "=": ("Equal", 187, "+"), "[": ("BracketLeft", 219, "{"),
        "]": ("BracketRight", 221, "}"), "\\": ("Backslash", 220, "|"),
        ";": ("Semicolon", 186, ":"), "'": ("Quote", 222, '"'),
        ",": ("Comma", 188, "<"), ".": ("Period", 190, ">"),
        "/": ("Slash", 191, "?"),
    }
    digits = dict(zip("1234567890", "!@#$%^&*()", strict=True))
    if len(key) == 1 and key.isascii() and key.isalnum():
        code = ("Key" + key.upper()) if key.isalpha() else "Digit" + key
        key_code = ord(key.upper())
        if modifiers & 8:
            key = key.upper() if key.isalpha() else digits[key]
        elif key.isupper() and not modifiers & 7:
            modifiers |= 8
    elif key in punctuation or key in digits.values() or any(
        key == entry[2] for entry in punctuation.values()
    ):
        if key in digits.values():
            unmodified = next(k for k, v in digits.items() if v == key)
            code, key_code = "Digit" + unmodified, ord(unmodified)
            modifiers |= 8
        else:
            unmodified = next(k for k, v in punctuation.items() if key in {k, v[2]})
            code, key_code, shifted = punctuation[unmodified]
            if key == shifted:
                modifiers |= 8
            if modifiers & 8:
                key = shifted
    elif key in named:
        code, key_code = key, named[key]
        if key == "Space":
            key = " "
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        code, key_code = key, 111 + int(key[1:])
    else:
        raise ValueError(f"Unsupported keyboard key: {key}")
    return BrowserInput(generation=generation, kind="key", event="keyDown",
                        key=key, code=code, key_code=key_code, modifiers=modifiers,
                        text=key if len(key) == 1 and not modifiers & 7 else "")


async def press_key(run, chord: str, *, client=None) -> None:
    event = key_event(chord, run.generation)
    try:
        await dispatch_input(run, event, client=client)
    finally:
        await asyncio.shield(asyncio.wait_for(dispatch_input(run, event.model_copy(
            update={"event": "keyUp", "text": ""}), client=client), 1))


async def dispatch_input(run, body: BrowserInput, *, client=None) -> dict:
    client = client or run.session._internal.client
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
        if body.event == "keyDown" and body.text:
            params.update(type="keyDown", text=body.text)
        elif body.event == "keyDown" and body.key == "Enter":
            params.update(type="keyDown", text="\r", unmodifiedText="\r")
        if body.event == "keyDown" and body.modifiers & 7 in {2, 4}:
            command = None
            if body.key.lower() == "a" and not body.modifiers & 8:
                command = "selectAll"
            elif body.key.lower() == "z":
                command = "redo" if body.modifiers & 8 else "undo"
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
