"""Budget browser results without cutting observation identities or JSON targets."""

from __future__ import annotations

import json
from typing import Any

ELEMENT_KEYS = {
    "ref",
    "role",
    "tag",
    "name",
    "disabled",
    "checked",
    "selected_text",
    "expanded",
    "type",
    "editable",
    "readonly",
    "selector",
    "href",
    "options",
    "option_offset",
    "total_options",
    "next_option_offset",
    "frame_id",
    "scope",
    "name_truncated",
    "name_offset",
    "next_name_offset",
    "details_truncated",
}
# Omitted when false: the model only needs the exceptions.
DEFAULT_FALSE = ("disabled", "editable", "readonly", "name_truncated", "details_truncated")


def _compact_element(element: dict[str, Any]) -> dict[str, Any]:
    """Drop backend-only identity/geometry and default flags from a model-facing element."""
    item = {k: v for k, v in element.items() if k in ELEMENT_KEYS}
    for key in DEFAULT_FALSE:
        if item.get(key) is False:
            item.pop(key)
    if item.get("tag") in {item.get("role"), "input"}:  # Role and input type already say it.
        item.pop("tag", None)
    if "options" in item:
        item["options"] = [
            {k: v for k, v in o.items() if not (k in {"disabled", "value_omitted"} and v is False)}
            for o in item["options"]
        ]
    return item


class _Scopes:
    """Shared record/row/form context, listed once and referenced by elements."""

    def __init__(self, observation: dict[str, Any]):
        self.table: dict[str, Any] = {}
        self.index: dict[str, str] = {}
        observation["scopes"] = self.table

    def bind(self, item: dict[str, Any]) -> str | None:
        """Replace item's scope with a short ID; return the ID if newly listed."""
        scope = item.get("scope")
        if not isinstance(scope, dict):
            item.pop("scope", None)
            return None
        key = json.dumps(scope, ensure_ascii=False, sort_keys=True)
        added = None
        if key not in self.index:
            added = self.index[key] = "s" + str(len(self.index))
            self.table[added] = scope
        item["scope"] = self.index[key]
        return added

    def unbind(self, added: str | None) -> None:
        if added:
            self.table.pop(added)
            self.index = {k: v for k, v in self.index.items() if v != added}


def project_result(result: dict[str, Any], budget: int) -> str:
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    data = json.loads(encode(result))
    observation = data.get("observation")
    if not isinstance(observation, dict):
        return _bounded_result(data, budget)
    # Older/persisted responses may encode the same observation twice.
    data["content"] = (
        data.get("content", "")
        if not isinstance(data.get("content"), str)
        else (
            "Observation collected" if data["content"].lstrip().startswith("{") else data["content"]
        )
    )
    elements = observation.get("elements", [])
    scopes = _Scopes(observation)
    observation["elements"] = [_compact_element(e) for e in elements]
    for item in observation["elements"]:
        scopes.bind(item)
    if not scopes.table:
        observation.pop("scopes")
    if len(encode(data)) <= budget:
        return encode(data)
    text = observation.get("text", "")
    observation.update(text="", elements=[], context_truncated=True)
    scopes = _Scopes(observation)
    observation["scope_ref"] = observation.get("observation_id")
    for key in ("scope_selector", "scope_shadow_path", "scope_frame_selector"):
        if key in observation and len(encode(observation[key])) > 1000:
            observation.pop(key)
    data["history"] = data.get("history", [])[-3:]
    data["content"] = str(data.get("content", ""))[:1000]
    for key in ("url", "title"):
        if isinstance(observation.get(key), str):
            observation[key] = observation[key][:512]
    observation["warnings"] = [str(w)[:256] for w in observation.get("warnings", [])[:3]]
    frames = observation.get("frames", [])
    observation["frames"] = [
        {k: (v[:256] if isinstance(v, str) and k != "frame_id" else v) for k, v in f.items()}
        for f in frames[:2]
    ]
    if len(frames) > 2:
        observation["next_frame_offset"] = observation.get("frame_offset", 0) + 2
    if "scroll_containers" in observation:
        observation["scroll_containers"] = observation["scroll_containers"][:3]
    if isinstance(data.get("page"), dict):
        data["page"].pop("url", None)  # Already present in the observation.
    if data.get("tabs"):
        data["tabs"] = [
            {k: (v[:256] if isinstance(v, str) and k != "tab_id" else v) for k, v in t.items()}
            for t in sorted(data["tabs"], key=lambda t: not t.get("active"))[:2]
        ]
        data["tabs_truncated"] = len(result["tabs"]) > 2
    for element in elements:
        item = _compact_element(element)
        added = scopes.bind(item)
        for key, value in list(item.items()):
            if key in {"selector", "href"} and isinstance(value, str) and len(value) > 512:
                item.pop(key)  # A shortened selector/URL would refer to a different target.
            elif isinstance(value, str) and key != "ref":
                item[key] = value[: 160 if key in {"name", "selected_text"} else 512]
        if "options" in item:
            item["options"] = [
                {k: v[:128] if k == "text" else v for k, v in o.items()}
                for o in item["options"][:5]
            ]
        observation["elements"].append(item)
        while len(encode(data)) > budget - 1200 and len(item.get("options", [])) > 1:
            item["options"].pop()
        if "options" in item and len(item["options"]) < len(element["options"]):
            item["next_option_offset"] = item.get("option_offset", 0) + len(item["options"])
        # Reserve room for readable text and continuation metadata.
        if len(encode(data)) > budget - 1200:
            observation["elements"].pop()
            scopes.unbind(added)
            if not observation["elements"]:
                observation["elements"].append(
                    {
                        **{k: item[k] for k in ("ref", "role", "name") if k in item},
                        "details_truncated": True,
                    }
                )
            break
    if len(observation["elements"]) < len(elements):
        observation["next_element_offset"] = observation.get("element_offset", 0) + len(
            observation["elements"]
        )
    if not scopes.table:
        observation.pop("scopes")
    available = max(0, budget - len(encode(data)) - 150)
    observation["text"] = text[:available]
    if len(observation["text"]) < len(text):
        observation["next_text_offset"] = observation.get("text_offset", 0) + len(
            observation["text"]
        )
    # Escaped characters can occupy more bytes than their source text.
    while len(encode(data)) > budget and observation["text"]:
        observation["text"] = observation["text"][: len(observation["text"]) // 2]
        observation["next_text_offset"] = observation.get("text_offset", 0) + len(
            observation["text"]
        )
    return _bounded_result(data, budget)


def _bounded_result(data, budget):
    """Every branch is bounded, including status and oversized structural metadata."""

    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    if len(encode(data)) <= budget:
        return encode(data)
    data["context_truncated"] = True
    content = data.get("content")
    if isinstance(content, dict):
        status = {
            k: v
            for k, v in content.items()
            if k
            in {
                "active",
                "owner",
                "generation",
                "healthy",
                "url",
                "viewport",
                "assistance",
                "demo_status",
                "activity",
                "scene",
                "error",
                "unresolved",
                "next_operation_offset",
            }
        }
        status["log_truncated"] = bool(content.get("log"))
        if isinstance(status.get("unresolved"), list):
            status["unresolved_total"] = len(status["unresolved"])
            status["unresolved"] = status["unresolved"][:2]
            if status["unresolved_total"] > 2:
                status["next_operation_offset"] = content.get("operation_offset", 0) + 2
        data["content"] = status
    elif isinstance(content, str):
        data["content"] = content[:500]
    data["history"] = data.get("history", [])[-1:]
    if len(encode(data)) <= budget:
        return encode(data)
    # Preserve executable identities and execution facts; omit unrepresentable details.
    observation = data.get("observation")
    minimal = {
        "success": data.get("success", False),
        "context_truncated": True,
        "content": "Browser details exceed this context budget; use describe or a narrower scope",
    }
    if isinstance(observation, dict):
        minimal["observation"] = {
            k: v
            for k, v in observation.items()
            if k
            in {
                "observation_id",
                "tab_id",
                "document_id",
                "frame_id",
                "frame_document_id",
                "control_generation",
                "scope_ref",
                "viewport",
                "text_offset",
                "element_offset",
                "next_text_offset",
                "next_element_offset",
                "next_frame_offset",
            }
        }
        minimal["observation"]["elements"] = [
            {
                "ref": e["ref"],
                "role": str(e.get("role", ""))[:100],
                "name": str(e.get("name", ""))[:100],
                "details_truncated": True,
            }
            for e in observation.get("elements", [])[:1]
            if "ref" in e
        ]
    receipt = data.get("receipt")
    if isinstance(receipt, dict):
        minimal["receipt"] = {
            k: v
            for k, v in receipt.items()
            if k
            in {
                "action_id",
                "evidence_ref",
                "action",
                "execution",
                "effect",
                "before_observation_id",
                "after_observation_id",
                "observation",
                "evidence",
            }
        }
    if len(encode(minimal)) <= budget:
        return encode(minimal)
    return encode(
        {
            "success": data.get("success", False),
            "context_truncated": True,
            "error": "Identity cannot be represented within this context budget",
        }
    )
