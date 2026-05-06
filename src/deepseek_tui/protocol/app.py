"""App-level RPC requests + responses.

Mirrors Rust ``AppRequest`` (protocol/src/lib.rs:187-197) and
``AppResponse`` (lib.rs:199-205).

Wire shape (``tag = "kind", rename_all = "snake_case"``)::

    {"kind": "capabilities"}
    {"kind": "config_get",   "key": "..."}
    {"kind": "config_set",   "key": "...", "value": "..."}
    {"kind": "config_unset", "key": "..."}
    {"kind": "config_list"}
    {"kind": "models"}
    {"kind": "thread_loaded_list"}
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .events import EventFrame

__all__ = [
    "AppCapabilitiesRequest",
    "AppConfigGetRequest",
    "AppConfigListRequest",
    "AppConfigSetRequest",
    "AppConfigUnsetRequest",
    "AppModelsRequest",
    "AppRequest",
    "AppResponse",
    "AppThreadLoadedListRequest",
]


class AppCapabilitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["capabilities"] = "capabilities"


class AppConfigGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["config_get"] = "config_get"
    key: str


class AppConfigSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["config_set"] = "config_set"
    key: str
    value: str


class AppConfigUnsetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["config_unset"] = "config_unset"
    key: str


class AppConfigListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["config_list"] = "config_list"


class AppModelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["models"] = "models"


class AppThreadLoadedListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["thread_loaded_list"] = "thread_loaded_list"


AppRequest = Annotated[
    AppCapabilitiesRequest
    | AppConfigGetRequest
    | AppConfigSetRequest
    | AppConfigUnsetRequest
    | AppConfigListRequest
    | AppModelsRequest
    | AppThreadLoadedListRequest,
    Field(discriminator="kind"),
]


class AppResponse(BaseModel):
    """Mirror of Rust ``AppResponse`` (lib.rs:199-205)."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: Any = Field(default_factory=dict)
    events: list[EventFrame] = Field(default_factory=list)
