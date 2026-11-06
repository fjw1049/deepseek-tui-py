"""Recognize strictly app-local CUA requests. Everything else keeps desktop exclusivity."""

from __future__ import annotations

import functools
import re

from deepseek_tui.cua.apps import installed_apps


@functools.lru_cache(maxsize=64)
def display_name(identifier: str) -> str:
    entry = installed_apps().get(identifier)
    return entry[0] if entry else identifier


@functools.lru_cache(maxsize=64)
def native_app(name: str) -> str | None:
    key = name.casefold()
    matches = [
        app
        for app, (label, path, _) in installed_apps().items()
        if key in (app.casefold(), label.casefold(), path.stem.casefold(), str(path).casefold())
    ]
    return matches[0] if len(matches) == 1 else None


# Only literal arguments and direct calls on a binding the host saw created in this REPL.
# Computed targets, user functions, browser operations and system shortcuts are exclusive.
_BIND = re.compile(
    r"(?:(?:(?:let|const|var)\s+)?([A-Za-z_$][\w$]*)\s*=\s*)?"
    r"""await\s+cua\.getApp\(\s*(["'])([^"'\\\r\n]+)\2\s*\)\s*;?\s*"""
)
_CALL = re.compile(
    r"await\s+([A-Za-z_$][\w$]*)\.(click|setValue|typeText|pressKey|drag|scroll|selectText|"
    r"performSecondaryAction|paste|getAXState|getScreenshot|getAXStateAndScreenshot)\("
)
_STRING = r"""(?:"(?:[^"\\\r\n]|\\.)*"|'(?:[^'\\\r\n]|\\.)*')"""
_TOKEN = re.compile(
    rf"{_STRING}|-?\d+(?:\.\d+)?|true|false|null|[\s,\[\]{{}}:]|(?:disableDiffing|emit|clickCount)\s*:"
)
_END = re.compile(r"\)\s*;?\s*")
_LOCAL_KEY = re.compile(
    r"""\s*(["'])(?:[a-zA-Z0-9]|Return|Tab|Backspace|Escape|Left|Right|Up|Down|super\+a)"""
    r"\1\s*\)\s*;?\s*",
    re.I,
)
_DISCOVERY = re.compile(r"\s*await\s+cua\.(?:getState|listApps)\(\s*\)\s*;?\s*")


def discovery_only(code: str) -> bool:
    return bool(_DISCOVERY.fullmatch(code))


def js_scope(code: str, bindings: dict[str, str]) -> tuple[str | None, tuple[str, str] | None]:
    code = code.strip()
    pos = 0
    app = None
    binding = None
    if match := _BIND.match(code):
        app = native_app(match[3])
        if not app:
            return None, None
        binding = (match[1], app) if match[1] else None
        pos = match.end()
    while pos < len(code):
        call = _CALL.match(code, pos)
        if not call:
            return None, None
        target = binding[1] if binding and call[1] == binding[0] else bindings.get(call[1])
        end = call.end()
        if call[2] == "pressKey":
            args = _LOCAL_KEY.match(code, end)
        else:
            while token := _TOKEN.match(code, end):
                end = token.end()
            args = _END.match(code, end)
        if not args or not target or (app and app != target):
            return None, None
        app, pos = target, args.end()
    return app, binding


def canonical_binding(code: str, app: str) -> str:
    # Dispatch exactly the bundle we reserved, even when LCU's own display-name list
    # contains a helper with the same name. Leave the rest of the program untouched.
    import json

    match = _BIND.match(code.lstrip())
    assert match is not None
    offset = len(code) - len(code.lstrip())
    return code[: offset + match.start(2)] + json.dumps(app) + code[offset + match.end(3) + 1 :]


def binding_only(code: str) -> bool:
    return bool(_BIND.fullmatch(code.strip()))
