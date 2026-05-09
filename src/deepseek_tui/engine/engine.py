from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.approval import ApprovalHandler, AutoApprovalHandler
from deepseek_tui.engine.capacity import CapacityController, CapacityControllerConfig
from deepseek_tui.engine.capacity_flow import (
    run_error_escalation_checkpoint,
    run_post_tool_checkpoint,
    run_pre_request_checkpoint,
)
from deepseek_tui.engine.compaction import (
    CompactionConfig,
    compact_messages_safe,
    should_compact,
)
from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.engine.dispatch import format_tool_error
from deepseek_tui.engine.events import (
    ApprovalRequiredEvent,
    ApprovalResolvedEvent,
    ErrorEvent,
    SandboxDeniedEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
    TurnStartedEvent,
    UserInputRequiredEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.ops import CancelRequestOp, SendMessageOp
from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.engine.tool_catalog import (
    CODE_EXECUTION_TOOL_NAME,
    MULTI_TOOL_PARALLEL_NAME,
    REQUEST_USER_INPUT_NAME,
    execute_code_execution_tool,
    execute_tool_search,
    is_tool_search_tool,
    missing_tool_error_message,
)
from deepseek_tui.engine.tool_execution import emit_tool_audit
from deepseek_tui.engine.turn_loop import TurnLoop, TurnResult
from deepseek_tui.execpolicy.approval_cache import (
    ApprovalCache,
    ApprovalCacheStatus,
    build_approval_key,
)
from deepseek_tui.execpolicy.engine import ExecPolicyEngine
from deepseek_tui.execpolicy.models import ApprovalDecision
from deepseek_tui.lsp import (
    LSP_MANAGER_KEY,
    DiagnosticBlock,
    LspManager,
    edited_paths_for_tool,
    render_blocks,
)
from deepseek_tui.protocol.messages import Message, ToolUseBlock
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.base import ToolError, ToolResult
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from deepseek_tui.tools.runtime import ToolRuntime

logger = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        handle: EngineHandle,
        client: LLMClient,
        default_model: str = "deepseek-chat",
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
        exec_policy: ExecPolicyEngine | None = None,
        approval_handler: ApprovalHandler | None = None,
        max_tool_round_trips: int = 3,
        tool_runtime: ToolRuntime | None = None,
        compaction_config: CompactionConfig | None = None,
        skill_registry: object | None = None,
    ) -> None:
        self.handle = handle
        self.client = client
        self.default_model = default_model
        # When a full runtime is supplied, it wins — unpack registry + context
        # from it so managers stay paired with the context they own.
        if tool_runtime is not None:
            self.tool_registry = tool_runtime.registry
            self.tool_context = tool_runtime.context
        else:
            self.tool_registry = tool_registry or ToolRegistry()
            self.tool_context = tool_context or ToolContext(working_directory=Path.cwd())
        self.tool_runtime = tool_runtime
        # Ensure the registry dispatcher can see the context (Stage 3
        # managers are attached on the context, not the registry).
        self.tool_registry.set_context(self.tool_context)
        self.exec_policy = exec_policy or ExecPolicyEngine()
        self.approval_handler = approval_handler or AutoApprovalHandler()
        self.max_tool_round_trips = max_tool_round_trips
        self.compaction_config = compaction_config or CompactionConfig()
        self.capacity_controller = CapacityController(config=CapacityControllerConfig())
        self.session_messages: list[Message] = []
        self.turn_loop = TurnLoop(client, compact_fn=self._emergency_compact)
        # Stage 4.4 post-edit LSP diagnostics — Rust ``Engine.pending_lsp_blocks``
        self.pending_lsp_blocks: list[DiagnosticBlock] = []
        self.turn_counter = 0
        # Stage 3.next.1 approval cache — fingerprints repeat tool calls
        # so an APPROVED_SESSION grant doesn't have to re-prompt.
        self.approval_cache = ApprovalCache()
        self._tool_write_lock = asyncio.Lock()
        # Skills integration — renders available skills into system prompt
        self.skill_registry = skill_registry
        # Per-tool snapshots for /undo (mirrors Rust pre_tool_snapshot, #384).
        # Maps tool_call_id → list[(absolute_path, original_bytes_or_None)].
        # None means file did not exist before the tool ran.
        self.tool_snapshots: dict[str, list[tuple[Path, bytes | None]]] = {}

    @classmethod
    async def create(
        cls,
        handle: EngineHandle,
        client: LLMClient,
        *,
        config: object | None = None,
        working_directory: Path | None = None,
        mode: str = "agent",
        default_model: str = "deepseek-chat",
        exec_policy: ExecPolicyEngine | None = None,
        approval_handler: ApprovalHandler | None = None,
        max_tool_round_trips: int = 3,
    ) -> Engine:
        """Construct an Engine with a freshly-wired :class:`ToolRuntime`.

        This is the integration-complete path: all managers (task/subagent),
        the full registry, and the ToolContext are created together so that
        tools can actually reach the managers at dispatch time.
        """
        from deepseek_tui.config.models import Config
        from deepseek_tui.skills import discover_in_workspace
        from deepseek_tui.tools.runtime import create_tool_runtime

        cfg = config if isinstance(config, Config) else Config()
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=working_directory,
            mode=mode,
        )
        # Discover skills for system prompt injection
        skill_reg = discover_in_workspace(workspace=working_directory)
        return cls(
            handle=handle,
            client=client,
            default_model=default_model,
            exec_policy=exec_policy,
            approval_handler=approval_handler,
            max_tool_round_trips=max_tool_round_trips,
            tool_runtime=runtime,
            skill_registry=skill_reg,
        )

    def _render_skills_context(self) -> str | None:
        """Render skills context for system prompt injection."""
        if self.skill_registry is None:
            return None
        from deepseek_tui.skills import render_available_skills_context

        return render_available_skills_context(self.skill_registry) or None

    async def shutdown(self) -> None:
        """Drain managers owned by the tool runtime if Engine built it."""
        if self.tool_runtime is not None:
            await self.tool_runtime.shutdown()
        if hasattr(self.client, "close"):
            await self.client.close()

    async def run(self) -> None:
        while True:
            op = await self.handle.next_op()
            if isinstance(op, SendMessageOp):
                await self._handle_send_message(op)
            elif isinstance(op, CancelRequestOp):
                continue

    async def _handle_send_message(self, op: SendMessageOp) -> None:
        self.handle.reset_cancel()
        user_message = Message.user(op.content)
        working_messages = [*self.session_messages, user_message]

        await self.handle.emit(TurnStartedEvent(user_text=op.content))
        result = await self._run_conversation(
            messages=working_messages,
            model=op.model or self.default_model,
            system_prompt=build_system_prompt(
                op.system_prompt,
                skills_context=self._render_skills_context(),
            ),
            max_tokens=op.max_tokens,
        )

        if result.cancelled:
            await self.handle.emit(TurnCancelledEvent(reason="user_cancelled"))
            return

        self.session_messages = working_messages
        await self.handle.emit(
            TurnCompleteEvent(
                assistant_message=result.assistant_message,
                usage=result.usage,
            )
        )
        await self._auto_persist_session()

    async def _run_conversation(
        self,
        messages: list[Message],
        model: str,
        system_prompt: str,
        max_tokens: int | None,
    ) -> TurnResult:
        tools = self.tool_registry.to_api_tools()
        self.turn_counter += 1
        step_error_count = 0
        consecutive_tool_error_steps = 0
        for _ in range(self.max_tool_round_trips + 1):
            # Drain steer messages — mid-turn user input (mirrors turn_loop.rs:49-57)
            for steer_text in self.handle.drain_steers():
                steer_text = steer_text.strip()
                if steer_text:
                    messages.append(Message.user(steer_text))

            # Capacity pre-request checkpoint (mirrors capacity_flow.rs:13-34)
            await run_pre_request_checkpoint(
                self.capacity_controller,
                self.turn_counter,
                model,
                messages,
                compact_fn=self._emergency_compact,
            )

            # Auto-compact before each LLM call if thresholds exceeded.
            # Mirrors Rust turn_loop.rs:85-168.
            if should_compact(messages, self.compaction_config):
                compact_result = await compact_messages_safe(
                    self.client,
                    messages,
                    self.compaction_config,
                    workspace=self.tool_context.working_directory,
                )
                messages[:] = compact_result.messages
                if compact_result.summary_prompt:
                    system_prompt = f"{system_prompt}\n\n{compact_result.summary_prompt}"

            # Flush any diagnostics queued by post-edit hooks from the
            # previous round-trip so the model sees them on this request.
            self._flush_pending_lsp_diagnostics(messages)
            request = MessageRequest(
                model=model,
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                max_tokens=max_tokens,
            )
            result = await self.turn_loop.run(
                request, self.handle.emit, self.handle.cancel_event, tools=tools
            )
            if result.cancelled:
                return result
            if result.assistant_message is not None:
                messages.append(result.assistant_message)
            if not result.tool_calls:
                return result

            messages.append(self._build_tool_use_message(result.tool_calls))
            tool_results = await self._execute_tool_calls(result.tool_calls, model)
            tool_errors = sum(1 for m in tool_results if any(
                getattr(b, "is_error", False) for b in m.content if hasattr(b, "is_error")
            ))
            messages.extend(tool_results)

            # Capacity post-tool checkpoint (mirrors capacity_flow.rs:37-76)
            await run_post_tool_checkpoint(
                self.capacity_controller, self.turn_counter, model, messages,
            )

            # Capacity error escalation (mirrors capacity_flow.rs:78-151)
            if tool_errors > 0:
                step_error_count += tool_errors
                consecutive_tool_error_steps += 1
                await run_error_escalation_checkpoint(
                    self.capacity_controller,
                    self.turn_counter,
                    model,
                    messages,
                    step_error_count=step_error_count,
                    consecutive_tool_error_steps=consecutive_tool_error_steps,
                )
            else:
                consecutive_tool_error_steps = 0

        await self.handle.emit(
            ErrorEvent(
                message="Tool round-trip limit exceeded",
                retryable=False,
            )
        )
        return TurnResult(assistant_message=None, usage=None, tool_calls=[])

    def _build_tool_use_message(self, tool_calls: list[ToolCall]) -> Message:
        return Message.assistant_with_tools(
            [
                ToolUseBlock(id=tool_call.id, name=tool_call.name, input=tool_call.arguments)
                for tool_call in tool_calls
            ]
        )

    async def _execute_tool_calls(
        self, tool_calls: list[ToolCall], model: str | None = None
    ) -> list[Message]:
        results: list[Message] = []
        effective_model = model or self.default_model
        api_tools = self.tool_registry.to_api_tools()

        for tool_call in tool_calls:
            try:
                result = await self._execute_single_tool(
                    tool_call, api_tools, effective_model
                )
                if result is None:
                    results.append(
                        Message.tool_result(
                            tool_call.id,
                            f"Tool {tool_call.name} denied by approval policy",
                            is_error=True,
                        )
                    )
                    continue

                emit_tool_audit(
                    {
                        "event": "tool.result",
                        "tool_id": tool_call.id,
                        "tool_name": tool_call.name,
                        "success": result.success,
                    }
                )
                await self.handle.emit(
                    ToolResultEvent(
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        content=result.content,
                        success=result.success,
                    )
                )
                if result.success:
                    await self._run_post_edit_lsp_hook(
                        tool_call.name, tool_call.arguments
                    )
                output_for_context = compact_tool_result_for_context(
                    effective_model, tool_call.name, result
                )
                results.append(
                    Message.tool_result(
                        tool_call.id,
                        output_for_context,
                        is_error=not result.success,
                    )
                )
            except ToolError as exc:
                error_msg = format_tool_error(exc, tool_call.name)
                emit_tool_audit(
                    {
                        "event": "tool.result",
                        "tool_id": tool_call.id,
                        "tool_name": tool_call.name,
                        "success": False,
                        "error": error_msg,
                    }
                )
                await self.handle.emit(ErrorEvent(message=error_msg, retryable=False))
                results.append(
                    Message.tool_result(
                        tool_call.id, f"Error: {error_msg}", is_error=True
                    )
                )
        return results

    _SNAPSHOT_TOOLS: frozenset[str] = frozenset(
        {"write_file", "edit_file", "apply_patch"}
    )

    def _take_pre_tool_snapshot(
        self, tool_call_id: str, tool_name: str, args: dict[str, Any]
    ) -> None:
        """Capture file contents before a write tool runs (mirrors Rust #384).

        Best-effort — failures here must never block tool execution.
        """
        if tool_name not in self._SNAPSHOT_TOOLS:
            return
        from deepseek_tui.lsp import edited_paths_for_tool

        try:
            paths = edited_paths_for_tool(tool_name, args)
        except Exception:  # noqa: BLE001
            return
        workspace = self.tool_context.working_directory
        snapshots: list[tuple[Path, bytes | None]] = []
        for p in paths:
            absolute = p if p.is_absolute() else workspace / p
            try:
                snapshots.append((absolute, absolute.read_bytes()))
            except FileNotFoundError:
                snapshots.append((absolute, None))
            except OSError:
                continue
        if snapshots:
            self.tool_snapshots[tool_call_id] = snapshots

    def undo_last_tool(self) -> tuple[bool, str]:
        """Restore the most recent tool snapshot (mirrors Rust /undo).

        Returns (success, message).
        """
        if not self.tool_snapshots:
            return False, "No tool snapshots available to undo."
        last_id = next(reversed(self.tool_snapshots))
        snapshots = self.tool_snapshots.pop(last_id)
        restored = 0
        errors: list[str] = []
        for path, original in snapshots:
            try:
                if original is None:
                    if path.exists():
                        path.unlink()
                else:
                    path.write_bytes(original)
                restored += 1
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        if errors:
            return False, f"Restored {restored}; errors: {'; '.join(errors)}"
        return True, f"Reverted {restored} file(s) from tool {last_id[:8]}"

    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        api_tools: list[dict[str, Any]],
        model: str,
    ) -> ToolResult | None:
        """Execute a single tool call, handling special tools and approval.

        Returns None if the tool was denied by approval.
        """
        tool_name = tool_call.name
        # Snapshot before file-modifying tools
        self._take_pre_tool_snapshot(tool_call.id, tool_name, tool_call.arguments)

        # --- Special built-in tools (not in ToolRegistry) ---
        if is_tool_search_tool(tool_name):
            active: set[str] = set()
            for t in api_tools:
                fn = t.get("function", t)
                if isinstance(fn, dict):
                    name = fn.get("name", "")
                    if isinstance(name, str):
                        active.add(name)
            return execute_tool_search(
                tool_name, tool_call.arguments, api_tools, active
            )

        if tool_name == CODE_EXECUTION_TOOL_NAME:
            return await execute_code_execution_tool(
                tool_call.arguments, self.tool_context.working_directory
            )

        if tool_name == MULTI_TOOL_PARALLEL_NAME:
            return await self._execute_parallel_tools(tool_call.arguments)

        if tool_name == REQUEST_USER_INPUT_NAME:
            return await self._await_user_input(tool_call.id, tool_call.arguments)

        # --- Normal registry tools ---
        if not self.tool_registry.contains(tool_name):
            raise ToolError(missing_tool_error_message(tool_name, api_tools))

        tool = self.tool_registry.get(tool_name)

        # Approval gate
        approval_request = self.exec_policy.evaluate(
            tool_name, tool.capabilities()
        )
        if approval_request is not None:
            denied = await self._handle_approval_flow(tool_call, approval_request)
            if denied:
                return None

        return await self.tool_registry.execute(
            tool_name, tool_call.arguments, self.tool_context
        )

    async def _handle_approval_flow(
        self,
        tool_call: ToolCall,
        approval_request: Any,
    ) -> bool:
        """Run the approval gate. Returns True if denied."""
        cache_key = build_approval_key(tool_call.name, tool_call.arguments)
        cache_status = self.approval_cache.check(cache_key)

        if cache_status is ApprovalCacheStatus.APPROVED:
            await self.handle.emit(
                ApprovalResolvedEvent(
                    tool_call_id=tool_call.id,
                    approved=True,
                    reason="cached_session",
                )
            )
            return False

        emit_tool_audit(
            {
                "event": "tool.approval_required",
                "tool_id": tool_call.id,
                "tool_name": tool_call.name,
            }
        )
        await self.handle.emit(
            ApprovalRequiredEvent(
                tool_call_id=tool_call.id,
                request=approval_request,
            )
        )
        decision = await self.approval_handler.request_approval(
            tool_call.id, approval_request
        )
        approved = decision in {
            ApprovalDecision.APPROVED,
            ApprovalDecision.APPROVED_SESSION,
        }
        emit_tool_audit(
            {
                "event": "tool.approval_decision",
                "tool_id": tool_call.id,
                "tool_name": tool_call.name,
                "decision": decision.value,
            }
        )
        await self.handle.emit(
            ApprovalResolvedEvent(
                tool_call_id=tool_call.id,
                approved=approved,
                reason=decision.value,
            )
        )
        if decision is ApprovalDecision.DENIED:
            await self.handle.emit(
                SandboxDeniedEvent(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    reason=f"Tool {tool_call.name} denied by approval policy",
                )
            )
            return True

        self.approval_cache.insert(
            cache_key,
            approved_for_session=(decision is ApprovalDecision.APPROVED_SESSION),
        )
        self.exec_policy.record_decision(tool_call.name, decision)
        return False

    async def _auto_persist_session(self) -> None:
        """Best-effort session persistence after each turn.

        Writes session_messages to a JSON file so sessions survive restarts.
        Mirrors Rust ``Engine::auto_save_session`` behavior. Silent on failure.
        """
        try:
            from deepseek_tui.config.paths import default_config_path

            sessions_dir = default_config_path().parent / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            session_file = sessions_dir / "current.json"
            import json as _json

            data = {
                "model": self.default_model,
                "turn_counter": self.turn_counter,
                "messages": [m.model_dump() for m in self.session_messages],
            }
            tmp = session_file.with_suffix(".tmp")
            tmp.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(session_file)
        except Exception:  # noqa: BLE001
            pass

    async def _emergency_compact(self, messages: list[Message]) -> list[Message]:
        """Emergency compaction callback for TurnLoop context overflow recovery."""
        result = await compact_messages_safe(
            self.client,
            messages,
            self.compaction_config,
            workspace=self.tool_context.working_directory,
        )
        return result.messages

    # --- Engine-intercepted special tools --------------------------------

    async def _execute_parallel_tools(self, input_data: dict[str, Any]) -> ToolResult:
        """Fan out multi_tool_use.parallel sub-calls concurrently.

        Mirrors Rust turn_loop.rs:1161-1189 + tool_execution.rs:58-67.
        Only read-only tools that don't require approval are eligible.
        Recursive self-calls are rejected (tool_execution.rs:63).
        """
        tool_uses = input_data.get("tool_uses")
        if not isinstance(tool_uses, list) or not tool_uses:
            raise ToolError("tool_uses must be a non-empty array")

        async def _run_one(item: dict[str, Any]) -> dict[str, str]:
            name = item.get("recipient_name", "")
            params = item.get("parameters", {})
            if not isinstance(params, dict):
                params = {}
            for prefix in ("functions.", "tools.", "tool."):
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            if name == MULTI_TOOL_PARALLEL_NAME:
                return {
                    "tool": name,
                    "error": "multi_tool_use.parallel cannot call itself",
                    "success": "false",
                }
            if not self.tool_registry.contains(name):
                return {
                    "tool": name,
                    "error": f"Tool '{name}' not found",
                    "success": "false",
                }
            tool = self.tool_registry.get(name)
            if not tool.is_read_only():
                return {
                    "tool": name,
                    "error": f"Tool '{name}' is not read-only; denied",
                    "success": "false",
                }
            try:
                result = await self.tool_registry.execute(
                    name, params, self.tool_context
                )
                return {"tool": name, "content": result.content, "success": "true"}
            except (ToolError, Exception) as exc:
                return {"tool": name, "error": str(exc), "success": "false"}

        import json as _json

        results = await asyncio.gather(*[_run_one(item) for item in tool_uses])
        return ToolResult(content=_json.dumps(results, ensure_ascii=False), success=True)

    async def _await_user_input(
        self, tool_call_id: str, input_data: dict[str, Any]
    ) -> ToolResult:
        """Emit UserInputRequiredEvent and block until TUI resolves.

        Mirrors Rust turn_loop.rs:1245-1275.
        """
        from deepseek_tui.tools.user_input_tool import validate_user_input_request

        questions = validate_user_input_request(input_data)
        questions_payload: list[dict[str, object]] = [
            {
                "header": q.header,
                "id": q.id,
                "question": q.question,
                "options": q.options,
            }
            for q in questions
        ]

        # Create a future the TUI will resolve
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self.handle.pending_user_inputs[tool_call_id] = future

        await self.handle.emit(
            UserInputRequiredEvent(
                tool_call_id=tool_call_id,
                questions=questions_payload,
            )
        )

        try:
            response = await future
        finally:
            self.handle.pending_user_inputs.pop(tool_call_id, None)

        import json as _json

        return ToolResult(content=_json.dumps(response, ensure_ascii=False), success=True)

    # --- Stage 4.4 post-edit LSP hooks --------------------------------

    def _get_lsp_manager(self) -> LspManager | None:
        """Pull LspManager from ToolContext.metadata (set by ToolRuntime).

        Duck-typed for testability — the engine only needs ``config``
        and ``diagnostics_for``, so any object exposing that shape works.
        """
        manager = self.tool_context.metadata.get(LSP_MANAGER_KEY)
        if manager is None:
            return None
        if not hasattr(manager, "diagnostics_for") or not hasattr(manager, "config"):
            return None
        return manager  # type: ignore[no-any-return]

    async def _run_post_edit_lsp_hook(
        self, tool_name: str, tool_input: dict[str, object]
    ) -> None:
        """Queue diagnostics for files the tool just edited.

        Mirrors Rust ``Engine::run_post_edit_lsp_hook`` (lsp_hooks.rs:80-103).
        Silent failure — a dead LSP server must never block the agent.
        """
        manager = self._get_lsp_manager()
        if manager is None or not manager.config.enabled:
            return
        paths = edited_paths_for_tool(tool_name, tool_input)
        if not paths:
            return
        workspace = self.tool_context.working_directory
        for path in paths:
            absolute = path if path.is_absolute() else workspace / path
            try:
                content = absolute.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                blocks = await manager.diagnostics_for(
                    absolute, content, self.turn_counter
                )
            except Exception:  # noqa: BLE001 — LSP failure is silent
                continue
            self.pending_lsp_blocks.extend(blocks)

    def _flush_pending_lsp_diagnostics(self, messages: list[Message]) -> None:
        """Render pending blocks into a synthetic user message.

        Mirrors Rust ``Engine::flush_pending_lsp_diagnostics``
        (lsp_hooks.rs:110-127). Attaches the rendered block to
        ``messages`` in place so it rides the next request.
        """
        if not self.pending_lsp_blocks:
            return
        blocks = self.pending_lsp_blocks
        self.pending_lsp_blocks = []
        rendered = render_blocks(blocks)
        if not rendered:
            return
        messages.append(Message.user(rendered))
