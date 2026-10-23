"""Notice when a UI surface stops returning anything new.

Compare consecutive observations, not all states visited in a task. Repeated output
is only a warning: it cannot prove that an action failed or that another observation
would be unsafe. Existing execution budgets bound loops without blocking recovery.

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
# Three repeats trigger advice only; the execution budget remains the hard limit.
REMIND_STREAK = 3

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
        if streak >= REMIND_STREAK:
            return _STUCK.format(streak=streak)
        return _UNCHANGED
