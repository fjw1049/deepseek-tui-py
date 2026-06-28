"""Thread metadata, requests, and responses.

Mirrors Rust types in ``crates/protocol/src/lib.rs:14-185``:

* ``ThreadStatus``                  (lib.rs:14-23)
* ``SessionSource``                 (lib.rs:25-33)
* ``Thread``                        (lib.rs:35-51)
* ``ThreadStartParams``             (lib.rs:53-63)
* ``ThreadResumeParams``            (lib.rs:65-92)
* ``ThreadForkParams``              (lib.rs:94-117)
* ``ThreadListParams``              (lib.rs:119-125)
* ``ThreadReadParams``              (lib.rs:127-130)
* ``ThreadSetNameParams``           (lib.rs:132-136)
* ``ThreadRequest``                 (lib.rs:138-161; ``tag = "kind"``)
* ``ThreadResponse``                (lib.rs:163-185)

The Rust JSON shape uses ``#[serde(tag = "kind", rename_all =
"snake_case")]`` for ``ThreadRequest`` — variants serialise as flat
objects with ``"kind"`` alongside the variant fields::

    {"kind": "create",   "metadata": {...}}
    {"kind": "start",    "model": "...", ...}
    {"kind": "resume",   "thread_id": "...", "history": [...], ...}
    {"kind": "fork",     "thread_id": "...", ...}
    {"kind": "list",     "include_archived": false, "limit": 20}
    {"kind": "read",     "thread_id": "..."}
    {"kind": "set_name", "thread_id": "...", "name": "..."}
    {"kind": "archive",  "thread_id": "..."}
    {"kind": "unarchive","thread_id": "..."}
    {"kind": "message",  "thread_id": "...", "input": "..."}

The unit-like ``Create``/``Start``/etc. variants in Rust are wrappers
around their parameter struct; we collapse the wrapper level so the
JSON is byte-identical to Rust's ``serde`` output.
"""

from __future__ import annotations



from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .events import EventFrame

__all__ = [
    "SessionSource",
    "Thread",
    "ThreadArchiveRequest",
    "ThreadCreateRequest",
    "ThreadForkParams",
    "ThreadForkRequest",
    "ThreadListParams",
    "ThreadListRequest",
    "ThreadMessageRequest",
    "ThreadReadParams",
    "ThreadReadRequest",
    "ThreadRequest",
    "ThreadResponse",
    "ThreadResumeParams",
    "ThreadResumeRequest",
    "ThreadSetNameParams",
    "ThreadSetNameRequest",
    "ThreadStartParams",
    "ThreadStartRequest",
    "ThreadStatus",
    "ThreadUnarchiveRequest",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ThreadStatus(str, Enum):
    """Mirror of Rust ``ThreadStatus`` (lib.rs:14-23)."""

    RUNNING = "running"
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    ARCHIVED = "archived"


class SessionSource(str, Enum):
    """Mirror of Rust ``SessionSource`` (lib.rs:25-33)."""

    INTERACTIVE = "interactive"
    RESUME = "resume"
    FORK = "fork"
    API = "api"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Thread metadata
# ---------------------------------------------------------------------------


class Thread(BaseModel):
    """Mirror of Rust ``Thread`` (lib.rs:35-51)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    preview: str
    ephemeral: bool
    model_provider: str
    created_at: int
    updated_at: int
    status: ThreadStatus
    path: str | None = None
    cwd: str
    cli_version: str
    source: SessionSource
    name: str | None = None


# ---------------------------------------------------------------------------
# Param structs (used both standalone and as ThreadRequest variant bodies)
# ---------------------------------------------------------------------------


class ThreadStartParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    model_provider: str | None = None
    cwd: str | None = None
    persist_extended_history: bool = False


class ThreadResumeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str
    history: list[Any] | None = None
    path: str | None = None
    model: str | None = None
    model_provider: str | None = None
    cwd: str | None = None
    approval_policy: str | None = None
    sandbox: str | None = None
    config: Any | None = None
    base_instructions: str | None = None
    developer_instructions: str | None = None
    personality: str | None = None
    persist_extended_history: bool = False


class ThreadForkParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str
    path: str | None = None
    model: str | None = None
    model_provider: str | None = None
    cwd: str | None = None
    approval_policy: str | None = None
    sandbox: str | None = None
    config: Any | None = None
    base_instructions: str | None = None
    developer_instructions: str | None = None
    persist_extended_history: bool = False
    through_item_id: str | None = None


class ThreadListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_archived: bool = False
    limit: int | None = None


class ThreadReadParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str


class ThreadSetNameParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str
    name: str


# ---------------------------------------------------------------------------
# ThreadRequest variants (tag = "kind", rename_all = "snake_case")
# ---------------------------------------------------------------------------
#
# Rust's serde emits these as flat objects: the parameter struct's fields
# are flattened next to the "kind" tag. We replicate this by building one
# Pydantic model per variant that inlines the relevant fields.


def _flatten(*sources: type[BaseModel]) -> dict[str, Any]:
    """Collect field declarations from multiple BaseModel classes."""
    annotations: dict[str, Any] = {}
    for src in sources:
        annotations.update(src.__annotations__)
    return annotations


class ThreadCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["create"] = "create"
    metadata: Any = Field(default_factory=dict)


class ThreadStartRequest(ThreadStartParams):
    """``ThreadRequest::Start(ThreadStartParams)`` — flat shape."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["start"] = "start"


class ThreadResumeRequest(ThreadResumeParams):
    """``ThreadRequest::Resume(ThreadResumeParams)`` — flat shape."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["resume"] = "resume"


class ThreadForkRequest(ThreadForkParams):
    """``ThreadRequest::Fork(ThreadForkParams)`` — flat shape."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["fork"] = "fork"


class ThreadListRequest(ThreadListParams):
    """``ThreadRequest::List(ThreadListParams)`` — flat shape."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["list"] = "list"


class ThreadReadRequest(ThreadReadParams):
    """``ThreadRequest::Read(ThreadReadParams)`` — flat shape."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["read"] = "read"


class ThreadSetNameRequest(ThreadSetNameParams):
    """``ThreadRequest::SetName(ThreadSetNameParams)`` — flat shape."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["set_name"] = "set_name"


class ThreadArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["archive"] = "archive"
    thread_id: str


class ThreadUnarchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["unarchive"] = "unarchive"
    thread_id: str


class ThreadMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["message"] = "message"
    thread_id: str
    input: str


ThreadRequest = Annotated[
    ThreadCreateRequest
    | ThreadStartRequest
    | ThreadResumeRequest
    | ThreadForkRequest
    | ThreadListRequest
    | ThreadReadRequest
    | ThreadSetNameRequest
    | ThreadArchiveRequest
    | ThreadUnarchiveRequest
    | ThreadMessageRequest,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# ThreadResponse
# ---------------------------------------------------------------------------


class ThreadResponse(BaseModel):
    """Mirror of Rust ``ThreadResponse`` (lib.rs:163-185)."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str
    status: str
    thread: Thread | None = None
    threads: list[Thread] = Field(default_factory=list)
    model: str | None = None
    model_provider: str | None = None
    cwd: str | None = None
    approval_policy: str | None = None
    sandbox: str | None = None
    events: list[EventFrame] = Field(default_factory=list)
    data: Any = Field(default_factory=dict)


# Silence "unused" linter warning while keeping the helper exported for
# subclasses that may want to compose param structs.
_ = _flatten
