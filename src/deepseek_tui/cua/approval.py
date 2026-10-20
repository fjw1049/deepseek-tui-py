"""Present upstream approvals without expanding their scopes."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

HOST_APP_ID = "com.xingyuzhong.deepseekgui"
# An unpackaged Workbench runs as Electron itself.
HOST_APP_IDS = {HOST_APP_ID.lower(), "com.github.electron"}


def approval_question(params: dict[str, Any]) -> dict[str, Any] | None:
    meta = params.get("_meta") or params.get("meta") or {}
    schema = params.get("requestedSchema") or {}
    if (
        params.get("mode", "form") != "form"
        or schema.get("type") != "object"
        or schema.get("properties") != {}
        or schema.get("required")
        or not isinstance(params.get("message"), str)
    ):
        return None
    app = (meta.get("tool_params") or {}).get("app")
    native = meta.get("connector_id") == "computer-use" and isinstance(app, str)
    if native and app.lower() in HOST_APP_IDS:
        return None
    # Browser requests must carry an exact origin; unfamiliar shapes fail closed.
    origin = meta.get("origin")
    browser = False
    if isinstance(origin, str):
        url = urlsplit(origin)
        browser = (
            meta.get("tool_name") == "access_browser_origin"
            and url.scheme in {"http", "https"}
            and bool(url.netloc)
            and origin == f"{url.scheme}://{url.netloc}"
        )
    if not native and not browser:
        return None
    options = [
        {"label": "拒绝 / Deny", "value": "decline", "description": "不允许本次访问"},
        {"label": "允许一次 / Allow once", "value": "once", "description": "仅允许本次请求"},
    ]
    if native:
        scopes = meta.get("persist", [])
        for scope, label in [
            ("session", "本次会话 / This session"),
            ("always", "始终允许 / Always allow"),
        ]:
            if scope in scopes:
                options.append(
                    {"label": label, "value": scope, "description": "使用运行时提供的授权范围"}
                )
    return {
        "id": "cua_permission",
        "header": "电脑控制授权",
        "question": params["message"],
        "options": options,
    }


def approval_response(params: dict[str, Any], response: dict[str, Any] | None) -> dict[str, Any]:
    question = approval_question(params)
    if not question or not response:
        return {"action": "cancel"}
    choices = {option["value"]: option["value"] for option in question["options"]}
    choices.update({option["label"]: option["value"] for option in question["options"]})
    for answer in response.get("answers", []):
        if (
            not isinstance(answer, dict)
            or (answer.get("question_id") or answer.get("id")) != question["id"]
        ):
            continue
        value = next(
            (
                choices.get(answer.get(key))
                for key in ("value", "label", "selected_option")
                if isinstance(answer.get(key), str) and answer.get(key) in choices
            ),
            None,
        )
        if value == "decline":
            return {"action": "decline"}
        if value in {"once", "session", "always"}:
            result: dict[str, Any] = {"action": "accept", "content": {}}
            if value != "once":
                result["_meta"] = {"persist": value}
            return result
    return {"action": "cancel"}
