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
from textual.widgets import Footer, Header

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
from deepseek_tui.tui.widgets.composer import Composer
from deepseek_tui.tui.widgets.file_mention import FileMention
from deepseek_tui.tui.widgets.help_panel import HelpPanel
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
    CSS = """
    Composer {
        dock: bottom;
        height: auto;
        max-height: 10;
        padding: 0 1;
    }
    StatusBar {
        dock: bottom;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+n", "new_session", "New Session"),
        Binding("ctrl+k", "command_palette", "Command Palette"),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar"),
        Binding("escape", "esc_press", "Backtrack", show=False),
        Binding("question_mark", "show_help", "Help", show=False),
        # Rust-parity bindings (subset). Full Rust catalog has 40+ chords;
        # this batch covers the highest-traffic ones — pickers, mode cycle,
        # transcript scroll. Remaining Rust bindings are documented in the
        #集成债 list as Stage 6 follow-up.
        Binding("ctrl+r", "open_session_picker", "Sessions"),
        Binding("ctrl+m", "open_model_picker", "Models"),
        Binding("ctrl+p", "open_file_picker", "Files"),
        Binding("tab", "cycle_mode", "Cycle Mode", show=False),
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
        self._resume_session_id = resume_session_id
        self._fork_session_id = fork_session_id
        self._turn_started_at: float | None = None
        self._backtrack = BacktrackState()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Sidebar()
        yield Transcript()
        yield SlashMenu()
        yield FileMention()
        yield StatusBar()
        yield Composer()
        yield Footer()

    async def on_mount(self) -> None:
        logger.info(
            "tui_on_mount resume=%s fork=%s",
            self._resume_session_id,
            self._fork_session_id,
        )
        self.query_one(Composer).focus()
        await self._start_engine()

    async def _start_engine(self) -> None:
        """Build LLM client + Engine from config and start the engine loop.

        When no API key is configured, push the onboarding screen and
        retry once the user supplies one.
        """
        from deepseek_tui.engine.engine import Engine
        from deepseek_tui.tui.approval_handler import TUIApprovalHandler
        from deepseek_tui.tui.screens.onboarding import (
            OnboardingScreen,
            is_onboarded,
            mark_onboarded,
        )

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

        from deepseek_tui.config.paths import default_config_path

        sessions_dir = default_config_path().parent / "sessions"
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
            self.query_one(Transcript).add_system_message(
                "Engine not started. Please configure an API key first."
            )
            return
        preview = (event.text or "")[:200].replace("\n", " ")
        logger.info(
            "composer_submit text_len=%d preview=%r",
            len(event.text or ""),
            preview,
        )
        transcript = self.query_one(Transcript)
        transcript.add_user_message(event.text)
        await self.handle.send_op(SendMessageOp(content=event.text))
        self.run_worker(self._listen_events())

    # ── slash command handling ────────────────────────────────────────

    def on_composer_slash_input(self, event: Composer.SlashInput) -> None:
        """Dispatch a slash command and display the result."""
        self.query_one(SlashMenu).hide()
        result = dispatch(event.raw_input, self)
        transcript = self.query_one(Transcript)
        if result.output:
            transcript.add_system_message(result.output)
        if result.error:
            transcript.add_system_message(f"Error: {result.error}")
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
                status.set_status("awaiting approval...")
                transcript.add_system_message(
                    f"Approval required for tool: "
                    f"{event.request.tool_name} — {event.request.reason}"
                )
            elif isinstance(event, ApprovalResolvedEvent):
                label = "approved" if event.approved else "denied"
                transcript.add_system_message(
                    f"Tool {label}: {event.reason}"
                )
            elif isinstance(event, SandboxDeniedEvent):
                transcript.add_system_message(
                    f"Sandbox denied {event.tool_name}: {event.reason}"
                )
            elif isinstance(event, UserInputRequiredEvent):
                status.set_status("awaiting user input...")
                self._handle_user_input_event(event, transcript)
            elif isinstance(event, ErrorEvent):
                transcript.add_system_message(f"Error: {event.message}")
                status.set_status("error")
            elif isinstance(event, TurnCancelledEvent):
                status.set_status("cancelled")
                transcript.finalize_message()
                break
            elif isinstance(event, TurnCompleteEvent):
                status.set_status("ready")
                if event.usage is not None:
                    status.set_tokens(
                        event.usage.input_tokens + event.usage.output_tokens
                    )
                transcript.finalize_message()
                self._maybe_notify_turn_done()
                break
            elif isinstance(event, StatusEvent):
                status.set_status(event.message)

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
            transcript.add_system_message(display)
            if option_labels:
                response[str(qid)] = option_labels[0]
                transcript.add_system_message(
                    f"Auto-selected: {option_labels[0]}"
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
                    transcript.add_system_message(cmd_result.output)
                if cmd_result.error:
                    transcript.add_system_message(f"Error: {cmd_result.error}")
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
            self.query_one(Transcript).add_system_message(
                "No saved sessions found in ~/.deepseek/sessions/"
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
        self.query_one(StatusBar).set_mode(next_mode)
        self.query_one(Transcript).add_system_message(f"Mode: {next_mode}")

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

        Currently advisory: the transcript always shows thinking deltas.
        Wiring the toggle to actually hide them is documented as a Stage 6
        follow-up since the cell already streams via ``_ThinkingCell``.
        """
        self.config.ui.show_thinking = not self.config.ui.show_thinking
        state = "on" if self.config.ui.show_thinking else "off"
        self.query_one(Transcript).add_system_message(f"show_thinking={state}")

    @staticmethod
    def _discover_session_picks() -> list[tuple[str, str]]:
        """Read ``~/.deepseek/sessions/*.json`` into picker tuples."""
        from deepseek_tui.config.paths import default_config_path

        sessions_dir = default_config_path().parent / "sessions"
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
        as a system message rather than a full overlay (which is logged
        as a known simplification in HANDOVER).
        """
        engine = self._engine
        total = (
            len([m for m in engine.session_messages if getattr(m, "role", None) == "user"])
            if engine is not None
            else 0
        )
        effect = self._backtrack.handle_esc(total)
        transcript = self.query_one(Transcript)
        if effect == EscEffect.PRIME:
            transcript.add_system_message("Press Esc again to backtrack to a previous turn")
        elif effect == EscEffect.CANCEL:
            transcript.add_system_message("Backtrack cancelled")
        elif effect == EscEffect.OPEN_OVERLAY:
            transcript.add_system_message(
                f"Backtrack: {total} user turn(s). "
                f"Press Enter to commit (depth-from-tail = {self._backtrack.selected_idx})."
            )

    def on_sidebar_session_selected(self, event: Sidebar.SessionSelected) -> None:
        """Handle session selection from sidebar."""
        transcript = self.query_one(Transcript)
        transcript.add_system_message(f"Switching to session: {event.session_id[:8]}...")
        self.query_one(Sidebar).hide_sidebar()

    # ── notifications ─────────────────────────────────────────────────

    def _maybe_notify_turn_done(self) -> None:
        """Emit OSC 9 / BEL when a long turn finishes (mirrors Rust notifications.rs).

        Threshold + method come from ``Config.ui.notify_*``. Silently no-ops
        when stdout has no buffer or method is OFF.
        """
        import sys

        from deepseek_tui.tui.notifications import Method, notify_done_to

        started = self._turn_started_at
        self._turn_started_at = None
        if started is None:
            return
        elapsed = time.monotonic() - started

        ui = self.config.ui
        method = Method.from_str(ui.notify_method)
        threshold_secs = float(ui.notify_threshold_secs)
        in_tmux = bool(os.environ.get("TMUX"))
        sink = getattr(sys.stdout, "buffer", None)
        if sink is None:
            return
        try:
            notify_done_to(method, in_tmux, "deepseek: done", threshold_secs, elapsed, sink)
        except (OSError, ValueError):
            return
