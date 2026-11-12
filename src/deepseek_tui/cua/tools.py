"""Expose only runtime-supplied public tools through the existing tool registry."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import unicodedata
from dataclasses import replace
from typing import Any

from deepseek_tui.cua import app_scope
from deepseek_tui.cua.ax_text import is_listing, shorten
from deepseek_tui.cua.session import CuaSession, StaleTarget
from deepseek_tui.surfaces import CUA_TOOLS  # noqa: F401 - re-exported for CUA wiring
from deepseek_tui.tools.registry import ToolCapability, ToolContext, ToolError, ToolResult, ToolSpec
from deepseek_tui.utils import current_tool, current_turn

MAX_CUA_TEXT_BYTES = 64 * 1024
# Runtime text blocks this large are remembered so a verbatim repeat can be shortened.
REPEATED_TEXT_MIN_BYTES = 4096
MAX_REMEMBERED_TEXTS = 8
# Large web views list only part of their tree; persistent navigation often sits past the cut.
_AX_TRUNCATED = re.compile(r"\(showing \d+-(\d+) of (\d+) items\)")
_AX_RANGE_MARKER = re.compile(r"\(showing\b", re.IGNORECASE)
_COORDINATE_CLICK = re.compile(r"\.click\(\s*\[")
AX_TRUNCATED_NOTE = (
    "[Host note: this accessibility tree is truncated. Elements past the listed range exist "
    "but are not shown, so an unlisted element is not evidence that it is absent, and a '+' "
    "line can be an element that moved into the range. Locate unlisted targets with a screenshot.]"
)
COORDINATE_CLICK_NOTE = (
    "[Host note: a coordinate click does not report what it hit. Before the next action, "
    "confirm the intended target took effect; if not, look for the target's element index in "
    "a fresh accessibility tree before trying coordinates again.]"
)
WINDOWS_NOTE = (
    "[Host note: {app} has {count} windows open on screen, but its accessibility state shows "
    "only the front one. To work in another window, choose it from the app's Window menu or "
    "press super+grave to cycle windows, then get fresh state.]"
)
NOT_SENT_NOTE = "[Host: nothing reached the app; once the call is fixed, running it is safe.]"
UNCERTAIN_NOTE = (
    "[Host: this call may have changed the app before it failed. Check its state with "
    "cua_observe before repeating anything.]"
)
UNCERTAIN_OBSERVED_NOTE = (
    "[Host: this call may have changed the app before it failed. The host observed {app} "
    "just now; the state below is current. Decide from it and do not repeat an action that "
    "already took effect. Element indices from before may be stale.]"
)
UNKNOWN_OUTCOME_NOTE = (
    "Not executed: an earlier computer-use call has an unknown outcome and may already have "
    "taken effect. The host observed {app} for you first; the state below is current. "
    "Variables and element indices from before may be gone. Check whether that effect "
    "happened, then bind the app again and issue only what is still needed."
)
SHORTENED_NOTE = (
    "[Host: this accessibility listing was too large to show whole, so long lists are "
    "shortened. Each '… N more items here not shown' line stands for elements that still "
    "exist, with their index range. {saved}]"
)
# Ever shorter runs until the listing fits: (members kept at the start, at the end).
_SHORTEN_STEPS = ((8, 4), (4, 2), (2, 1), (1, 1))
# Waits poll the accessibility text this often; a screenshot comes only with the final read.
WAIT_POLL_SECONDS = 0.5
MAX_WAIT_MS = 30_000
HANDOFF_NOTICE = (
    "[CUA session reset for desktop handoff. Old JavaScript variables and element references "
    "are invalid. Use cua_observe before rebuilding bindings and acting.]"
)


async def handoff_notice(since: float | None, surface: dict[str, str] | None) -> str:
    """The reset notice, plus what the host can say about the desktop the user just held.

    The host never sees what the user did, so the model is told to expect anything.
    """
    from deepseek_tui.cua.apps import on_screen_apps

    held = f" for {int(time.time() - since)}s" if since else ""
    facts = [f"The user held the desktop{held} and may have changed anything on it, including "
             "which app or window is in front."]
    if surface:
        facts.append(f"Your last target was {surface.get('app_id') or 'the browser'}.")
    if apps := await asyncio.to_thread(on_screen_apps):
        facts.append("Apps on screen now, front to back: " + ", ".join(apps) + ".")
    return "[" + " ".join(facts) + "]\n" + HANDOFF_NOTICE


# Runtime failures the host can name, from the runtime's numeric codes and its fixed messages.
_RUNTIME_ERRORS = (
    ("stale_element", (), r"is an invalid element ID|element ID is no longer valid|"
     r"element was invalidated",
     "Element indices come only from the latest accessibility state. Get fresh state and use a "
     "current index."),
    ("text_not_found", (), r"Could not find the requested text to select",
     "selectText matches the element's exact current text. Read its value from fresh state, add "
     "prefix or suffix to tell repeats apart, or take another route."),
    ("invalid_key", (), r"keyNotFound",
     "Use xdotool-style key names, which are case-sensitive: \"Return\", \"Tab\", \"Down\", "
     "\"super+Down\" (super is Command on macOS)."),
    ("unsupported_form", (), r"only supported on Linux|accepts pages, not pixels|"
     r"requires an app name, path, or bundle ID|is unavailable on (macOS|Linux|Windows)|"
     r"Capability is not available",
     "This call form is not available on this platform. Use the form the documentation gives "
     "for it (for example, on macOS select or focus first, then typeText(text))."),
    ("unknown_app", ("-10007", "-10010", "-10018"), r"^Invalid app:|Unknown app|ambiguous app",
     "Use an exact app id from cua.listApps() or cua.getState(); a display name can fail."),
    ("permissions_pending", ("-10014",), r"permissions are still pending",
     "The user is still granting system permissions. Call the same API again; do not end the "
     "turn."),
    ("screen_locked", ("-10020",), r"The Mac is locked",
     "The screen is locked. Ask the person to unlock it (request_user_input with kind=\"action\", "
     "surface=\"desktop\" when available); do not retry before that."),
    ("state_changed", (), r"The user changed '.*'\. Re-query the latest state",
     "The app changed since your last state read; this also follows your own window or menu "
     "change. Call getAXState() on the bound app (get_app_state in the message is the runtime's "
     "internal name) and act on fresh indices."),
    ("screenshot_unavailable", (), r"Screenshot unavailable for|The screen capture failed|SCStreamErrorDomain Code=-3811",
     "This app has no screenshot in its current state, for example while a menu is open or its "
     "window is hidden or minimized. Use getAXState(), or close the menu or show the window "
     "first."),
    # Shares -10005 with timeouts, so only its own text names it.
    # Raised by the host's input wrapper (bridge.mjs) before anything is sent.
    ("stale_coordinates", (), r"Coordinate guard:",
     "Coordinates come only from the app's latest screenshot. Take a new screenshot and locate "
     "the target again; element indices are unaffected."),
    ("no_window", (), r"noWindowsAvailable",
     "The app has no window the runtime can act on (closed, minimized, or on another "
     "Space); nothing was sent. Bring a window up first: reopen it from the app's menu bar "
     "(Window or File menu, or super+n where that opens one), then get fresh state. Do not "
     "click coordinates while no window is listed."),
    ("unbound_name", (), r"^[A-Za-z_$][\w$]* is not defined$",
     "A name used here was never assigned in this REPL. Bindings persist across calls only when "
     "assigned (const app = await cua.getApp(...)); a reset or reconnect clears them."),
    ("user_stopped", ("-10012",), r"explicitly stopped by the user",
     "The user stopped computer use for this turn. Stop desktop actions and report where the "
     "task stands."),
    ("user_intervened", ("-10016",), r"user intervened",
     "The user operated the app during this call. Observe before deciding anything; do not "
     "repeat the action blindly."),
    ("app_denied", ("-10006",), r"not allowed to use the app|blocked from using the app|"
     r"was not approved to use",
     "Access to this app was refused. Do not retry it or reach it through another tool; tell "
     "the user."),
    ("version_mismatch", ("-10013",), r"version mismatch",
     "The computer-use runtime needs the ChatGPT app to be relaunched or updated. Stop computer "
     "use and tell the user."),
)
_SERVER_CODE = re.compile(r"Computer Use server error (-\d+)")
_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‟": '"', "‘": "'", "’": "'"})


def runtime_error(text: str) -> tuple[str, str] | None:
    """The kind and guidance of a failure the runtime reported, when the host can name it."""
    code = _SERVER_CODE.search(text)
    for kind, codes, pattern, guidance in _RUNTIME_ERRORS:
        if code and code.group(1) in codes or re.search(pattern, text, re.MULTILINE):
            return kind, guidance
    return None


def _comparable(text: str) -> str:
    """Normalize width, quotes, case and incidental spacing, never the characters themselves."""
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).translate(_QUOTES)).casefold()
    # Spaces carry no meaning next to punctuation or CJK text.
    return re.sub(r" ?([^\w\s]|[\u3000-\u9fff]) ?", r"\1", text)


def text_observed(text: str, expected: str) -> bool:
    return _comparable(expected) in _comparable(text)


_DESKTOP_ACTION_TEXT = {
    "zh": ("需要你在电脑上操作", "我已完成", "完成后继续原任务", "跳过这一步", "不做这一步，让助手另找办法"),
    "en": ("Your help on the computer", "Done", "Continue the task", "Skip this step",
           "Let the assistant find another way"),
}


def desktop_action_question(reason: str, locale: str | None) -> dict[str, Any]:
    header, done, done_hint, skip, skip_hint = _DESKTOP_ACTION_TEXT.get(
        (locale or "zh")[:2], _DESKTOP_ACTION_TEXT["en"]
    )
    return {
        "header": header,
        "id": "desktop_action",
        "question": reason,
        "options": [
            {"label": done, "description": done_hint},
            {"label": skip, "description": skip_hint},
        ],
    }


def desktop_action_result(
    question: dict[str, Any], response: dict[str, Any], notice: str = HANDOFF_NOTICE,
) -> dict[str, Any]:
    done, skip = (option["label"] for option in question["options"])
    choice, text = "dismissed", ""
    answers = response.get("answers") or []
    for answer in answers.values() if isinstance(answers, dict) else answers:
        if isinstance(answer, dict):
            keys = ("label", "value", "selected_option", "answer", "text")
            values = [answer.get(k) for k in keys]
        else:
            values = [answer]
        text = next((v for v in values if isinstance(v, str) and v.strip()), text)
        if done in values:
            choice = "done"
        elif skip in values:
            choice = "skip"
        elif text:
            choice = "information"
    guidance = {
        "done": "The user reports the step is done. That is their statement, not a verified "
                "result: observe the desktop again and confirm before relying on it.",
        "skip": "The user declined this step. Do not ask again without new evidence; find "
                "another authorized route or report what remains blocked.",
        "information": "The user replied with information instead; incorporate it.",
        "dismissed": "The user dismissed the request. Do not repeat it without new evidence.",
    }[choice]
    return {
        "choice": choice,
        "user_text": text if choice == "information" else "",
        "instructions": guidance + " " + notice,
    }


def ax_complete(text: str) -> bool:
    """Whether an accessibility listing shows every item it reports."""
    ranges = _AX_TRUNCATED.findall(text)
    # A range marker in an unfamiliar format may hide a truncation; never read it as complete.
    if len(ranges) < len(_AX_RANGE_MARKER.findall(text)):
        return False
    return all(int(shown) >= int(total) for shown, total in ranges)


def cua_surface(meta: Any) -> dict[str, str] | None:
    """What this call last touched, from the runtime's own result metadata (UI only).

    Native apps carry their bundle id; the live preview captures that app's window.
    Browser calls carry no app: an agent tab need not be the window's visible tab, so
    the preview shows the call's own screenshots instead of capturing the window.
    """
    surface = meta.get("codex/toolSurface") if isinstance(meta, dict) else None
    if not isinstance(surface, dict):
        return None
    if surface.get("kind") == "computerUse":
        app = surface.get("app")
        app_id = app.get("appId") if isinstance(app, dict) else None
        return {"kind": "app", "app_id": app_id} if isinstance(app_id, str) and app_id else None
    if surface.get("kind") == "browserUse":
        return {"kind": "browser"}
    return None


def collapse_repeated_texts(messages, new: int, texts: list[str]) -> None:
    """Shorten a large runtime text that the newest CUA results repeat from earlier context.

    Every new connection makes the runtime return its first-call guide again (about 24 KB)
    while the earlier copy is still above. Only a copy present right now is referenced;
    when pruning or compaction later drops it, add_documentation_reminder asks for a fresh
    read. An explicit rewriteDocumentation call always keeps its result whole.
    """
    from deepseek_tui.protocol.messages import ToolResultBlock, ToolUseBlock

    if new <= 0 or not texts:
        return
    calls = {b.id: b for m in messages for b in m.content if isinstance(b, ToolUseBlock)}
    earlier = [b for m in messages[:-new] for b in m.content if isinstance(b, ToolResultBlock)]
    for index in range(len(messages) - new, len(messages)):
        message, blocks, changed = messages[index], [], False
        for block in message.content:
            call = calls.get(getattr(block, "tool_use_id", ""))
            if (isinstance(block, ToolResultBlock) and call is not None
                    and call.name in CUA_TOOLS
                    and "rewriteDocumentation" not in str(call.input.get("code", ""))):
                content = block.content
                for text in texts:
                    source = next((b.tool_use_id for b in earlier if text in b.content), None)
                    if source and text in content:
                        content = content.replace(text, (
                            f"[Same {len(text)}-character runtime text as the result of tool "
                            f"call {source} above; not repeated.]"
                        ))
                if content != block.content:
                    block, changed = block.model_copy(update={"content": content}), True
            blocks.append(block)
        if changed:
            messages[index] = message.model_copy(update={"content": blocks})


def add_documentation_reminder(messages) -> None:
    from deepseek_tui.protocol.messages import Message, MessageOrigin

    text = (
        "[CUA context was compacted or tool documentation was pruned. Before further computer "
        "use, call await cua.rewriteDocumentation() and read its complete output. "
        "If the connection was reset, start with a documented entry point instead.]"
    )
    messages[:] = [
        m
        for m in messages
        if not (m.origin == MessageOrigin.SYSTEM_REMINDER and m.text_content() == text)
    ]
    messages.append(Message.user(text, origin=MessageOrigin.SYSTEM_REMINDER))


def _text_bytes(blocks: list[Any]) -> int:
    return sum(len(str(b.get("text", "")).encode("utf-8")) for b in blocks
               if isinstance(b, dict) and b.get("type") == "text")


async def _shorten_listings(payload: dict[str, Any], call_id: str) -> dict[str, Any] | None:
    """Fit an oversized result by shortening its accessibility listings in place.

    Returns the note for the model and how many elements were left out, or None when the
    result already fits or cannot be made to fit this way (it then spills as before).
    """
    blocks = payload.get("content") or []
    if _text_bytes(blocks) <= MAX_CUA_TEXT_BYTES:
        return None
    listings = [b for b in blocks if isinstance(b, dict) and b.get("type") == "text"
                and is_listing(str(b.get("text", "")))]
    originals = [b["text"] for b in listings]
    # Leave room for the note and the host's own notes.
    budget = MAX_CUA_TEXT_BYTES - 2048
    for first, last in _SHORTEN_STEPS if listings else ():
        omitted = 0
        for block, text in zip(listings, originals, strict=True):
            block["text"], count = shorten(text, first, last)
            omitted += count
        if omitted and _text_bytes(blocks) <= budget:
            break
    else:
        for block, text in zip(listings, originals, strict=True):
            block["text"] = text
        return None
    from deepseek_tui.tools.runtime import write_spillover

    try:
        path = await asyncio.to_thread(write_spillover, call_id, "\n\n".join(originals))
        saved = (f"The full listing is saved to {path}; read the part you need with "
                 "read_file, or scroll or search the app, before acting on a hidden item.")
    except OSError:
        saved = "Scroll or search the app to reach a hidden item before acting on it."
    return {"note": SHORTENED_NOTE.format(saved=saved), "omitted": omitted}


def _call_ids(context: ToolContext) -> tuple[str, str]:
    return (context.metadata.get("cua_turn_id") or current_turn(),
            context.metadata.get("cua_call_id") or current_tool())


def _with_stats(result: ToolResult, **values: Any) -> ToolResult:
    """Add to the per-call record kept for measuring computer use (never model-visible)."""
    stats = {**result.metadata.get("cua_stats", {}), **values}
    return replace(result, metadata={**result.metadata, "cua_stats": stats})


def _inputs(trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [action for action in trace.get("actions", []) if not action.get("observe")]


def _ends_observed(trace: dict[str, Any] | None) -> bool:
    """The call's last recorded step read the UI successfully, after any input it sent."""
    actions = (trace or {}).get("actions") or []
    return bool(actions) and bool(actions[-1].get("observe")) and actions[-1].get("ok") is True


def _coordinate_input(trace: dict[str, Any] | None, input_data: dict[str, Any]) -> bool:
    if trace is None:
        # No record from this runtime: fall back to reading the code.
        return bool(_COORDINATE_CLICK.search(str(input_data.get("code", ""))))
    return any(action.get("coordinate") for action in _inputs(trace))


# Rejected while validating the request, before any input is sent.
_PRE_DISPATCH = frozenset({"stale_element", "text_not_found", "invalid_key", "unsupported_form",
                           "unknown_app", "state_changed", "no_window", "stale_coordinates"})


def _sent_no_input(trace: dict[str, Any] | None, kind: str | None) -> bool:
    """A failed call provably reached no UI: recorded, no DOM tab in reach, and either no
    input or a single input the runtime rejected before sending it."""
    if trace is None or trace.get("tabs"):
        return False
    actions = _inputs(trace)
    return not actions or (
        len(actions) == 1 and actions[0].get("ok") is False and kind in _PRE_DISPATCH)


class CuaTool(ToolSpec):
    def __init__(
        self,
        session: CuaSession,
        descriptor: dict[str, Any],
        cancel_events: list[asyncio.Event] | None = None,
    ):
        self.session = session
        self.descriptor = descriptor
        self.cancel_events = cancel_events or []

    def name(self) -> str:
        return "cua_" + self.descriptor["name"]

    def description(self) -> str:
        return self.descriptor["description"]

    def input_schema(self) -> dict[str, Any]:
        return self.descriptor["inputSchema"]

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.EXECUTES_CODE, ToolCapability.REQUIRES_APPROVAL]

    def supports_parallel(self) -> bool:
        return False

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext, *, scope: str | None = None,
        exclusive: bool = False,
    ) -> ToolResult:
        context.metadata["cua_session"] = self.session
        js = self.descriptor["name"] == "js"
        if js and self.session.outside_change and (target := self.session.heal_target()):
            return await self._observe_instead(target, context, self.session.outside_change)
        if (js and input_data.get("code") and self.session.needs_outcome_observation
                and (target := self.session.heal_target())):
            # Observe once before further work; the uncertain receipt remains pending.
            observed = await CuaObserveTool(self.session, self.cancel_events).execute(
                target, context)
            if observed.success:
                return _with_stats(replace(observed, success=False, content=(
                    UNKNOWN_OUTCOME_NOTE.format(app=target["app"]) + "\n" + observed.content)),
                    replaced_by_observation=True)
        try:
            result = await self._execute(input_data, context, scope=scope, exclusive=exclusive)
        except StaleTarget as stale:
            if not stale.app:
                raise
            return await self._observe_instead({"app": stale.app}, context, stale.reason)
        if not result.success and self.descriptor["name"] == "js":
            kind = result.metadata.get("cua_error_kind")
            if kind == "user_intervened":
                self.session.invalidate_observation(
                    "The user operated the app during the last call; inspect its actual state.")
            elif not _sent_no_input(result.metadata.get("cua_trace"), kind):
                self.session.invalidate_observation("CUA code failed; inspect its actual effects.")
            else:
                return _with_stats(replace(result, content=result.content + "\n" + NOT_SENT_NOTE),
                                   delivery="not_sent")
            return await self._observe_after_failure(result, context)
        return result

    async def _observe_after_failure(self, result: ToolResult, context: ToolContext) -> ToolResult:
        """A failure that may have reached the app comes back with the app's current state,
        so the model decides from it at once instead of spending a call to look."""
        target = self.session.heal_target()
        observed = (await CuaObserveTool(self.session, self.cancel_events).execute(target, context)
                    if target else None)
        if observed is None or not observed.success:
            # The guard stays: the next cua_js call observes first.
            return _with_stats(replace(result, content=result.content + "\n" + UNCERTAIN_NOTE),
                               delivery="uncertain")
        return _with_stats(replace(
            result,
            content=(result.content + "\n" + UNCERTAIN_OBSERVED_NOTE.format(app=target["app"])
                     + "\n" + observed.content),
            images=[*result.images, *observed.images],
            metadata={**result.metadata, "cua_observed": True},
        ), delivery="uncertain", observed_after_failure=True,
            observe_runtime_ms=observed.metadata.get("cua_stats", {}).get("runtime_ms"))

    async def _observe_instead(
        self, target: dict[str, str], context: ToolContext, reason: str,
    ) -> ToolResult:
        """Code waits on a fresh observation; take it now instead of refusing the call."""
        observed = await CuaObserveTool(self.session, self.cancel_events).execute(target, context)
        if not observed.success:
            # Some apps cannot be observed at all (custom-drawn, windowless). Holding code
            # until an observation succeeds would block them for good, so open the gate.
            self.session.stop_waiting_on(target["app"])
            return _with_stats(replace(observed, content=(
                f"Not executed: {reason} The host tried to observe {target['app']} for you and "
                "could not:\n" + observed.content
                + "\nYour next cua_js runs. Read the app's state in that code first "
                "(bind it and get its state or a screenshot) and act only on what it shows.")),
                replaced_by_observation=True)
        return _with_stats(replace(observed, success=False, content=(
            f"Not executed: {reason} The host observed {target['app']} for you instead; the "
            "state below is current. Re-issue your code against it: element indices from "
            "before this observation may be stale.\n" + observed.content)),
            replaced_by_observation=True)

    async def _execute(
        self, input_data: dict[str, Any], context: ToolContext, *, scope: str | None = None,
        exclusive: bool = False,
    ) -> ToolResult:
        from deepseek_tui.mcp.execute import mcp_response_to_tool_result

        turn, call_id = _call_ids(context)
        scope_args = {"scope": scope, "exclusive": exclusive} if scope else {}
        payload = await self.session.run(
            lambda: self.session.call(self.descriptor["name"], input_data, turn, call_id, **scope_args),
            self.cancel_events,
        )
        for item in payload.get("content") or []:
            text = item.get("text") if isinstance(item, dict) else None
            if isinstance(text, str) and len(text.encode("utf-8")) >= REPEATED_TEXT_MIN_BYTES:
                texts = self.session.large_texts
                texts[:] = [t for t in texts if t != text][-(MAX_REMEMBERED_TEXTS - 1):] + [text]
        shortened = await _shorten_listings(payload, f"{call_id}-{self.descriptor['name']}")
        # Runtime failures are not argument errors: build without the generic MCP schema hint.
        result = mcp_response_to_tool_result(self.name(), {**payload, "isError": False})
        result = replace(result, success=not payload.get("isError"))
        images = [
            image.model_copy(
                update={
                    "source": {
                        **(image.source or {}),
                        "kind": "cua",
                        "tool": self.name(),
                        "session_id": self.session.session_id,
                        "turn_id": turn,
                        "tool_call_id": call_id,
                    }
                }
            )
            for image in result.images
        ]
        metadata = {**result.metadata, "cua_runtime_content": True,
                    "cua_stats": dict(payload.get("stats") or {})}
        if payload.get("unknown_outcome_note"):
            metadata["unknown_outcome_note"] = payload["unknown_outcome_note"]
        if self.descriptor["name"] == "observe":
            observation = payload.get("observation")
            if isinstance(observation, dict):
                text = str(observation.get("text", ""))
                observation["complete"] = ax_complete(text) and not shortened
                observation["expectations"] = [
                    {"text": expected, "matched": text_observed(text, expected)}
                    for expected in input_data.get("expect", [])
                ]
                metadata["cua_observation"] = observation
        if surface := cua_surface(payload.get("_meta")):
            metadata["cua_surface"] = surface
            if self.descriptor["name"] != "observe" or not (
                self.session.outside_change or self.session.reset_reason
            ):
                self.session.last_surface = surface
                self.session.lease.note_surface(surface)
        trace = payload.get("trace")
        if isinstance(trace, dict) and trace.get("ready"):
            metadata["cua_trace"] = trace
            # Code that ends by reading fresh UI state is not acting blind (engine/ui_progress.py),
            # though its printed text is still no completion evidence.
            metadata["cua_observed"] = _ends_observed(trace)
        content = result.content
        if shortened:
            content += "\n" + shortened["note"]
            metadata["cua_stats"]["shortened_items"] = shortened["omitted"]
        if not result.success and (named := runtime_error(content)):
            metadata["cua_error_kind"] = metadata["cua_stats"]["error"] = named[0]
            content += f"\n[Host: {named[0]}] {named[1]}"
        result = replace(result, content=content, images=images, metadata=metadata)
        if not result.success and "is not a function" in result.content:
            # JavaScript's own TypeError: the model guessed an API.
            result = replace(result, content=result.content + (
                "\nThat API does not exist. Use only the APIs in the documentation returned by "
                "the first call; await cua.rewriteDocumentation() shows it again."
            ))
        if result.success:
            notes = []
            if not ax_complete(result.content):
                notes.append(AX_TRUNCATED_NOTE)
            if _coordinate_input(metadata.get("cua_trace"), input_data):
                notes.append(COORDINATE_CLICK_NOTE)
            if surface and surface.get("kind") == "app" and (
                    windows := await self._windows_note(surface["app_id"])):
                notes.append(windows)
            if notes:
                result = replace(result, content="\n".join([result.content, *notes]))
        result = _with_stats(result, text_bytes=len(result.content.encode("utf-8")),
                             images=len(result.images))
        if len(result.content.encode("utf-8")) > MAX_CUA_TEXT_BYTES:
            from deepseek_tui.tools.runtime import write_spillover

            try:
                path = await asyncio.to_thread(write_spillover, call_id, result.content)
                recovery = (
                    f"Full output saved to {path}. Read it in bounded sections with read_file."
                )
            except OSError:
                recovery = (
                    "The full output could not be saved. Request a smaller read-only observation."
                )
            return replace(
                result,
                success=False,
                content=(
                    "CUA executed, but its text output exceeded the context budget. "
                    "Do not replay the action. No partial API documentation is shown. "
                    + recovery
                    + " If this is API documentation, read all of it before further CUA actions."
                ),
            )
        return result


    async def _windows_note(self, app_id: str) -> str:
        """Report multiple windows; screenshot identity is tracked by the input bridge."""
        from deepseek_tui.cua.apps import open_windows

        windows = await asyncio.to_thread(open_windows, app_id)
        if windows is None or self.session.window_counts.get(app_id) == len(windows):
            return ""
        self.session.window_counts[app_id] = len(windows)
        return WINDOWS_NOTE.format(app=app_id, count=len(windows)) if len(windows) > 1 else ""


class CuaObserveTool(CuaTool):
    """A bounded observation path, independent of model-written JavaScript."""

    def __init__(self, session: CuaSession, cancel_events=None):
        super().__init__(session, {"name": "observe"}, cancel_events)

    def description(self) -> str:
        return (
            "Observe a native app or an existing browser tab without clicks or text input. "
            + ("Supply app (name/bundle id; an app that is not running is launched in the "
               "background)" if sys.platform == "darwin" else
               "Supply window_id (from the runtime inventory)")
            + ", or browser and tab_id from the runtime inventory. "
            "Returns full accessibility state and a screenshot through the same CUA runtime; "
            "existing access permissions apply. Use after actions to verify the expected "
            "change, when the user changes the interface, and before reporting a result. "
            "For text-verifiable changes, supply expect with exact visible text fragments "
            "that would show success; width, quote style, case and spacing are ignored. "
            "A missing fragment means not yet verified, not absent. "
            "While an app is loading or finishing an action, add wait_ms (up to 30000) "
            "instead of observing repeatedly: the host returns one fresh observation after "
            "that long, or as soon as every expect fragment appears. "
            "Works after a reset; does not restore old JavaScript bindings."
        )

    def input_schema(self) -> dict[str, Any]:
        # Only the form this platform's runtime accepts for a native target.
        native = ({"app": {"type": "string", "minLength": 1}} if sys.platform == "darwin"
                  else {"window_id": {"type": "integer", "minimum": 0}})
        return {"type": "object", "properties": {
            **native,
            "browser": {"type": "string", "minLength": 1},
            "tab_id": {"type": "string", "minLength": 1},
            "expect": {"type": "array", "maxItems": 8,
                       "items": {"type": "string", "minLength": 1}},
            "wait_ms": {"type": "integer", "minimum": 0, "maximum": MAX_WAIT_MS},
        }, "additionalProperties": False,
            "oneOf": [{"required": list(native)}, {"required": ["browser", "tab_id"]}]}

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        target = {k: v for k, v in input_data.items() if k not in {"expect", "wait_ms"}}
        expected = input_data.get("expect", [])
        wait_ms = input_data.get("wait_ms", 0)
        if type(wait_ms) is not int or not 0 <= wait_ms <= MAX_WAIT_MS:
            raise ToolError(f"wait_ms must be a whole number from 0 to {MAX_WAIT_MS}.")
        window = target.get("window_id")
        if (set(target) not in ({"app"}, {"window_id"}, {"browser", "tab_id"})
                or (set(target) == {"window_id"}
                    and (type(window) is not int or window < 0))
                or any(not isinstance(v, str) or not v.strip() or len(v) > 2048
                       for k, v in target.items() if k != "window_id")
                or not isinstance(expected, list) or len(expected) > 8
                or any(not isinstance(v, str) or not v.strip() or len(v) > 2048 for v in expected)):
            raise ToolError(
                "Supply app, window_id, or browser and tab_id; no code or other fields.")
        waited = 0.0
        if wait_ms and not expected:
            # Nothing to watch for: let the app settle, then observe once.
            await asyncio.sleep(wait_ms / 1000)
            waited = wait_ms / 1000
        result = await super().execute(input_data, context)
        checks = result.metadata.get("cua_observation", {}).get("expectations", [])
        if wait_ms and expected and result.success and not all(c["matched"] for c in checks):
            started = time.monotonic()
            await self._wait_for(target, expected, started + wait_ms / 1000, context)
            waited = time.monotonic() - started
            # Preserve the warning already settled by the first observation.
            unknown_note = result.metadata.get("unknown_outcome_note")
            # One fresh observation after the wait, whatever the polls saw.
            result = await super().execute(input_data, context)
            if unknown_note:
                result = replace(result, content=result.content + "\n" + unknown_note)
            checks = result.metadata.get("cua_observation", {}).get("expectations", [])
            result = replace(result, content=result.content
                             + f"\nWaited {waited:.1f}s for the expected text.")
        if wait_ms:
            result = _with_stats(result, waited_ms=round(waited * 1000))
            if expected:
                result = _with_stats(result, expect_met=all(c["matched"] for c in checks))
        if checks:
            summary = "\n".join(
                ("Observed: " if check["matched"] else "Not verified: ") + check["text"]
                for check in checks)
            result = replace(result, content=result.content + "\nExpected text checks:\n" + summary)
        return result

    async def _wait_for(
        self, target: dict[str, Any], expected: list[str], deadline: float, context: ToolContext,
    ) -> None:
        """Poll accessibility text only, so a wait costs no screenshots or model calls."""
        turn, call_id = _call_ids(context)
        while (remaining := deadline - time.monotonic()) > 0:
            await asyncio.sleep(min(WAIT_POLL_SECONDS, remaining))
            payload = await self.session.run(
                lambda: self.session.call("observe", {**target, "poll": True}, turn,
                                          f"{call_id}:poll"),
                self.cancel_events,
            )
            text = str((payload.get("observation") or {}).get("text", ""))
            if payload.get("isError") or all(text_observed(text, e) for e in expected):
                return


_BUTTONS = ("left", "right", "middle")
_DIRECTIONS = ("up", "down", "left", "right")
MAX_ACTIONS = 20


def _number(value: Any) -> bool:
    return type(value) in (int, float)


def _element(action: dict[str, Any], kind: str) -> int:
    element = action.get("element")
    if type(element) is not int or element < 0:
        raise ToolError(f"{kind} needs element: an index from the app's latest state.")
    return element


def _place(action: dict[str, Any], kind: str) -> str:
    """An element index, or a point when the action gives x and y instead."""
    if action.get("element") is None and _number(action.get("x")) and _number(action.get("y")):
        return json.dumps([action["x"], action["y"]])
    if action.get("element") is None:
        raise ToolError(f"{kind} needs element (an index from the latest state) or x and y.")
    return str(_element(action, kind))


def _string(action: dict[str, Any], kind: str, field: str, *, empty: bool = False) -> str:
    value = action.get(field)
    if not isinstance(value, str) or not (value or empty):
        raise ToolError(f"{kind} needs {field}.")
    return json.dumps(value)


def action_js(action: Any, mac: bool) -> str:
    """One typed step as the runtime's documented call on the bound app."""
    kind = action.get("type") if isinstance(action, dict) else None
    if kind == "click":
        options: dict[str, Any] = {}
        if action.get("button") not in (None, "left"):
            if action["button"] not in _BUTTONS:
                raise ToolError("click button is left, right or middle.")
            options["mouseButton"] = action["button"]
        if action.get("count") not in (None, 1):
            if type(action["count"]) is not int or not 1 <= action["count"] <= 3:
                raise ToolError("click count is 1, 2 or 3.")
            options["clickCount"] = action["count"]
        extra = ", " + json.dumps(options) if options else ""
        return f"await app.click({_place(action, kind)}{extra});"
    if kind == "type":
        return f"await app.typeText({_string(action, kind, 'text')});"
    if kind == "paste":
        return f"await app.paste({_string(action, kind, 'text')});"
    if kind == "key":
        return f"await app.pressKey({_string(action, kind, 'key')});"
    if kind == "scroll":
        if action.get("direction") not in _DIRECTIONS:
            raise ToolError("scroll needs direction: up, down, left or right.")
        pages = action.get("pages")
        if pages is not None and (not mac or not _number(pages) or pages <= 0):
            raise ToolError("scroll pages is a positive number, on macOS only.")
        return (f"await app.scroll({_place(action, kind)}, {json.dumps(action['direction'])}"
                f"{'' if pages is None else ', ' + json.dumps(pages)});")
    if kind == "drag":
        if not all(_number(action.get(k)) for k in ("x", "y", "to_x", "to_y")):
            raise ToolError("drag needs x, y, to_x and to_y.")
        return (f"await app.drag({json.dumps([action['x'], action['y']])}, "
                f"{json.dumps([action['to_x'], action['to_y']])});")
    if kind == "secondary_action":
        return (f"await app.performSecondaryAction({_element(action, kind)}, "
                f"{_string(action, kind, 'name')});")
    if mac and kind == "set_value":
        return (f"await app.setValue({_element(action, kind)}, "
                f"{_string(action, kind, 'text', empty=True)});")
    if mac and kind == "select_text":
        return f"await app.selectText({_element(action, kind)}, {_string(action, kind, 'text')});"
    raise ToolError(f"Unknown action type {kind!r}. Use one of: {', '.join(action_types(mac))}.")


def action_types(mac: bool) -> list[str]:
    # The runtime offers setValue and selectText on macOS only.
    return (["click", "type", "key", "paste", "scroll", "drag", "secondary_action"]
            + (["set_value", "select_text"] if mac else []))


def actions_code(
    entry: str, key: str, steps: list[str], screenshot: bool, *, refresh: bool = False,
) -> str:
    """Host-written code: bind the app once per REPL, run the steps, read the state."""
    slot = f"globalThis.__deepseekActs[{json.dumps(key)}]"
    return "\n".join([
        "{",
        "globalThis.__deepseekActs ??= {};",
        "let step = 0;",
        "let app;",
        "try {",
        f"app = {slot} ??= await {entry};",
        # Switching to a desktop-wide lease ends the runtime's previous app control.
        *(["await app.getAXState();"] if refresh else []),
        *(f"step = {number}; {step}" for number, step in enumerate(steps, 1)),
        "} catch (error) {",
        'if (step && typeof error?.message === "string") error.message += '
        f'"\\n[Action " + step + " of {len(steps)} failed; the actions after it did not run.]";',
        "throw error;",
        "}",
        # A closed app or window must not stay cached.
        f"try {{ await app.{'getAXStateAndScreenshot' if screenshot else 'getAXState'}(); }} "
        f"catch (error) {{ delete {slot}; throw error; }}",
        "}",
    ])


class CuaActTool(CuaTool):
    """The runtime's documented app actions as typed steps, so no code has to be written."""

    def __init__(self, session: CuaSession, cancel_events=None):
        super().__init__(session, {"name": "js"}, cancel_events)

    def name(self) -> str:
        return "cua_act"

    def description(self) -> str:
        mac = sys.platform == "darwin"
        return (
            "Operate one native app with typed steps instead of code. The host runs the steps "
            "in order through the same CUA runtime and returns the app's accessibility state "
            "afterwards (a diff when little changed); existing access permissions apply. "
            + ("Supply app (name/bundle id; an app that is not running is launched in the "
               "background)" if mac else "Supply window_id (from the runtime inventory)")
            + " and actions. An element is an index from the latest state shown for that app "
            "(the previous cua_act result or cua_observe); use x and y only for a target the "
            "state does not list: they are pixels of that app's latest screenshot. key takes "
            "xdotool-style names such as \"Return\", \"Tab\" and \"super+c\""
            + (" (super is Command)" if mac else "") + ". When a step fails, "
            "the steps after it do not run. Set screenshot to get an image with the state. "
            "Browser tabs, and logic these steps cannot express, go through cua_js."
        )

    def input_schema(self) -> dict[str, Any]:
        mac = sys.platform == "darwin"
        native = ({"app": {"type": "string", "minLength": 1}} if mac
                  else {"window_id": {"type": "integer", "minimum": 0}})
        number = {"type": "number"}
        step = {
            "type": {"type": "string", "enum": action_types(mac)},
            "element": {"type": "integer", "minimum": 0,
                        "description": "Index from the latest state. click and scroll take "
                                       "this or x and y."},
            "x": {**number, "description": "Pixels of this app's latest screenshot, from its "
                                            "top-left corner."},
            "y": number,
            "to_x": {**number, "description": "drag: where the drag ends, in the same "
                                               "screenshot's pixels."},
            "to_y": number,
            "text": {"type": "string",
                     "description": "type, paste" + (", set_value, select_text" if mac else "")},
            "key": {"type": "string", "description": "key: the key or chord to press."},
            "direction": {"type": "string", "enum": list(_DIRECTIONS)},
            "button": {"type": "string", "enum": list(_BUTTONS)},
            "count": {"type": "integer", "minimum": 1, "maximum": 3,
                      "description": "click: 2 for a double click."},
            "name": {"type": "string",
                     "description": "secondary_action: an action the element lists."},
        }
        if mac:
            step["pages"] = {**number, "description": "scroll: how many pages."}
        return {"type": "object", "properties": {
            **native,
            "actions": {"type": "array", "minItems": 1, "maxItems": MAX_ACTIONS, "items": {
                "type": "object", "properties": step, "required": ["type"],
                "additionalProperties": False}},
            "screenshot": {"type": "boolean"},
            "title": {"type": "string", "description": "The step, in the user's words."},
        }, "required": [*native, "actions"], "additionalProperties": False}

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        mac = sys.platform == "darwin"
        actions = input_data.get("actions")
        if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
            raise ToolError(f"Supply actions: 1 to {MAX_ACTIONS} steps.")
        steps = [action_js(action, mac) for action in actions]
        scope = None
        exclusive = False
        if mac:
            name = input_data.get("app")
            if not isinstance(name, str) or not name.strip():
                raise ToolError("Supply app: the app's name or bundle id.")
            # The installed app's own id scopes the desktop hold to that app; an unknown
            # name is left to the runtime and holds the whole desktop.
            scope = await asyncio.to_thread(app_scope.native_app, name)
            key = scope or name
            # Match cua_js: system shortcuts need exclusive desktop access.
            if any(action["type"] == "key" and not app_scope.js_scope(
                    step, {"app": key})[0] for action, step in zip(actions, steps)):
                exclusive = True
            entry = f"cua.getApp({json.dumps(key)})"
        else:
            window = input_data.get("window_id")
            if type(window) is not int or window < 0:
                raise ToolError("Supply window_id from the runtime inventory.")
            key, entry = f"window:{window}", f"cua.getApp({{windowId: {window}}})"
        call = {"code": actions_code(
            entry, key, steps, input_data.get("screenshot") is True,
            refresh=mac and (exclusive or scope is None))}
        if isinstance(input_data.get("title"), str) and input_data["title"].strip():
            call["title"] = input_data["title"]
        return await super().execute(call, context, scope=scope, exclusive=exclusive)


def register_tools(
    registry: Any, session: CuaSession, cancel_events: list[asyncio.Event] | None = None
) -> None:
    for descriptor in session.descriptors:
        name = "cua_" + descriptor["name"]
        if registry.contains(name):
            existing = registry.get(name)
            if (
                isinstance(existing, CuaTool)
                and existing.session is session
                and existing.descriptor == descriptor
            ):
                continue
        registry.register(CuaTool(session, descriptor, cancel_events))
    for name, host_tool in (("cua_observe", CuaObserveTool), ("cua_act", CuaActTool)):
        existing = registry.get(name) if registry.contains(name) else None
        if not isinstance(existing, host_tool) or existing.session is not session:
            registry.register(host_tool(session, cancel_events))
