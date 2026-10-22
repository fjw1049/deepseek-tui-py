"""UI surfaces the agent can operate, as one registry for routing, focus and context.

A surface is a place where actions happen through an interface rather than an API:
the Workbench browser, the user's Chrome, desktop apps. The engine's generic
mechanisms (prompt routing, the task phase, vision-helper context) read this table
instead of naming tools; adding a surface means adding an entry here and its guide.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Surface:
    id: str
    tier: str  # "web" | "desktop"; tiers render in this order after structured tools
    route: str  # one line in the routing list
    tools: frozenset[str]
    guide: str | None = None  # prompts/<guide> injected while the surface is available
    # Call arguments a vision helper may see as context for this surface's screenshots.
    context_keys: tuple[str, ...] = ()
    # Tools that belong to the surface without operating it; they never start a task.
    aux_tools: frozenset[str] = frozenset()
    # Operating it also narrows the turn to the task-scoped tool set. Off where the
    # surface is routinely a step inside other work (checking a native UI you build).
    focus: bool = False


CUA_TOOLS = frozenset({"cua_js", "cua_js_reset"})

SURFACES: tuple[Surface, ...] = (
    Surface(
        "browser",
        "web",
        "the Workbench browser via `browser_use`, for sites, web apps and local previews",
        frozenset({"browser_use", "browser_skill"}),
        guide="browser.md",
        context_keys=("action", "ref", "selector", "frame_id", "observation_id", "full_page",
                      "crop"),
        aux_tools=frozenset({"browser_skill"}),
        focus=True,
    ),
    Surface(
        "chrome",
        "web",
        "the user's own Chrome via `cua_js`, when the task needs its tabs, sign-ins or "
        "extensions",
        CUA_TOOLS,
    ),
    Surface(
        "desktop",
        "desktop",
        "`cua_js` for native apps, system dialogs, cross-app workflows and checking native "
        "UIs you build. This is the right tool for native apps; do not decline a native-app "
        "task because no API exists",
        CUA_TOOLS,
        guide="computer_use.md",
        context_keys=("title", "code"),
    ),
)


def surface_tools() -> frozenset[str]:
    return frozenset().union(*(surface.tools for surface in SURFACES))


def task_tools() -> frozenset[str]:
    """Tools whose use makes the turn a UI task that ends with an evidence-backed delivery."""
    return frozenset().union(*(s.tools - s.aux_tools for s in SURFACES))


def focus_tools() -> frozenset[str]:
    """Task tools whose use also narrows the turn's tool set."""
    return frozenset().union(*(s.tools - s.aux_tools for s in SURFACES if s.focus))


def context_keys_for(tool_name: str) -> tuple[str, ...]:
    return next((s.context_keys for s in SURFACES if tool_name in s.tools and s.context_keys), ())


def cua_surfaces(cua_config) -> frozenset[str]:
    """The surfaces one CUA connection offers under its configuration."""
    return frozenset({"desktop", "chrome"} if cua_config.chrome else {"desktop"})
