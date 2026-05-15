"""Main TUI application — mirrors Rust ``tui/app.rs`` + ``tui/ui.rs``.

Stage 6.1: Wire Engine ↔ TUI so the app can actually send/receive messages.
Stage 6.5: Slash command activation — SlashMenu in compose tree,
           dispatch on ``/command`` input.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header

from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.models import Config
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ErrorEvent,
    SandboxDeniedEvent,
    StatusEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.ops import SendMessageOp
from deepseek_tui.tui.backtrack import BacktrackState, EscEffect
from deepseek_tui.tui.commands import dispatch
from deepseek_tui.tui.widgets.command_palette import CommandPalette
from deepseek_tui.tui.widgets.composer import Composer, ComposerHint
from deepseek_tui.tui.widgets.file_mention import FileMention
from deepseek_tui.tui.widgets.help_panel import HelpPanel
from deepseek_tui.tui.widgets.info_sidebar import InfoSidebar, InfoSidebarData
from deepseek_tui.tui.widgets.sidebar import Sidebar
from deepseek_tui.tui.widgets.slash_menu import SlashMenu
from deepseek_tui.tui.widgets.status_bar import StatusBar
from deepseek_tui.tui.widgets.transcript import Transcript

if TYPE_CHECKING:
    from deepseek_tui.engine.engine import Engine

logger = logging.getLogger(__name__)


def _json_decode_error() -> type[Exception]:
    """Lazy import to keep top-level imports cheap."""
    import json as _json

    return _json.JSONDecodeError


class DeepSeekTUI(App[None]):
    """Main TUI application."""

    TITLE = "DeepSeek TUI"
    # Composer chrome (2026-05-11 polish pass v2): the composer is the
    # primary interaction surface, so it gets a full rounded border and
    # is bumped from 3 → 5 rows (one for each border + 3 for text). The
    # ``margin-bottom: 1`` carves a blank row between it and the
    # ``KeyHints`` strip so the muted chip row reads as separate chrome
    # rather than a continuation of the input.
    CSS = """
    Composer {
        dock: bottom;
        height: auto;
        min-height: 5;
        max-height: 12;
        border: round $accent;
        margin: 0 1 1 1;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+n", "new_session", "New Session"),
        Binding("ctrl+k", "command_palette", "Command Palette"),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar"),
        Binding("escape", "esc_press", "Backtrack", show=False),
        Binding("f1", "show_help", "Help", show=False),
        # Rust-parity bindings (subset). Full Rust catalog has 40+ chords;
        # this batch covers the highest-traffic ones — pickers, mode cycle,
        # transcript scroll. Remaining Rust bindings are documented in the
        #集成债 list as Stage 6 follow-up.
        Binding("ctrl+r", "open_session_picker", "Sessions"),
        Binding("ctrl+o", "open_model_picker", "Models"),
        Binding("ctrl+p", "open_file_picker", "Files"),
        Binding("ctrl+i", "toggle_info_sidebar", "Info", show=False),
        Binding("ctrl+l", "clear_transcript", "Clear", show=False),
        Binding("pageup", "transcript_page_up", "PageUp", show=False),
        Binding("pagedown", "transcript_page_down", "PageDown", show=False),
        Binding("ctrl+t", "toggle_thinking", "Thinking", show=False),
    ]

    def __init__(
        self,
        handle: EngineHandle | None = None,
        config: Config | None = None,
        resume_session_id: str | None = None,
        fork_session_id: str | None = None,
    ) -> None:
        super().__init__()
        self.config = config or Config()
        self.handle = handle or EngineHandle()
        self._engine: Engine | None = None
        self._engine_task: asyncio.Task[None] | None = None
        self._interaction_mode: str = "agent"  # persisted across cycle_mode toggles
        self._resume_session_id = resume_session_id
        self._fork_session_id = fork_session_id
        self._turn_started_at: float | None = None
        self._backtrack = BacktrackState()
        # ISO-8601 UTC timestamp captured at engine boot; the right
        # info-sidebar uses it to filter ``TaskManager.list_tasks`` so
        # the panel only surfaces tasks born this session — stale
        # ``failed`` records from prior runs no longer clutter the view.
        self._session_started_at_iso: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Sidebar()
        yield InfoSidebar()
        yield Transcript()
        yield SlashMenu()
        yield FileMention()
        yield ComposerHint()
        yield Composer()
        yield StatusBar()

    async def on_mount(self) -> None:
        logger.info(
            "tui_on_mount resume=%s fork=%s",
            self._resume_session_id,
            self._fork_session_id,
        )
        # Ensure bundled system skills exist before any skill discovery
        # runs (Engine.create reads ``default_skills_dir()`` via
        # ``discover_in_workspace``). Mirrors Rust ``main.rs:3974`` which
        # calls ``crate::skills::install_system_skills`` at startup.
        try:
            from deepseek_tui.skills.system import install_system_skills

            install_system_skills()
        except Exception:  # noqa: BLE001 — bundled-skill failure must
            # never block the TUI from launching.
            logger.exception("install_system_skills failed at startup")
        self.query_one(Composer).focus()
        # Seed StatusBar + ComposerHint with mode/model *before* the
        # engine starts so the bottom chrome already shows them (chord
        # chips and model name should be visible the instant the TUI
        # paints — not delayed behind ``Engine.create``).
        status = self.query_one(StatusBar)
        status.set_status("starting engine...")
        status.set_mode(self._interaction_mode)
        if self.config.model:
            status.set_model(self.config.model)
        elif self.config.default_text_model:
            status.set_model(self.config.default_text_model)
        hint = self.query_one(ComposerHint)
        hint.set_mode(self._interaction_mode)
        if self.config.model:
            hint.set_model(self.config.model)
        self.query_one(Transcript).show_thinking = bool(
            self.config.ui.show_thinking
        )
        # Run engine startup off the on_mount critical path so the UI
        # becomes interactive immediately. Engine.create can take several
        # seconds (MCP servers, skill discovery, tool runtime wiring); we
        # don't want keystrokes to queue up behind it.
        self.run_worker(self._start_engine(), exclusive=True, name="engine-start")

    async def _start_engine(self) -> None:
        """Build LLM client + Engine from config and start the engine loop.

        When no API key is configured, push the onboarding screen and
        retry once the user supplies one.
        """
        from datetime import datetime, timezone

        from deepseek_tui.engine.engine import Engine
        from deepseek_tui.tui.approval_handler import TUIApprovalHandler
        from deepseek_tui.tui.screens.onboarding import (
            OnboardingScreen,
            is_onboarded,
            mark_onboarded,
        )

        # Stamp the session start before any engine work — the info
        # sidebar filters tasks against this so historical failures
        # don't bleed into a fresh interaction.
        if self._session_started_at_iso is None:
            self._session_started_at_iso = datetime.now(timezone.utc).isoformat()

        client = self._build_client()
        if client is None:
            logger.warning("tui_no_api_key onboarding=%s", not is_onboarded())
            self.query_one(StatusBar).set_status(
                "no API key — run `deepseek-tui setup` or `deepseek-tui login`"
            )
            if not is_onboarded():
                def _on_onboarding(api_key: str | None) -> None:
                    if api_key:
                        self.config.api_key = api_key
                        try:
                            mark_onboarded()
                        except OSError:
                            pass
                        self.run_worker(self._start_engine(), exclusive=True)

                self.push_screen(OnboardingScreen(), _on_onboarding)
            return

        model = self.config.model or self.config.default_text_model
        approval_handler = TUIApprovalHandler(self)
        logger.info("tui_engine_create model=%s", model)
        self._engine = await Engine.create(
            self.handle,
            client,
            config=self.config,
            default_model=model,
            approval_handler=approval_handler,
        )
        self._engine_task = asyncio.create_task(self._engine.run())
        logger.info("tui_engine_started")
        status = self.query_one(StatusBar)
        status.set_model(model)
        status.set_mode("agent")
        self.query_one(ComposerHint).set_model(model)
        # Apply --resume / --fork before announcing ready so the user sees
        # the restored transcript rather than a blank screen. Errors here
        # are non-fatal: status bar surfaces them and the user can keep
        # going with an empty session.
        applied = self._apply_resume_or_fork()
        if applied is None:
            status.set_status("ready")
        else:
            status.set_status(applied)

    def _apply_resume_or_fork(self) -> str | None:
        """Restore session messages from disk if a resume/fork id was given.

        Returns a status-bar message (or ``None`` if nothing to do).
        Sessions are read from ``~/.deepseek/sessions/<id>.json``; the
        special id ``current``/``latest`` maps to the auto-persisted
        ``current.json`` snapshot. Mirrors Rust ``run_interactive``'s
        resume path which also feeds ``SessionManager::load_session``
        output back into the engine before the first user input.
        """
        if self._engine is None:
            return None
        target_id = self._resume_session_id or self._fork_session_id
        if not target_id:
            return None
        path = self._resolve_session_path(target_id)
        if path is None or not path.exists():
            return f"resume target not found: {target_id}"
        try:
            import json as _json

            data = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, _json_decode_error()) as exc:
            return f"failed to read session: {exc}"
        messages_raw = data.get("messages", [])
        if not isinstance(messages_raw, list):
            return "session file has no messages"
        from deepseek_tui.protocol.messages import Message

        try:
            restored = [Message.model_validate(m) for m in messages_raw]
        except Exception as exc:  # noqa: BLE001 — pydantic validation errors
            return f"session file invalid: {exc}"
        self._engine.session_messages.clear()
        self._engine.session_messages.extend(restored)
        transcript = self.query_one(Transcript)
        transcript.clear_messages()
        for msg in restored:
            text_parts = [
                getattr(b, "text", "")
                for b in msg.content
                if getattr(b, "type", None) == "text"
            ]
            text = " ".join(p for p in text_parts if p)
            if not text:
                continue
            if msg.role == "user":
                transcript.add_user_message(text)
            elif msg.role == "assistant":
                # Transcript has no single "add assistant message" — synthesize
                # from the streaming primitives so the cell looks identical to
                # a freshly-streamed turn.
                transcript.start_assistant_message()
                transcript.append_delta(text)
                transcript.finalize_message()
        verb = "resumed" if self._resume_session_id else "forked from"
        return f"{verb} {target_id[:8]} ({len(restored)} messages)"

    @staticmethod
    def _resolve_session_path(session_id: str):  # type: ignore[no-untyped-def]
        """Map a session id to a JSON path under ``~/.deepseek/sessions``."""
        from pathlib import Path

        from deepseek_tui.config.paths import user_sessions_dir

        sessions_dir = user_sessions_dir()
        if session_id in {"current", "latest"}:
            return sessions_dir / "current.json"
        absolute = Path(session_id).expanduser()
        if absolute.is_absolute() and absolute.exists():
            return absolute
        return sessions_dir / f"{session_id}.json"

    def _build_client(self) -> LLMClient | None:
        """Construct an LLM client from config + secrets."""
        from deepseek_tui.client.deepseek import DeepSeekClient
        from deepseek_tui.secrets.manager import SecretsManager

        mgr = SecretsManager()
        api_key = mgr.resolve_api_key(self.config)
        if not api_key:
            return None

        pc = self.config.effective_provider_config()
        base_url = pc.base_url or "https://api.deepseek.com"
        return DeepSeekClient(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=float(pc.timeout),
        )

    # ── message submission ────────────────────────────────────────────

    async def on_composer_submitted(self, event: Composer.Submitted) -> None:
        if self._engine is None:
            logger.warning("composer_submit_no_engine")
            self.query_one(StatusBar).set_status(
                "no engine — configure API key first"
            )
            return
        preview = (event.text or "")[:200].replace("\n", " ")
        # Prepend active mode so Engine adapts behaviour (plan/yolo/ask vs agent).
        content = event.text
        if self._interaction_mode != "agent":
            content = f"[mode:{self._interaction_mode}] {content}"
        transcript = self.query_one(Transcript)
        if self.handle.is_turn_active():
            # Soft steer: Engine is mid-turn, so don't queue a new
            # SendMessageOp (which would fight for op-queue ordering).
            # Engine drains ``handle._steer_queue`` at the top of its
            # next round and appends each entry as a user message,
            # which is exactly the behaviour we want here.
            logger.info(
                "composer_submit text_len=%d preview=%r mode=steer",
                len(event.text or ""),
                preview,
            )
            transcript.add_user_message(event.text, queued=True)
            await self.handle.steer(content)
            return
        logger.info(
            "composer_submit text_len=%d preview=%r mode=send",
            len(event.text or ""),
            preview,
        )
        transcript.add_user_message(event.text)
        await self.handle.send_op(SendMessageOp(content=content))
        self.run_worker(self._listen_events())

    # ── slash command handling ────────────────────────────────────────

    def on_composer_slash_input(self, event: Composer.SlashInput) -> None:
        """Dispatch a slash command and display the result."""
        self.query_one(SlashMenu).hide()
        result = dispatch(event.raw_input, self)
        transcript = self.query_one(Transcript)
        if result.output:
            transcript.add_notice(result.output, severity="info")
        if result.error:
            transcript.add_notice(result.error, severity="error")
        if result.exit_app:
            self.exit()

    def on_composer_text_changed(self, event: Composer.TextChanged) -> None:
        """Show/hide slash menu or file mention based on input prefix."""
        text = event.text.strip()
        slash_menu = self.query_one(SlashMenu)
        file_mention = self.query_one(FileMention)
        if text.startswith("/"):
            slash_menu.show(filter_text=text)
            file_mention.hide()
        elif "@" in text:
            at_pos = text.rfind("@")
            after_at = text[at_pos + 1:]
            file_mention.show(prefix=after_at)
            slash_menu.hide()
        else:
            slash_menu.hide()
            file_mention.hide()

    def on_slash_menu_selected(self, event: SlashMenu.Selected) -> None:
        """Fill composer with selected slash command."""
        composer = self.query_one(Composer)
        composer.clear()
        composer.insert(event.command + " ")
        self.query_one(SlashMenu).hide()
        composer.focus()

    def on_file_mention_selected(self, event: FileMention.Selected) -> None:
        """Insert selected file path into composer."""
        composer = self.query_one(Composer)
        current = composer.text
        at_pos = current.rfind("@")
        if at_pos >= 0:
            new_text = current[:at_pos] + f"@{event.path} "
            composer.clear()
            composer.insert(new_text)
        self.query_one(FileMention).hide()
        composer.focus()

    # ── engine event loop ─────────────────────────────────────────────

    async def _listen_events(self) -> None:
        """Consume engine events and route to UI widgets."""
        transcript = self.query_one(Transcript)
        status = self.query_one(StatusBar)
        async for event in self.handle.events():
            if isinstance(event, TurnStartedEvent):
                self._turn_started_at = time.monotonic()
                status.set_status("thinking...")
                status.set_started(self._turn_started_at)
                # Refresh the thinking-visibility flag every turn so the
                # Ctrl+T toggle takes effect at the next finalize.
                transcript.show_thinking = bool(self.config.ui.show_thinking)
                transcript.start_assistant_message()
            elif isinstance(event, TextDeltaEvent):
                transcript.append_delta(event.text)
            elif isinstance(event, ThinkingDeltaEvent):
                transcript.append_thinking(event.thinking)
            elif isinstance(event, ToolCallEvent):
                tc = event.tool_call
                transcript.add_tool_call(tc.id, tc.name, tc.arguments)
                status.set_status(f"running {tc.name}...")
            elif isinstance(event, ToolResultEvent):
                transcript.update_tool_result(
                    event.tool_call_id, event.content, event.success
                )
            elif isinstance(event, ApprovalRequiredEvent):
                # The modal dialog IS the notification — surfacing an
                # extra "Approval required for X" notice on top of every
                # tool call clogged the transcript and hid the actual
                # tool result. Drive the tool cell's header instead.
                status.set_status(
                    f"awaiting approval: {event.request.tool_name}"
                )
                transcript.mark_tool_awaiting_approval(event.tool_call_id)
            elif isinstance(event, ApprovalResolvedEvent):
                label = "approved" if event.approved else "denied"
                status.set_status(f"tool {label}")
                if event.approved:
                    transcript.mark_tool_approved(event.tool_call_id)
                else:
                    transcript.mark_tool_denied(
                        event.tool_call_id, event.reason
                    )
            elif isinstance(event, SandboxDeniedEvent):
                # Sandbox denial happens INSTEAD of tool execution — no
                # ToolResultEvent ever fires for this call. Mark the
                # cell denied so it doesn't stay stuck at "running".
                transcript.mark_tool_denied(event.tool_call_id, event.reason)
                status.set_status(
                    f"sandbox denied: {event.tool_name}"
                )
            elif isinstance(event, UserInputRequiredEvent):
                status.set_status("awaiting user input...")
                self._handle_user_input_event(event, transcript)
            elif isinstance(event, ErrorEvent):
                transcript.add_notice(event.message, severity="error")
                status.set_status("error")
            elif isinstance(event, TurnCancelledEvent):
                status.set_status("cancelled")
                status.set_finished()
                transcript.finalize_message()
                break
            elif isinstance(event, TurnCompleteEvent):
                status.set_status("ready")
                status.set_finished()
                if event.usage is not None:
                    status.set_tokens(
                        event.usage.input_tokens + event.usage.output_tokens
                    )
                # Cost + cache chips are populated only when the event
                # actually carries them (off-platform providers leave
                # cost None so the chip stays hidden).
                if event.session_cost_usd is not None:
                    status.set_cost(
                        event.session_cost_usd,
                        event.session_cost_cny or 0.0,
                    )
                if event.cache_hit_tokens or event.cache_miss_tokens:
                    status.set_cache(
                        event.cache_hit_tokens, event.cache_miss_tokens
                    )
                transcript.finalize_message()
                await self._refresh_info_sidebar()
                self._maybe_notify_turn_done()
                break
            elif isinstance(event, StatusEvent):
                status.set_status(event.message)
            # Refresh the right info-sidebar opportunistically on the
            # high-traffic events that mutate its data (tool results
            # alter todos/tasks/agents). Refresh is cheap (three list
            # reads + format) so debouncing is not needed yet.
            if isinstance(event, ToolResultEvent):
                await self._refresh_info_sidebar()

    # ── user input handling ─────────────────────────────────────────

    def _handle_user_input_event(
        self, event: UserInputRequiredEvent, transcript: Transcript
    ) -> None:
        """Display questions and resolve with first option (auto-select).

        A full interactive picker can be added later; for now this
        unblocks the Engine so it never deadlocks.
        """
        response: dict[str, object] = {}
        for q in event.questions:
            qid = q.get("id", "")
            question = q.get("question", "")
            options = q.get("options", [])
            option_labels = [
                o.get("label", "?") if isinstance(o, dict) else str(o)
                for o in (options if isinstance(options, list) else [])
            ]
            display = f"Question: {question}\nOptions: {', '.join(option_labels)}"
            transcript.add_notice(display, severity="info")
            if option_labels:
                response[str(qid)] = option_labels[0]
                transcript.add_notice(
                    f"Auto-selected: {option_labels[0]}",
                    severity="info",
                )

        self.handle.resolve_user_input(event.tool_call_id, response)

    # ── actions ───────────────────────────────────────────────────────

    def action_command_palette(self) -> None:
        """Open the Ctrl+K command palette."""

        def _on_result(result: str | None) -> None:
            if result:
                cmd_result = dispatch(result, self)
                transcript = self.query_one(Transcript)
                if cmd_result.output:
                    transcript.add_notice(cmd_result.output, severity="info")
                if cmd_result.error:
                    transcript.add_notice(cmd_result.error, severity="error")
                if cmd_result.exit_app:
                    self.exit()

        self.push_screen(CommandPalette(), _on_result)

    def action_new_session(self) -> None:
        transcript = self.query_one(Transcript)
        transcript.clear_messages()
        if self._engine is not None:
            self._engine.session_messages.clear()

    async def action_quit(self) -> None:
        logger.info("tui_quit")
        if self._engine is not None:
            await self._engine.shutdown()
        if self._engine_task is not None:
            self._engine_task.cancel()
        self.exit()

    def action_toggle_sidebar(self) -> None:
        self.query_one(Sidebar).toggle()

    def action_toggle_info_sidebar(self) -> None:
        """Toggle the right-side Todos / Tasks / Agents panel (Ctrl+I)."""
        try:
            self.query_one(InfoSidebar).toggle()
        except Exception:
            pass

    def action_show_help(self) -> None:
        self.push_screen(HelpPanel())

    # ── Rust-parity action stubs (subset) ────────────────────────────

    def action_open_session_picker(self) -> None:
        """Open the session picker (Ctrl+R, Rust ``Ctrl+R``).

        Sessions are loaded from ``~/.deepseek/sessions/*.json``; selection
        triggers the same restore path used by ``--resume``. Empty list
        falls back to the auto-saved ``current.json`` when present.
        """
        from deepseek_tui.tui.widgets.pickers import SessionPicker

        sessions = self._discover_session_picks()
        if not sessions:
            self.query_one(StatusBar).set_status(
                "no saved sessions in ~/.deepseek/sessions/"
            )
            return

        def _on_pick(picked: str | None) -> None:
            if picked:
                self._resume_session_id = picked
                self._fork_session_id = None
                applied = self._apply_resume_or_fork()
                if applied:
                    self.query_one(StatusBar).set_status(applied)

        self.push_screen(SessionPicker(sessions=sessions), _on_pick)

    def action_open_model_picker(self) -> None:
        """Open the model picker (Ctrl+M, Rust ``Ctrl+M``)."""
        from deepseek_tui.tui.widgets.pickers import ModelPicker

        def _on_pick(picked: str | None) -> None:
            if not picked or self._engine is None:
                return
            self._engine.default_model = picked
            self.config.model = picked
            self.query_one(StatusBar).set_model(picked)
            self.query_one(ComposerHint).set_model(picked)

        self.push_screen(ModelPicker(), _on_pick)

    def action_open_file_picker(self) -> None:
        """Open the workspace file picker (Ctrl+P, Rust ``Ctrl+P``).

        On selection, prepends the path to the composer as ``@path``.
        """
        from deepseek_tui.tui.widgets.pickers import FilePicker

        def _on_pick(picked: str | None) -> None:
            if not picked:
                return
            composer = self.query_one(Composer)
            current = composer.text
            composer.clear()
            composer.insert(f"{current}@{picked} ".lstrip())
            composer.focus()

        self.push_screen(FilePicker(), _on_pick)

    def action_cycle_mode(self) -> None:
        """Cycle agent/plan/yolo/ask modes (Tab, Rust ``Tab``)."""
        modes = ("agent", "plan", "yolo", "ask")
        current = self.query_one(StatusBar)._mode or "agent"
        try:
            idx = modes.index(current)
        except ValueError:
            idx = 0
        next_mode = modes[(idx + 1) % len(modes)]
        self._interaction_mode = next_mode
        self.query_one(StatusBar).set_mode(next_mode)
        self.query_one(ComposerHint).set_mode(next_mode)

    def action_clear_transcript(self) -> None:
        """Clear visible transcript without resetting engine session.

        Rust ``Ctrl+L`` clears the screen; ``Ctrl+N`` is the full new-session
        chord. Keeping these distinct mirrors that split.
        """
        self.query_one(Transcript).clear_messages()

    def action_transcript_page_up(self) -> None:
        try:
            self.query_one(Transcript).scroll_page_up(animate=False)
        except Exception:  # noqa: BLE001 — Textual scroll is best-effort
            pass

    def action_transcript_page_down(self) -> None:
        try:
            self.query_one(Transcript).scroll_page_down(animate=False)
        except Exception:  # noqa: BLE001
            pass

    def action_toggle_thinking(self) -> None:
        """Toggle ``ui.show_thinking`` (Ctrl+T, Rust ``Ctrl+T``).

        The transcript reads the flag at the start of each turn and on
        ``finalize_message``; live deltas always render so the user can
        see what's happening *during* a turn, and the collapse/drop
        decision is taken once the turn ends.
        """
        self.config.ui.show_thinking = not self.config.ui.show_thinking
        state = "on" if self.config.ui.show_thinking else "off"
        transcript = self.query_one(Transcript)
        transcript.show_thinking = bool(self.config.ui.show_thinking)
        self.query_one(StatusBar).set_status(f"thinking {state}")

    @staticmethod
    def _discover_session_picks() -> list[tuple[str, str]]:
        """Read ``~/.deepseek/sessions/*.json`` into picker tuples."""
        from deepseek_tui.config.paths import user_sessions_dir

        sessions_dir = user_sessions_dir()
        if not sessions_dir.exists():
            return []
        items: list[tuple[str, str]] = []
        for path in sorted(sessions_dir.glob("*.json")):
            stem = path.stem
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            label = f"{stem} ({size:,}B)"
            items.append((stem, label))
        return items

    def action_esc_press(self) -> None:
        """Esc-Esc backtrack chord (mirrors Rust ``backtrack.rs``).

        First Esc primes; second opens the picker. The picker shows up
        as a status-bar toast rather than a full overlay (which is logged
        as a known simplification in HANDOVER) — keeps the transcript
        clean of chord priming hints.
        """
        engine = self._engine
        total = (
            len([m for m in engine.session_messages if getattr(m, "role", None) == "user"])
            if engine is not None
            else 0
        )
        effect = self._backtrack.handle_esc(total)
        status = self.query_one(StatusBar)
        if effect == EscEffect.PRIME:
            status.set_status("Esc again to backtrack")
        elif effect == EscEffect.CANCEL:
            status.set_status("backtrack cancelled")
        elif effect == EscEffect.OPEN_OVERLAY:
            status.set_status(
                f"backtrack: {total} turn(s); depth={self._backtrack.selected_idx}"
            )

    def on_sidebar_session_selected(self, event: Sidebar.SessionSelected) -> None:
        """Handle session selection from sidebar."""
        self.query_one(StatusBar).set_status(
            f"switching to session {event.session_id[:8]}…"
        )
        self.query_one(Sidebar).hide_sidebar()

    # ── info sidebar refresh ──────────────────────────────────────────

    async def _refresh_info_sidebar(self) -> None:
        """Fetch live engine state and push it into the right info sidebar.

        Cheap to call: 3 list reads + format. ``ToolResultEvent`` and
        ``TurnCompleteEvent`` both invoke this so Todos/Tasks/Agents
        update without waiting for the next user turn.
        """
        if self._engine is None:
            return
        try:
            sidebar = self.query_one(InfoSidebar)
        except Exception:
            return

        # --- Todos: read from the in-memory store TodoWriteTool writes to.
        todos_raw = self._engine.tool_context.metadata.get("todos") or {}
        items_raw = todos_raw.get("items", []) if isinstance(todos_raw, dict) else []
        todo_items: list[dict[str, object]] = []
        completed = 0
        in_progress_id: int | None = None
        for item in items_raw:
            status = getattr(item, "status", "pending")
            content = getattr(item, "content", getattr(item, "text", ""))
            item_id = getattr(item, "id", "?")
            todo_items.append(
                {"id": item_id, "content": content, "status": status}
            )
            if status == "completed":
                completed += 1
            if status == "in_progress" and isinstance(item_id, str) and item_id.isdigit():
                in_progress_id = int(item_id)
        total = len(todo_items)
        pct = round(completed * 100 / total) if total else 0

        # --- Tasks: durable TaskManager snapshot, filtered to this
        # session so stale ``failed`` records from earlier runs don't
        # clutter a fresh interaction.
        tasks_data: list[dict[str, object]] = []
        manager = self._engine.tool_context.task_manager
        if manager is not None:
            try:
                summaries = await manager.list_tasks(
                    limit=5, since=self._session_started_at_iso
                )
            except Exception:
                summaries = []
            for s in summaries:
                tasks_data.append(
                    {
                        "id": s.id,
                        "status": (
                            s.status.value
                            if hasattr(s.status, "value")
                            else str(s.status)
                        ),
                        "prompt_summary": s.prompt_summary,
                        "duration_ms": s.duration_ms,
                        "created_at": s.created_at,
                    }
                )

        # --- Agents: SubAgentManager snapshot (newest 5).
        agents_data: list[dict[str, object]] = []
        sub_mgr = self._engine.tool_context.subagent_manager
        if sub_mgr is not None:
            try:
                snaps = sub_mgr.list_agents()
            except Exception:
                snaps = []
            for s in snaps[:5]:
                status_obj = getattr(s, "status", None)
                status_str = (
                    status_obj.kind.value
                    if status_obj is not None and hasattr(status_obj, "kind")
                    else str(status_obj or "?")
                )
                atype = getattr(s, "agent_type", None)
                atype_str = (
                    atype.value
                    if atype is not None and hasattr(atype, "value")
                    else str(atype or "?")
                )
                agents_data.append(
                    {
                        "agent_id": getattr(s, "agent_id", "?"),
                        "agent_type": atype_str,
                        "status": status_str,
                        "duration_ms": getattr(s, "duration_ms", None),
                    }
                )

        sidebar.update_data(
            InfoSidebarData(
                todos=todo_items,
                todos_completion_pct=pct,
                todos_in_progress_id=in_progress_id,
                tasks=tasks_data,
                agents=agents_data,
            )
        )

    # ── notifications ─────────────────────────────────────────────────

    def _maybe_notify_turn_done(self) -> None:
        """Emit OSC 9 / BEL when a long turn finishes (mirrors Rust notifications.rs).

        Method + threshold are read from the top-level ``[notifications]``
        section first (Rust parity), falling back to ``Config.ui.notify_*``
        when the nested fields are unset. ``notifications.enabled = false``
        suppresses the notification entirely.
        """
        import sys

        from deepseek_tui.tui.notifications import Method, notify_done_to

        started = self._turn_started_at
        self._turn_started_at = None
        if started is None:
            return
        elapsed = time.monotonic() - started

        notif = self.config.notifications
        if not notif.enabled:
            return
        ui = self.config.ui
        method_str = notif.method if notif.method is not None else ui.notify_method
        threshold_secs = float(
            notif.threshold_secs
            if notif.threshold_secs is not None
            else ui.notify_threshold_secs
        )
        method = Method.from_str(method_str)
        in_tmux = bool(os.environ.get("TMUX"))
        sink = getattr(sys.stdout, "buffer", None)
        if sink is None:
            return
        try:
            notify_done_to(method, in_tmux, "deepseek: done", threshold_secs, elapsed, sink)
        except (OSError, ValueError):
            return
