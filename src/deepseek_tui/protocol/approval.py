"""Approval & review types.

Mirrors:

* ``AskForApproval`` (protocol/src/lib.rs:226-236)
* ``NetworkPolicyRuleAction`` (lib.rs:288-293)
* ``NetworkPolicyAmendment`` (lib.rs:295-299)
* ``ReviewDecision`` (lib.rs:301-313)
* ``NetworkApprovalContext`` (lib.rs:343-347)
* ``ExecApprovalRequestEvent`` (lib.rs:349-367)

Rust JSON shapes::

    AskForApproval (rename_all = "snake_case"):
        "unless_trusted" | "on_failure" | "on_request" | "never"
        | {"reject": {"sandbox_approval": ..., "rules": ..., "mcp_elicitations": ...}}

    ReviewDecision (tag = "type", rename_all = "snake_case"):
        {"type": "approved"}
        {"type": "approved_execpolicy_amendment"}
        {"type": "approved_for_session"}
        {"type": "network_policy_amendment", "host": "...", "action": "allow"}
        {"type": "denied"}
        {"type": "abort"}
"""

from __future__ import annotations



from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_serializer, model_validator

__all__ = [
    "AskForApproval",
    "ExecApprovalRequestEvent",
    "LocalShellParams",
    "NetworkApprovalContext",
    "NetworkPolicyAmendment",
    "NetworkPolicyRuleAction",
    "ReviewDecision",
    "ReviewDecisionAbort",
    "ReviewDecisionApproved",
    "ReviewDecisionApprovedExecpolicyAmendment",
    "ReviewDecisionApprovedForSession",
    "ReviewDecisionDenied",
    "ReviewDecisionNetworkPolicyAmendment",
    "ToolKind",
    "ToolOutput",
    "ToolOutputFunction",
    "ToolOutputMcp",
    "ToolPayload",
    "ToolPayloadCustom",
    "ToolPayloadFunction",
    "ToolPayloadLocalShell",
    "ToolPayloadMcp",
]


# ---------------------------------------------------------------------------
# AskForApproval (rename_all = "snake_case", with one data variant "Reject")
# ---------------------------------------------------------------------------


class _AskUnlessTrusted(BaseModel):
    type: Literal["unless_trusted"] = "unless_trusted"


class _AskOnFailure(BaseModel):
    type: Literal["on_failure"] = "on_failure"


class _AskOnRequest(BaseModel):
    type: Literal["on_request"] = "on_request"


class _AskNever(BaseModel):
    type: Literal["never"] = "never"


class _AskReject(BaseModel):
    type: Literal["reject"] = "reject"
    sandbox_approval: bool
    rules: bool
    mcp_elicitations: bool


_AskVariants = Annotated[
    _AskUnlessTrusted | _AskOnFailure | _AskOnRequest | _AskNever | _AskReject,
    Field(discriminator="type"),
]


class AskForApproval(RootModel[_AskVariants]):
    """Mirror of Rust ``AskForApproval`` enum.

    Wire shape:

    * Unit variants → bare lower_snake string: ``"unless_trusted"`` etc.
    * ``Reject`` → ``{"reject": {"sandbox_approval": ..., "rules": ..., "mcp_elicitations": ...}}``
    """

    @classmethod
    def unless_trusted(cls) -> AskForApproval:
        return cls(_AskUnlessTrusted())

    @classmethod
    def on_failure(cls) -> AskForApproval:
        return cls(_AskOnFailure())

    @classmethod
    def on_request(cls) -> AskForApproval:
        return cls(_AskOnRequest())

    @classmethod
    def never(cls) -> AskForApproval:
        return cls(_AskNever())

    @classmethod
    def reject(
        cls,
        *,
        sandbox_approval: bool,
        rules: bool,
        mcp_elicitations: bool,
    ) -> AskForApproval:
        return cls(
            _AskReject(
                sandbox_approval=sandbox_approval,
                rules=rules,
                mcp_elicitations=mcp_elicitations,
            )
        )

    @model_serializer(mode="plain")
    def _serialise(self) -> Any:
        inner = self.root
        if isinstance(inner, _AskReject):
            return {
                "reject": {
                    "sandbox_approval": inner.sandbox_approval,
                    "rules": inner.rules,
                    "mcp_elicitations": inner.mcp_elicitations,
                }
            }
        return inner.type

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"type": data}
        if isinstance(data, dict) and "reject" in data and "type" not in data:
            payload = data["reject"]
            if isinstance(payload, dict):
                return {"type": "reject", **payload}
        return data


# ---------------------------------------------------------------------------
# NetworkPolicy
# ---------------------------------------------------------------------------


class NetworkPolicyRuleAction(str, Enum):
    """Mirror of Rust ``NetworkPolicyRuleAction`` (lib.rs:288-293)."""

    ALLOW = "allow"
    DENY = "deny"


class NetworkPolicyAmendment(BaseModel):
    """Mirror of Rust ``NetworkPolicyAmendment`` (lib.rs:295-299)."""

    host: str
    action: NetworkPolicyRuleAction


# ---------------------------------------------------------------------------
# ReviewDecision (tag = "type", rename_all = "snake_case")
# ---------------------------------------------------------------------------


class ReviewDecisionApproved(BaseModel):
    type: Literal["approved"] = "approved"


class ReviewDecisionApprovedExecpolicyAmendment(BaseModel):
    type: Literal["approved_execpolicy_amendment"] = "approved_execpolicy_amendment"


class ReviewDecisionApprovedForSession(BaseModel):
    type: Literal["approved_for_session"] = "approved_for_session"


class ReviewDecisionNetworkPolicyAmendment(BaseModel):
    type: Literal["network_policy_amendment"] = "network_policy_amendment"
    host: str
    action: NetworkPolicyRuleAction


class ReviewDecisionDenied(BaseModel):
    type: Literal["denied"] = "denied"


class ReviewDecisionAbort(BaseModel):
    type: Literal["abort"] = "abort"


ReviewDecision = Annotated[
    ReviewDecisionApproved
    | ReviewDecisionApprovedExecpolicyAmendment
    | ReviewDecisionApprovedForSession
    | ReviewDecisionNetworkPolicyAmendment
    | ReviewDecisionDenied
    | ReviewDecisionAbort,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Approval request payloads
# ---------------------------------------------------------------------------


class NetworkApprovalContext(BaseModel):
    """Mirror of Rust ``NetworkApprovalContext`` (lib.rs:343-347)."""

    host: str
    protocol: str


class ExecApprovalRequestEvent(BaseModel):
    """Mirror of Rust ``ExecApprovalRequestEvent`` (lib.rs:349-367).

    The ``available_decisions`` field carries Rust ``Vec<ReviewDecision>``;
    each item serialises with its own ``type`` discriminator.
    """

    call_id: str
    approval_id: str
    turn_id: str
    command: str
    cwd: str
    reason: str
    network_approval_context: NetworkApprovalContext | None = None
    proposed_execpolicy_amendment: list[str] = Field(default_factory=list)
    proposed_network_policy_amendments: list[NetworkPolicyAmendment] = Field(
        default_factory=list,
    )
    additional_permissions: list[str] = Field(default_factory=list)
    available_decisions: list[ReviewDecision] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool payload + output types (formerly tool_payload.py)
# ---------------------------------------------------------------------------


class ToolKind(str, Enum):
    FUNCTION = "function"
    MCP = "mcp"


class LocalShellParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    cwd: str | None = None
    timeout_ms: int | None = None


class ToolPayloadFunction(BaseModel):
    type: Literal["function"] = "function"
    arguments: str


class ToolPayloadCustom(BaseModel):
    type: Literal["custom"] = "custom"
    input: str


class ToolPayloadLocalShell(BaseModel):
    type: Literal["local_shell"] = "local_shell"
    params: LocalShellParams


class ToolPayloadMcp(BaseModel):
    type: Literal["mcp"] = "mcp"
    server: str
    tool: str
    raw_arguments: Any
    raw_tool_call_id: str | None = None


ToolPayload = Annotated[
    ToolPayloadFunction | ToolPayloadCustom | ToolPayloadLocalShell | ToolPayloadMcp,
    Field(discriminator="type"),
]


class ToolOutputFunction(BaseModel):
    type: Literal["function"] = "function"
    body: Any | None = None
    success: bool


class ToolOutputMcp(BaseModel):
    type: Literal["mcp"] = "mcp"
    result: Any


ToolOutput = Annotated[
    ToolOutputFunction | ToolOutputMcp,
    Field(discriminator="type"),
]
