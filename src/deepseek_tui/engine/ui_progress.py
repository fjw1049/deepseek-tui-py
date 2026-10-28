"""Notice when a UI surface stops returning anything new.

CUA compares host-captured observations against a short history to notice repeated
navigation as well as unchanged screens. Other surfaces compare consecutive results.
Missing expected text counts as unverified progress even when other content changes.
Pausing CUA actions always leaves observation available for recovery.

Screenshots are compared as grayscale thumbnails by their most-changed 8x8 block.
Measured on real desktop captures: re-encodes of one unchanged screen 0-1, a focus ring
appearing 9, one typed word 46. A mouse pointer drawn into one capture also counts as
change; erring that way only withholds a note, while the opposite error would tell the
model a real change did not happen.

State is turn-local. A person acting on the screen (a returned ``request_user_input``)
starts it over, because their change is not visible to this comparison's history.
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field

from PIL import Image, ImageChops

from deepseek_tui.config.paths import user_media_dir
from deepseek_tui.surfaces import SURFACES
from deepseek_tui.tools.registry import ToolResult

logger = logging.getLogger(__name__)

THUMB_WIDTH = 512
BLOCK = 8
SAME_BLOCK_DIFF = 2
# Three repeats trigger advice; a longer run of fully unchanged results pauses the surface.
REMIND_STREAK = 3
STALL_STREAK = 8

_UNCHANGED = (
    "\n\n<system-reminder>\n"
    "This observation matches the previous one of this kind: it shows "
    "nothing new.\n"
    "</system-reminder>"
)

_STUCK = (
    "\n\n<system-reminder>\n"
    "The last {streak} observations repeated earlier content on this interface. "
    "This may indicate stalled progress, but does not prove an action failed. "
    "Do not act on what you cannot see. Choose one and state it before acting: "
    "(1) a way to observe or reach the target you have not tried yet; "
    "(2) request_user_input for the step that needs the person; "
    "(3) stop and report the blocker and what remains.\n"
    "</system-reminder>"
)

_PAUSED = (
    "\n\n<system-reminder>\n"
    "The last {streak} observations on this interface were unchanged. Further calls on it "
    "are paused until the person acts: hand them the step (request_user_input when "
    "available), or stop and report the blocker and what remains (finish_task "
    "partial/blocked when available).\n"
    "</system-reminder>"
)

_BLOCKED = (
    "Not executed: the last {streak} observations on this interface were unchanged. "
    "Hand the step to the person (request_user_input when available), or stop and report "
    "the blocker and what remains (finish_task partial/blocked when available)."
)

_CUA_PAUSED = (
    "Further CUA code is paused because observations repeat or the expected change remains "
    "unverified. Use cua_observe to check for a real change; otherwise hand off or report "
    "partial/blocked. Do not repeat the same action."
)

_Thumb = Image.Image  # grayscale, THUMB_WIDTH wide: captures of one window at two scales match


@dataclass(frozen=True)
class _Observation:
    text: str
    images: tuple[_Thumb, ...]
    canonical: bool = False
    browser: bool = False


def _canonical_text(text: str) -> str:
    # IDs and focus move even when the fields and their values do not.
    lines = (line for line in text.splitlines()
             if not line.startswith("The focused UI element is"))
    return "\n".join(re.sub(r"^\s*\d+\s+", "", line).strip()
                     for line in lines if line.strip())


def _similar(a: _Thumb, b: _Thumb) -> bool:
    if a.size != b.size:
        return False
    diff = ImageChops.difference(a, b)
    blocks = diff.resize((max(1, diff.width // BLOCK), max(1, diff.height // BLOCK)), Image.BOX)
    return blocks.getextrema()[1] <= SAME_BLOCK_DIFF


def _thumbnail(asset_id: str) -> _Thumb:
    with Image.open(user_media_dir() / asset_id) as image:
        image.draft("L", (THUMB_WIDTH * 2, THUMB_WIDTH * 2))
        gray = image.convert("L")
    height = max(1, round(gray.height * THUMB_WIDTH / gray.width))
    return gray.resize((THUMB_WIDTH, height), Image.BOX)


def observation_of(result: ToolResult) -> _Observation | None:
    """What a successful surface call showed, or None when it showed nothing to compare."""
    if not result.success:
        return None
    browser = (result.metadata or {}).get("browser")
    cua = (result.metadata or {}).get("cua_observation")
    if isinstance(cua, dict):
        text = (json.dumps(cua.get("target"), sort_keys=True) + "\n"
                + _canonical_text(cua.get("text", "")))
        # Keep pixels too: canvas changes may never appear in accessibility text.
    elif result.metadata.get("cua_runtime_content"):
        return None  # Arbitrary JS can print anything, including stale or filtered state.
    elif isinstance(browser, dict):
        # Receipts and ids change on every call; only the page's own content counts.
        observation = browser.get("observation")
        if isinstance(observation, dict):
            text = re.sub(r"(?m)^已保存\s*(?:\n)?\d{1,2}:\d{2}(?::\d{2})?\s*$",
                          "已保存", observation.get("text", ""))
            text = json.dumps({
                "text": text, "url": observation.get("url"),
                "frame": observation.get("frame_id"),
                "text_offset": observation.get("text_offset"),
                "element_offset": observation.get("element_offset"),
                "viewport": observation.get("viewport"),
                "editor": observation.get("editor"),
                "controls": [{k: e.get(k) for k in (
                    "role", "name", "checked", "selected_text", "expanded", "disabled"
                )} for e in observation.get("elements", [])],
                "scroll": [e.get("viewport") for e in observation.get("scroll_containers", [])],
            }, ensure_ascii=False, sort_keys=True)
        else:
            text = ""
    else:
        text = result.content or ""
    try:
        images = tuple(_thumbnail(image.asset_id) for image in result.images)
    except (OSError, ValueError):
        logger.debug("ui_progress_image_unreadable", exc_info=True)
        return None
    if not text and not images:
        return None
    return _Observation(text, images, canonical=isinstance(cua, dict),
                        browser=isinstance(browser, dict))


def _surface_key(tool_name: str) -> frozenset[str]:
    # Surfaces that share tools (desktop and Chrome through one CUA connection) share history.
    return next((s.tools for s in SURFACES if tool_name in s.tools), frozenset({tool_name}))


@dataclass
class UiProgress:
    # Non-CUA surfaces keep their consecutive-observation behavior.
    _last: dict[tuple[frozenset[str], str], _Observation] = field(default_factory=dict)
    _streak: dict[frozenset[str], int] = field(default_factory=dict)
    _history: dict[tuple[frozenset[str], str], deque] = field(default_factory=dict)
    _unobserved: dict[frozenset[str], int] = field(default_factory=dict)
    _browser_failures: int = 0

    def reset(self) -> None:
        self._last.clear()
        self._streak.clear()
        self._history.clear()
        self._unobserved.clear()
        self._browser_failures = 0

    def blocked_content(self, tool_name: str, arguments: dict | None = None) -> str | None:
        if tool_name == "browser_use" and arguments and arguments.get("action") in {
            "status", "operation_status", "observe", "describe", "screenshot", "wait",
            "check_text", "tabs", "downloads", "recover", "request_assistance",
        }:
            return None
        if tool_name == "browser_use" and self._browser_failures >= STALL_STREAK:
            return ("Not executed: repeated browser failures. "
                    "Observe the blocker or request assistance.")
        if tool_name in {"cua_observe", "cua_js_reset"}:
            return None  # A stalled or externally changed interface must remain inspectable.
        if self._unobserved.get(_surface_key(tool_name), 0) >= STALL_STREAK:
            return ("Not executed: use cua_observe to check the expected result "
                    "before more CUA code.")
        streak = self._streak.get(_surface_key(tool_name), 0)
        if tool_name in {"cua_js", "cua_js_reset"} and streak >= STALL_STREAK:
            return "Not executed: " + _CUA_PAUSED
        return _BLOCKED.format(streak=streak) if streak >= STALL_STREAK else None

    def record_result(self, tool_name: str, result: ToolResult) -> str:
        observation = observation_of(result)
        if tool_name == "browser_use":
            receipt = result.metadata.get("browser", {}).get("receipt", {})
            if not result.success or receipt.get("effect") == "not_confirmed":
                self._browser_failures += 1
                if self._browser_failures >= REMIND_STREAK:
                    return _STUCK.format(streak=self._browser_failures)
            elif receipt.get("effect") == "confirmed":
                self._browser_failures = 0
        key = _surface_key(tool_name)
        if result.metadata.get("cua_runtime_content") and observation is None:
            self._unobserved[key] = self._unobserved.get(key, 0) + 1
            return ("\nUse cua_observe to check whether the intended change happened; "
                    "code returning successfully is not verified progress."
                    if self._unobserved[key] >= REMIND_STREAK else "")
        if observation is not None:
            self._unobserved[key] = 0
        checks = result.metadata.get("cua_observation", {}).get("expectations", [])
        if observation is not None and any(not check["matched"] for check in checks):
            streak = self._streak[key] = self._streak.get(key, 0) + 1
            return ("\nThe expected change is not verified. "
                    + (_CUA_PAUSED if streak >= STALL_STREAK else _STUCK.format(streak=streak)))
        return self.record(tool_name, observation)

    def record(self, tool_name: str, observation: _Observation | None) -> str:
        if observation is None:
            return ""
        key = _surface_key(tool_name)
        kind = "screenshot" if observation.images else "text"
        previous = self._last.get((key, kind))
        self._last[(key, kind)] = observation
        unchanged = (
            previous is not None
            and previous.text == observation.text
            and len(previous.images) == len(observation.images)
            and all(_similar(a, b)
                    for a, b in zip(previous.images, observation.images, strict=True))
        )
        if observation.canonical or observation.browser:
            history = self._history.setdefault((key, kind), deque(maxlen=STALL_STREAK))
            unchanged = any(
                old.text == observation.text
                and len(old.images) == len(observation.images)
                and all(_similar(a, b) for a, b in zip(old.images, observation.images, strict=True))
                for old in history
            )
            history.append(observation)
        if not unchanged:
            # Progress in either channel clears the surface's warning streak.
            self._streak[key] = 0
            if observation.browser:
                self._browser_failures = 0
            return ""
        streak = self._streak[key] = self._streak.get(key, 0) + 1
        logger.info("ui_observation_unchanged tool=%s kind=%s streak=%d", tool_name, kind, streak)
        if streak >= STALL_STREAK:
            return _CUA_PAUSED if observation.canonical else _PAUSED.format(streak=streak)
        if streak >= REMIND_STREAK:
            return _STUCK.format(streak=streak)
        return _UNCHANGED
