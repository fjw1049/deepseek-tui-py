"""Site-scoped approval for browser actions: which site an action reaches, and what the user is asked."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from deepseek_tui.browser.sites import is_sensitive, site_of

NAVIGATION_ACTIONS = {"open", "new_tab"}
INTERACTION_ACTIONS = {"click", "fill", "type", "select", "set_checked", "press", "upload"}
_ACTION_WORDS = {
    "zh": {
        "open": "打开", "new_tab": "在新标签页打开", "click": "点击", "fill": "填写", "type": "输入",
        "select": "选择", "set_checked": "勾选", "press": "按键", "upload": "上传文件到",
        "hover": "悬停", "scroll": "滚动", "handle_dialog": "回应对话框", "recover": "重启浏览器",
        "close_session": "结束浏览器", "close_tab": "关闭标签页", "record_start": "开始录制",
        "record_stop": "结束录制", "video_start": "开始录像", "video_stop": "结束录像",
    },
    "en": {
        "open": "Open", "new_tab": "Open in a new tab", "click": "Click", "fill": "Fill in",
        "type": "Type into", "select": "Select in", "set_checked": "Check", "press": "Press",
        "upload": "Upload files to", "hover": "Hover over", "scroll": "Scroll",
        "handle_dialog": "Answer the dialog", "recover": "Restart the browser",
        "close_session": "Close the browser", "close_tab": "Close the tab",
        "record_start": "Start recording", "record_stop": "Stop recording",
        "video_start": "Start video", "video_stop": "Stop video",
    },
}

_ROLE_WORDS = {
    "zh": {
        "button": "按钮", "link": "链接", "textbox": "输入框", "searchbox": "搜索框",
        "checkbox": "复选框", "radio": "单选项", "combobox": "下拉框", "listbox": "列表",
        "option": "选项", "menuitem": "菜单项", "tab": "标签", "switch": "开关", "slider": "滑块",
    },
    "en": {},  # The ARIA role name already reads as English.
}

_TEXT = {
    "zh": {
        "here": "当前页面", "on": "在 {host} {action}", "press": "在 {host} 按下 {key}",
        "target": "{role}「{name}」", "value": "：「{text}」",
        "hidden": "（{count} 个字符，已隐藏）",
        "site": "网站: {host}", "file": "文件: {path}", "more_files": "另有 {count} 个文件",
        "private": "内网地址: 网站可以记住，页面操作仍会逐次确认",
        "session": "本会话允许: 本对话内 Agent 可直接打开 {host} 并在其中点击、填写",
        "sensitive": "敏感网站（邮箱、支付、银行、云控制台等）: 每次操作都需要确认",
        "upload": "上传会把本机文件发送给网站: 每次上传都需要确认，不会被记住",
    },
    "en": {
        "here": "this page", "on": "{action} on {host}", "press": "Press {key} on {host}",
        "target": "{role} \u201c{name}\u201d", "value": ": \u201c{text}\u201d",
        "hidden": " ({count} characters, hidden)",
        "site": "Site: {host}", "file": "File: {path}", "more_files": "{count} more files",
        "private": "Local network address: the site can be remembered, page actions still ask "
                   "each time",
        "session": "Allow for this session: the agent may open {host} and click or fill in there "
                   "for the rest of this conversation",
        "sensitive": "Sensitive site (mail, payments, banking, cloud consoles): every action asks",
        "upload": "Uploading sends files from this computer to the site: every upload asks and "
                  "is never remembered",
    },
}
_TEXT_ACTIONS = {"fill", "type", "select"}
_SHOWN_TEXT = 80
_SHOWN_FILES = 5


def origin_of(url: str) -> str | None:
    parts = urlsplit(url or "")
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}"


def _address(host: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def is_loopback(host: str) -> bool:
    address = _address(host)
    return host == "localhost" or host.endswith(".localhost") or bool(address and address.is_loopback)


def is_private(host: str) -> bool:
    address = _address(host)
    return bool(address and (address.is_private or address.is_link_local)) and not is_loopback(host)


def navigation_needs_approval(input_data: dict[str, Any]) -> bool:
    """Opening a site other than this computer's own servers asks the user first."""
    if input_data.get("action") not in NAVIGATION_ACTIONS or not input_data.get("url"):
        return False
    host = urlsplit(str(input_data["url"])).hostname or ""
    return not is_loopback(host)


def action_site(run: Any, arguments: dict[str, Any]) -> str | None:
    """The origin the action will act on: its URL for navigation, else the observed page."""
    if arguments.get("action") in NAVIGATION_ACTIONS and arguments.get("url"):
        return origin_of(str(arguments["url"]))
    if run is None:
        return None
    observation = run.latest_observation or {}
    if arguments.get("observation_id") and observation.get("observation_id") == arguments["observation_id"]:
        return origin_of(observation.get("url", ""))
    return origin_of(run.url)


def site_trust(origin: str | None) -> str:
    """site: one approval covers the site for the session; action: every action asks."""
    if origin is None:
        return "action"
    host = urlsplit(origin).hostname or ""
    if is_sensitive(site_of(host)):
        return "action"
    return "site"


def _secret(element: dict[str, Any] | None) -> bool:
    """Unknown targets and password-like fields keep their text hidden on the card."""
    if element is None:
        return True
    name = str(element.get("name") or "").lower()
    return element.get("type") == "password" or any(
        word in name for word in ("password", "passcode", "密码", "验证码", "one-time code"))


def preview(run: Any, arguments: dict[str, Any], locale: str | None = "zh") -> dict[str, Any]:
    """Words the approval card shows: which site, which action, which element, what data."""
    lang = "en" if (locale or "zh")[:2] == "en" else "zh"
    text = _TEXT[lang]
    action = str(arguments.get("action", ""))
    origin = action_site(run, arguments)
    host = urlsplit(origin).hostname if origin else None
    word = _ACTION_WORDS[lang].get(action, action)
    target = ""
    element = None
    observation = (run.latest_observation or {}) if run is not None else {}
    if arguments.get("observation_id") == observation.get("observation_id"):
        element = next((e for e in observation.get("elements", []) if
                        (arguments.get("ref") and e.get("ref") == arguments["ref"]) or
                        (arguments.get("selector") and e.get("selector") == arguments["selector"])), None)
        if element and element.get("name"):
            role = element.get("role") or ""
            target = text["target"].format(
                role=_ROLE_WORDS[lang].get(role, role), name=str(element["name"])[:60]).strip()
    if action in NAVIGATION_ACTIONS:
        title = f"{word} {arguments.get('url', '')}"
    elif action == "press":
        title = text["press"].format(host=host or text["here"], key=arguments.get("key") or "Enter")
    else:
        title = text["on"].format(host=host or text["here"],
                                  action=f"{word} {target}".strip())
    typed = arguments.get("text")
    if action in _TEXT_ACTIONS and isinstance(typed, str) and typed:
        if action != "select" and _secret(element):
            title += text["hidden"].format(count=len(typed))
        else:
            shown = " ".join(typed.split())
            if len(shown) > _SHOWN_TEXT:
                shown = shown[:_SHOWN_TEXT] + "…"
            title += text["value"].format(text=shown)
    trust = site_trust(origin) if action in NAVIGATION_ACTIONS | INTERACTION_ACTIONS else "action"
    impacts = []
    if host:
        impacts.append(text["site"].format(host=host))
    if action == "upload":
        files = [str(path) for path in arguments.get("files") or []]
        impacts += [text["file"].format(path=path) for path in files[:_SHOWN_FILES]]
        if len(files) > _SHOWN_FILES:
            impacts.append(text["more_files"].format(count=len(files) - _SHOWN_FILES))
        impacts.append(text["upload"])
    elif host and is_private(host):
        impacts.append(text["private"])
    elif trust == "site":
        impacts.append(text["session"].format(host=host))
    elif host:
        impacts.append(text["sensitive"])
    destructive = action == "upload" or (trust == "action" and action in INTERACTION_ACTIONS)
    return {"title": title, "impacts": impacts, "risk": "destructive" if destructive else "benign"}


def fingerprint(run: Any, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """A site-wide approval key, or None when the action must be approved on its own."""
    action = arguments.get("action")
    # Uploading sends local files away; approving a site never covers it.
    if action not in NAVIGATION_ACTIONS | INTERACTION_ACTIONS or action == "upload":
        return None
    origin = action_site(run, arguments)
    if site_trust(origin) != "site":
        return None
    host = urlsplit(origin).hostname or ""
    if is_private(host) and action in INTERACTION_ACTIONS:
        return None
    return {"browser_site": origin}
