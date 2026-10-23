"""Notice when a UI surface stops returning anything new.

Compare consecutive observations, not all states visited in a task. A few repeats are
only a warning: they cannot prove that an action failed. A long run of results with
nothing changed at all pauses that surface until a person acts, so a dead loop ends in
a handoff or an honest report instead of spending the whole round budget on screenshots.

Screenshots are compared as grayscale thumbnails by their most-changed 8x8 block.
Measured on real desktop captures: re-encodes of one unchanged screen 0-1, a focus ring
appearing 9, one typed word 46. A mouse pointer drawn into one capture also counts as
change; erring that way only withholds a note, while the opposite error would tell the
model a real change did not happen.

State is turn-local. A person acting on the screen (a returned ``request_user_input``)
starts it over, because their change is not visible to this comparison's history.
"""

from __future__ import annotations

import logging
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

_Thumb = Image.Image  # grayscale, THUMB_WIDTH wide: captures of one window at two scales match


@dataclass(frozen=True)
class _Observation:
    text: str
    images: tuple[_Thumb, ...]


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
    if isinstance(browser, dict):
        # Receipts and ids change on every call; only the page's own content counts.
        observation = browser.get("observation")
        text = observation.get("text", "") if isinstance(observation, dict) else ""
    else:
        text = result.content or ""
    try:
        images = tuple(_thumbnail(image.asset_id) for image in result.images)
    except (OSError, ValueError):
        logger.debug("ui_progress_image_unreadable", exc_info=True)
        return None
    if not text and not images:
        return None
    return _Observation(text, images)


def _surface_key(tool_name: str) -> frozenset[str]:
    # Surfaces that share tools (desktop and Chrome through one CUA connection) share history.
    return next((s.tools for s in SURFACES if tool_name in s.tools), frozenset({tool_name}))


@dataclass
class UiProgress:
    # Keep only the previous observation per kind, so normal A/B navigation is progress.
    _last: dict[tuple[frozenset[str], str], _Observation] = field(default_factory=dict)
    _streak: dict[frozenset[str], int] = field(default_factory=dict)

    def reset(self) -> None:
        self._last.clear()
        self._streak.clear()

    def blocked_content(self, tool_name: str) -> str | None:
        streak = self._streak.get(_surface_key(tool_name), 0)
        return _BLOCKED.format(streak=streak) if streak >= STALL_STREAK else None

    def record_result(self, tool_name: str, result: ToolResult) -> str:
        return self.record(tool_name, observation_of(result))

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
            and all(_similar(a, b) for a, b in zip(previous.images, observation.images))
        )
        if not unchanged:
            # Progress in either channel clears the surface's warning streak.
            self._streak[key] = 0
            return ""
        streak = self._streak[key] = self._streak.get(key, 0) + 1
        logger.info("ui_observation_unchanged tool=%s kind=%s streak=%d", tool_name, kind, streak)
        if streak >= STALL_STREAK:
            return _PAUSED.format(streak=streak)
        if streak >= REMIND_STREAK:
            return _STUCK.format(streak=streak)
        return _UNCHANGED
