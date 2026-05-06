"""Generic IPC envelope.

Mirrors Rust ``Envelope<T>`` (protocol/src/lib.rs:6-12).

The Rust serialisation is::

    {
      "request_id": "...",
      "thread_id": "...",      # omitted if None
      "body": {...}
    }

Pydantic's generic-model support is sufficient — but we have to opt out of
the default exclude_unset/None behaviour for ``thread_id`` so the JSON
shape matches Rust's ``#[serde(skip_serializing_if = "Option::is_none")]``.
Use :meth:`Envelope.model_dump_json` / :meth:`Envelope.model_dump` with
``exclude_none=True`` to match Rust on the wire.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

__all__ = ["Envelope"]

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """Generic IPC envelope: ``{request_id, thread_id?, body}``."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str
    thread_id: str | None = None
    body: T
