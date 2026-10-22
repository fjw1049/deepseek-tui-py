"""Notice when a UI surface stops returning anything new.

Same-args dedup (``tool_dedup``) cannot see a UI loop: every call's code differs while
the screen does not. Loops also rarely repeat back to back; they cycle (screenshot,
accessibility tree, an opened menu, the same screenshot again). So an observation counts
as new only if it matches none seen on that surface since the last reset, and a run of
results that are not new is the signal.

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
REMIND_STREAK = 3
BLOCK_STREAK = 8
MAX_HISTORY = 32

_KINDS = {
    "screenshot": "screenshots all matched earlier captures",
    "text": "text-only results all repeated earlier ones",
}

_UNCHANGED = (
    "\n\n<system-reminder>\n"
    "This observation matches one this interface already returned in this task: it shows "
    "nothing new.\n"
    "</system-reminder>"
)

_STUCK = (
    "\n\n<system-reminder>\n"
    "The last {streak} {kind} on this interface: the recent actions produced nothing "
    "new. Do not act on what you cannot see. Choose one and state it before acting: "
    "(1) a way to observe or reach the target you have not tried yet; "
    "(2) request_user_input for the step that needs the person; "
    "(3) stop and report the blocker and what remains.\n"
    "</system-reminder>"
)

_BLOCKED = (
    "Not executed: the last {streak} {kind} on this interface. "
    "Ask the user with request_user_input, or stop and report the blocker and what remains."
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


@dataclass
class _Seen:
    texts: set[str] = field(default_factory=set)
    images: list[_Thumb] = field(default_factory=list)

    def is_new(self, observation: _Observation) -> bool:
        """Record this observation; False when it shows nothing not seen before."""
        new_text = observation.text not in self.texts
        self.texts.add(observation.text)
        if not observation.images:
            return new_text
        new_image = False
        for image in observation.images:
            if not any(_similar(image, earlier) for earlier in self.images):
                new_image = True
                self.images.append(image)
                del self.images[:-MAX_HISTORY]
        return new_image


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
    _seen: dict[frozenset[str], _Seen] = field(default_factory=dict)
    # Per surface and kind ("screenshot" or "text"): consecutive results showing nothing new.
    _streak: dict[tuple[frozenset[str], str], int] = field(default_factory=dict)

    def reset(self) -> None:
        self._seen.clear()
        self._streak.clear()

    def blocked_content(self, tool_name: str) -> str | None:
        key = _surface_key(tool_name)
        for kind in _KINDS:
            streak = self._streak.get((key, kind), 0)
            if streak >= BLOCK_STREAK:
                return _BLOCKED.format(streak=streak, kind=_KINDS[kind])
        return None

    def record(self, tool_name: str, observation: _Observation | None) -> str:
        """Remember this observation; return the note to append to its tool result."""
        if observation is None:
            return ""
        key = _surface_key(tool_name)
        # With screenshots, only they decide: a window whose pixels never change has not
        # responded, even while the text beside them differs (another menu's tree, an
        # error). Text-only results keep their own count, so reading menus neither hides
        # nor clears an unresponsive window.
        kind = "screenshot" if observation.images else "text"
        if self._seen.setdefault(key, _Seen()).is_new(observation):
            self._streak[(key, kind)] = 0
            return ""
        streak = self._streak[(key, kind)] = self._streak.get((key, kind), 0) + 1
        logger.info("ui_observation_not_new tool=%s kind=%s streak=%d", tool_name, kind, streak)
        if streak >= REMIND_STREAK:
            return _STUCK.format(streak=streak, kind=_KINDS[kind])
        return _UNCHANGED
