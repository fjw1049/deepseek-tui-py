"""Retry only the explicit token-limit parameter compatibility error."""
import json
from typing import Any


def adapt_completion_tokens(status: int, body: str, payload: dict[str, Any]) -> bool:
    if status != 400 or "max_tokens" not in payload or "max_completion_tokens" in payload:
        return False
    try:
        error = json.loads(body)["error"]
        compatible = (
            error.get("param") == "max_tokens"
            and error.get("code") == "unsupported_parameter"
            and "max_completion_tokens" in error.get("message", "")
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return False
    if compatible:
        payload["max_completion_tokens"] = payload.pop("max_tokens")
        return True
    return False
