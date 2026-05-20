"""Parity tests for IPC protocol types.

Verifies that the Python port emits JSON byte-identical to the Rust
reference at ``docs/DeepSeek-TUI-main/crates/protocol/src/lib.rs``.

Three tests come straight from the Rust parity suite at
``crates/protocol/tests/parity_protocol.rs``:

* test_thread_resume_params_round_trip
* test_thread_list_params_defaults_are_serializable
* test_event_frame_serialization_contains_expected_tag

The rest are extensions that lock down the Rust JSON shape for every
enum variant — Pydantic's defaults differ from serde in several places
(Discriminated Union tag position, None-field omission, unit-variant
encoding), so each deviation deserves an explicit test.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import TypeAdapter

from deepseek_tui.protocol import (
    AskForApproval,
    Envelope,
    EventFrame,
    ExecApprovalRequestEvent,
    LocalShellParams,
    McpStartupCompleteEvent,
    McpStartupFailure,
    McpStartupStatus,
    McpStartupUpdateEvent,
    NetworkApprovalContext,
    NetworkPolicyAmendment,
    NetworkPolicyRuleAction,
    ReviewDecision,
    ReviewDecisionApproved,
    ReviewDecisionNetworkPolicyAmendment,
    SessionSource,
    Thread,
    ThreadListRequest,
    ThreadRequest,
    ThreadResponse,
    ThreadResumeRequest,
    ThreadStatus,
    ToolOutput,
    ToolOutputFunction,
    ToolOutputMcp,
    ToolPayload,
    ToolPayloadFunction,
    ToolPayloadLocalShell,
    ToolPayloadMcp,
    TurnCompleteEvent,
)
from deepseek_tui.protocol.threads import ThreadCreateRequest

_EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(EventFrame)
_THREAD_REQ_ADAPTER: TypeAdapter[Any] = TypeAdapter(ThreadRequest)
_TOOL_PAYLOAD_ADAPTER: TypeAdapter[Any] = TypeAdapter(ToolPayload)
_TOOL_OUTPUT_ADAPTER: TypeAdapter[Any] = TypeAdapter(ToolOutput)
_REVIEW_ADAPTER: TypeAdapter[Any] = TypeAdapter(ReviewDecision)


def _round_trip(adapter: TypeAdapter[Any], value: Any) -> Any:
    """Serialize `value` then deserialize it again via `adapter`."""
    encoded = adapter.dump_json(value, exclude_none=True).decode("utf-8")
    return adapter.validate_json(encoded)


# ---------------------------------------------------------------------------
# 1. Direct ports of Rust `parity_protocol.rs`
# ---------------------------------------------------------------------------


def test_thread_resume_params_round_trip() -> None:
    """Mirror of Rust `thread_resume_params_round_trip`."""
    req = ThreadResumeRequest(
        thread_id="thread-123",
        history=None,
        path=None,
        model="deepseek-v4-pro",
        model_provider="deepseek",
        cwd=None,
        approval_policy="on-request",
        sandbox="workspace-write",
        config=None,
        base_instructions="base",
        developer_instructions="dev",
        personality="default",
        persist_extended_history=True,
    )
    encoded_bytes = _THREAD_REQ_ADAPTER.dump_json(req, exclude_none=True)
    encoded = encoded_bytes.decode("utf-8")
    decoded = _THREAD_REQ_ADAPTER.validate_json(encoded)

    assert isinstance(decoded, ThreadResumeRequest)
    assert decoded.kind == "resume"
    assert decoded.thread_id == "thread-123"
    assert decoded.model == "deepseek-v4-pro"
    assert decoded.persist_extended_history is True


def test_thread_list_params_defaults_are_serializable() -> None:
    """Mirror of Rust `thread_list_params_defaults_are_serializable`."""
    req = ThreadListRequest(include_archived=False, limit=20)
    encoded = _THREAD_REQ_ADAPTER.dump_json(req, exclude_none=True).decode("utf-8")
    assert "include_archived" in encoded
    # Kind tag must be present and equal the variant name.
    assert '"kind":"list"' in encoded


def test_event_frame_serialization_contains_expected_tag() -> None:
    """Mirror of Rust `event_frame_serialization_contains_expected_tag`."""
    frame = TurnCompleteEvent(turn_id="turn-1")
    encoded = _EVENT_ADAPTER.dump_json(frame, exclude_none=True).decode("utf-8")
    assert "turn_complete" in encoded
    # Also: the tag key is "event", not "type" (serde `tag = "event"`).
    parsed = json.loads(encoded)
    assert parsed == {"event": "turn_complete", "turn_id": "turn-1"}


# ---------------------------------------------------------------------------
# 2. Envelope[T]
# ---------------------------------------------------------------------------


def test_envelope_with_thread_id_serialises() -> None:
    env: Envelope[dict[str, str]] = Envelope(
        request_id="req-1",
        thread_id="thread-xyz",
        body={"hello": "world"},
    )
    data = json.loads(env.model_dump_json(exclude_none=True))
    assert data == {
        "request_id": "req-1",
        "thread_id": "thread-xyz",
        "body": {"hello": "world"},
    }


def test_envelope_omits_thread_id_when_none() -> None:
    """`skip_serializing_if = "Option::is_none"` on the Rust side."""
    env: Envelope[dict[str, int]] = Envelope(request_id="req-1", body={"n": 1})
    data = json.loads(env.model_dump_json(exclude_none=True))
    assert data == {"request_id": "req-1", "body": {"n": 1}}


# ---------------------------------------------------------------------------
# 3. EventFrame — all 21 variants, tag = "event"
# ---------------------------------------------------------------------------


_EVENT_VARIANT_SAMPLES: list[tuple[str, dict[str, Any]]] = [
    ("response_start", {"event": "response_start", "response_id": "r1"}),
    (
        "response_delta",
        {"event": "response_delta", "response_id": "r1", "delta": "hi"},
    ),
    ("response_end", {"event": "response_end", "response_id": "r1"}),
    (
        "tool_call_start",
        {
            "event": "tool_call_start",
            "response_id": "r1",
            "tool_name": "read_file",
            "arguments": {"path": "/tmp/a"},
        },
    ),
    (
        "tool_call_result",
        {
            "event": "tool_call_result",
            "response_id": "r1",
            "tool_name": "read_file",
            "output": "file contents",
        },
    ),
    (
        "mcp_startup_update",
        {
            "event": "mcp_startup_update",
            "update": {"server_name": "fs", "status": "ready"},
        },
    ),
    (
        "mcp_startup_complete",
        {
            "event": "mcp_startup_complete",
            "summary": {"ready": ["fs"], "failed": [], "cancelled": []},
        },
    ),
    (
        "mcp_tool_call_begin",
        {
            "event": "mcp_tool_call_begin",
            "server_name": "fs",
            "tool_name": "read",
        },
    ),
    (
        "mcp_tool_call_end",
        {
            "event": "mcp_tool_call_end",
            "server_name": "fs",
            "tool_name": "read",
            "ok": True,
        },
    ),
    (
        "exec_approval_request",
        {
            "event": "exec_approval_request",
            "request": {
                "call_id": "c1",
                "approval_id": "a1",
                "turn_id": "t1",
                "command": "ls",
                "cwd": "/tmp",
                "reason": "tool ls",
                "proposed_execpolicy_amendment": [],
                "proposed_network_policy_amendments": [],
                "additional_permissions": [],
                "available_decisions": [],
            },
        },
    ),
    (
        "apply_patch_approval_request",
        {
            "event": "apply_patch_approval_request",
            "request": {
                "call_id": "c1",
                "approval_id": "a1",
                "turn_id": "t1",
                "command": "apply_patch",
                "cwd": "/tmp",
                "reason": "write",
                "proposed_execpolicy_amendment": [],
                "proposed_network_policy_amendments": [],
                "additional_permissions": [],
                "available_decisions": [],
            },
        },
    ),
    (
        "elicitation_request",
        {
            "event": "elicitation_request",
            "server_name": "fs",
            "request_id": "e1",
            "prompt": "which file?",
        },
    ),
    (
        "exec_command_begin",
        {"event": "exec_command_begin", "command": "ls -l", "cwd": "/tmp"},
    ),
    (
        "exec_command_output_delta",
        {
            "event": "exec_command_output_delta",
            "command": "ls -l",
            "delta": "file1\n",
        },
    ),
    (
        "exec_command_end",
        {"event": "exec_command_end", "command": "ls -l", "exit_code": 0},
    ),
    ("patch_apply_begin", {"event": "patch_apply_begin", "path": "/tmp/a.py"}),
    ("patch_apply_end", {"event": "patch_apply_end", "path": "/tmp/a.py", "ok": True}),
    ("turn_started", {"event": "turn_started", "turn_id": "t1"}),
    ("turn_complete", {"event": "turn_complete", "turn_id": "t1"}),
    (
        "turn_aborted",
        {"event": "turn_aborted", "turn_id": "t1", "reason": "user"},
    ),
    ("error", {"event": "error", "response_id": "r1", "message": "boom"}),
]


@pytest.mark.parametrize("tag,expected", _EVENT_VARIANT_SAMPLES)
def test_event_frame_variant_round_trip(tag: str, expected: dict[str, Any]) -> None:
    decoded = _EVENT_ADAPTER.validate_python(expected)
    encoded = json.loads(
        _EVENT_ADAPTER.dump_json(decoded, exclude_none=True).decode("utf-8")
    )
    assert encoded == expected
    assert encoded["event"] == tag


def test_event_frame_exhaustiveness() -> None:
    """All 21 Rust variants are represented in our parametrize table."""
    assert len(_EVENT_VARIANT_SAMPLES) == 21
    assert len({tag for tag, _ in _EVENT_VARIANT_SAMPLES}) == 21


# ---------------------------------------------------------------------------
# 4. ThreadRequest — tag = "kind", all 10 variants
# ---------------------------------------------------------------------------


_THREAD_VARIANT_SAMPLES: list[tuple[str, dict[str, Any]]] = [
    ("create", {"kind": "create", "metadata": {}}),
    ("start", {"kind": "start", "persist_extended_history": False}),
    (
        "resume",
        {
            "kind": "resume",
            "thread_id": "t1",
            "persist_extended_history": False,
        },
    ),
    (
        "fork",
        {"kind": "fork", "thread_id": "t1", "persist_extended_history": False},
    ),
    ("list", {"kind": "list", "include_archived": False}),
    ("read", {"kind": "read", "thread_id": "t1"}),
    (
        "set_name",
        {"kind": "set_name", "thread_id": "t1", "name": "renamed"},
    ),
    ("archive", {"kind": "archive", "thread_id": "t1"}),
    ("unarchive", {"kind": "unarchive", "thread_id": "t1"}),
    (
        "message",
        {"kind": "message", "thread_id": "t1", "input": "hello"},
    ),
]


@pytest.mark.parametrize("tag,expected", _THREAD_VARIANT_SAMPLES)
def test_thread_request_variant_round_trip(
    tag: str, expected: dict[str, Any]
) -> None:
    decoded = _THREAD_REQ_ADAPTER.validate_python(expected)
    encoded = json.loads(
        _THREAD_REQ_ADAPTER.dump_json(decoded, exclude_none=True).decode("utf-8")
    )
    assert encoded == expected
    assert encoded["kind"] == tag


def test_thread_request_exhaustiveness() -> None:
    assert len(_THREAD_VARIANT_SAMPLES) == 10
    assert len({tag for tag, _ in _THREAD_VARIANT_SAMPLES}) == 10


def test_thread_create_metadata_defaults_to_object() -> None:
    """Rust `#[serde(default)]` on metadata → Pydantic default_factory=dict."""
    req = ThreadCreateRequest()  # no metadata explicitly
    encoded = json.loads(
        _THREAD_REQ_ADAPTER.dump_json(req, exclude_none=True).decode("utf-8")
    )
    assert encoded == {"kind": "create", "metadata": {}}



# ---------------------------------------------------------------------------
# 6. ToolPayload / ToolOutput — tag = "type"
# ---------------------------------------------------------------------------


def test_tool_payload_function_variant() -> None:
    payload = ToolPayloadFunction(arguments="{\"path\": \"/a\"}")
    data = json.loads(
        _TOOL_PAYLOAD_ADAPTER.dump_json(payload, exclude_none=True).decode("utf-8")
    )
    assert data == {"type": "function", "arguments": "{\"path\": \"/a\"}"}


def test_tool_payload_local_shell_variant() -> None:
    payload = ToolPayloadLocalShell(
        params=LocalShellParams(command="ls", cwd="/tmp", timeout_ms=500),
    )
    data = json.loads(
        _TOOL_PAYLOAD_ADAPTER.dump_json(payload, exclude_none=True).decode("utf-8")
    )
    assert data == {
        "type": "local_shell",
        "params": {"command": "ls", "cwd": "/tmp", "timeout_ms": 500},
    }


def test_tool_payload_mcp_omits_raw_tool_call_id_when_none() -> None:
    payload = ToolPayloadMcp(
        server="fs",
        tool="read",
        raw_arguments={"p": 1},
    )
    data = json.loads(
        _TOOL_PAYLOAD_ADAPTER.dump_json(payload, exclude_none=True).decode("utf-8")
    )
    assert data == {
        "type": "mcp",
        "server": "fs",
        "tool": "read",
        "raw_arguments": {"p": 1},
    }


def test_tool_output_function_omits_body_when_none() -> None:
    out = ToolOutputFunction(success=True, body=None)
    data = json.loads(
        _TOOL_OUTPUT_ADAPTER.dump_json(out, exclude_none=True).decode("utf-8")
    )
    assert data == {"type": "function", "success": True}


def test_tool_output_mcp_variant() -> None:
    out = ToolOutputMcp(result={"k": "v"})
    data = json.loads(
        _TOOL_OUTPUT_ADAPTER.dump_json(out, exclude_none=True).decode("utf-8")
    )
    assert data == {"type": "mcp", "result": {"k": "v"}}


# ---------------------------------------------------------------------------
# 7. ReviewDecision — tag = "type", 6 variants
# ---------------------------------------------------------------------------


_REVIEW_VARIANT_SAMPLES: list[tuple[str, dict[str, Any]]] = [
    ("approved", {"type": "approved"}),
    (
        "approved_execpolicy_amendment",
        {"type": "approved_execpolicy_amendment"},
    ),
    ("approved_for_session", {"type": "approved_for_session"}),
    (
        "network_policy_amendment",
        {"type": "network_policy_amendment", "host": "x.com", "action": "allow"},
    ),
    ("denied", {"type": "denied"}),
    ("abort", {"type": "abort"}),
]


@pytest.mark.parametrize("tag,expected", _REVIEW_VARIANT_SAMPLES)
def test_review_decision_round_trip(
    tag: str, expected: dict[str, Any]
) -> None:
    decoded = _REVIEW_ADAPTER.validate_python(expected)
    encoded = json.loads(
        _REVIEW_ADAPTER.dump_json(decoded, exclude_none=True).decode("utf-8")
    )
    assert encoded == expected
    assert encoded["type"] == tag


# ---------------------------------------------------------------------------
# 8. AskForApproval (string-or-object discriminator)
# ---------------------------------------------------------------------------


def test_ask_for_approval_unit_variants_serialise_as_bare_string() -> None:
    for builder, expected in [
        (AskForApproval.unless_trusted, "unless_trusted"),
        (AskForApproval.on_failure, "on_failure"),
        (AskForApproval.on_request, "on_request"),
        (AskForApproval.never, "never"),
    ]:
        encoded = json.loads(builder().model_dump_json())
        assert encoded == expected


def test_ask_for_approval_reject_variant_is_tagged_object() -> None:
    ask = AskForApproval.reject(
        sandbox_approval=True, rules=False, mcp_elicitations=True
    )
    encoded = json.loads(ask.model_dump_json())
    assert encoded == {
        "reject": {
            "sandbox_approval": True,
            "rules": False,
            "mcp_elicitations": True,
        }
    }


def test_ask_for_approval_parses_bare_string() -> None:
    ask = AskForApproval.model_validate("on_request")
    encoded = json.loads(ask.model_dump_json())
    assert encoded == "on_request"


def test_ask_for_approval_parses_reject_object() -> None:
    ask = AskForApproval.model_validate(
        {"reject": {"sandbox_approval": True, "rules": True, "mcp_elicitations": False}}
    )
    encoded = json.loads(ask.model_dump_json())
    assert encoded == {
        "reject": {
            "sandbox_approval": True,
            "rules": True,
            "mcp_elicitations": False,
        }
    }


# ---------------------------------------------------------------------------
# 9. McpStartupStatus (string-or-object discriminator, like AskForApproval)
# ---------------------------------------------------------------------------


def test_mcp_startup_status_unit_variants_as_bare_strings() -> None:
    for builder, tag in [
        (McpStartupStatus.starting, "starting"),
        (McpStartupStatus.ready, "ready"),
        (McpStartupStatus.cancelled, "cancelled"),
    ]:
        encoded = json.loads(builder().model_dump_json())
        assert encoded == tag


def test_mcp_startup_status_failed_is_tagged_object() -> None:
    status = McpStartupStatus.failed("backend offline")
    encoded = json.loads(status.model_dump_json())
    assert encoded == {"failed": {"error": "backend offline"}}


def test_mcp_startup_update_event_round_trip() -> None:
    update = McpStartupUpdateEvent(
        server_name="fs", status=McpStartupStatus.ready()
    )
    encoded = json.loads(update.model_dump_json())
    assert encoded == {"server_name": "fs", "status": "ready"}


def test_mcp_startup_complete_event_round_trip() -> None:
    complete = McpStartupCompleteEvent(
        ready=["fs"],
        failed=[McpStartupFailure(server_name="shell", error="no exec")],
        cancelled=["scheduler"],
    )
    encoded = json.loads(complete.model_dump_json())
    assert encoded == {
        "ready": ["fs"],
        "failed": [{"server_name": "shell", "error": "no exec"}],
        "cancelled": ["scheduler"],
    }


# ---------------------------------------------------------------------------
# 10. ExecApprovalRequestEvent (the most complex non-EventFrame struct)
# ---------------------------------------------------------------------------


def test_exec_approval_request_event_full_round_trip() -> None:
    ev = ExecApprovalRequestEvent(
        call_id="c1",
        approval_id="a1",
        turn_id="t1",
        command="ls /etc",
        cwd="/tmp",
        reason="read sensitive dir",
        network_approval_context=NetworkApprovalContext(
            host="example.com", protocol="https"
        ),
        proposed_execpolicy_amendment=["allow_ls_etc"],
        proposed_network_policy_amendments=[
            NetworkPolicyAmendment(host="x.com", action=NetworkPolicyRuleAction.ALLOW)
        ],
        additional_permissions=["sandbox_bypass"],
        available_decisions=[
            ReviewDecisionApproved(),
            ReviewDecisionNetworkPolicyAmendment(
                host="x.com",
                action=NetworkPolicyRuleAction.ALLOW,
            ),
        ],
    )
    encoded = json.loads(ev.model_dump_json(exclude_none=True))
    assert encoded == {
        "call_id": "c1",
        "approval_id": "a1",
        "turn_id": "t1",
        "command": "ls /etc",
        "cwd": "/tmp",
        "reason": "read sensitive dir",
        "network_approval_context": {"host": "example.com", "protocol": "https"},
        "proposed_execpolicy_amendment": ["allow_ls_etc"],
        "proposed_network_policy_amendments": [{"host": "x.com", "action": "allow"}],
        "additional_permissions": ["sandbox_bypass"],
        "available_decisions": [
            {"type": "approved"},
            {"type": "network_policy_amendment", "host": "x.com", "action": "allow"},
        ],
    }


# ---------------------------------------------------------------------------
# 11. Thread + ThreadResponse
# ---------------------------------------------------------------------------


def test_thread_skip_none_fields() -> None:
    thread = Thread(
        id="t1",
        preview="hi",
        ephemeral=False,
        model_provider="deepseek",
        created_at=1_700_000_000,
        updated_at=1_700_000_100,
        status=ThreadStatus.RUNNING,
        path=None,  # should be omitted
        cwd="/tmp",
        cli_version="0.1.0",
        source=SessionSource.INTERACTIVE,
        name=None,  # should be omitted
    )
    encoded = json.loads(thread.model_dump_json(exclude_none=True))
    assert "path" not in encoded
    assert "name" not in encoded
    assert encoded["status"] == "running"
    assert encoded["source"] == "interactive"
    assert encoded["created_at"] == 1_700_000_000


def test_thread_response_defaults() -> None:
    resp = ThreadResponse(thread_id="t1", status="ok")
    encoded = json.loads(resp.model_dump_json(exclude_none=True))
    assert encoded["threads"] == []
    assert encoded["events"] == []
    # `data` gets the default_factory=dict → empty object in JSON.
    assert encoded["data"] == {}



