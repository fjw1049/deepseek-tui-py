"""Read-only time tools for scheduling (mirrors OpenHuman ``current_time``)."""

from __future__ import annotations



from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from deepseek_tui.tools.registry import ToolCapability, ToolError, ToolResult, ToolSpec
from deepseek_tui.tools.registry import ToolContext

__all__ = ["CurrentTimeTool"]


def _timezone_label(tzinfo: object | None) -> str:
    if tzinfo is None:
        return "UTC"
    key = getattr(tzinfo, "key", None)
    if isinstance(key, str) and key.strip():
        return key.strip()
    name = getattr(tzinfo, "tzname", lambda _dt: None)(None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return str(tzinfo)


def _coerce_offset_minutes(raw: object) -> list[int]:
    """Accept ``[2]`` or a single integer ``2`` (common LLM mistake)."""
    if raw is None:
        return []
    if isinstance(raw, bool):
        raise ToolError("offset_minutes entries must be integers")
    if isinstance(raw, int):
        return _validate_offset_list([raw])
    if isinstance(raw, list):
        return _validate_offset_list(raw)
    raise ToolError("offset_minutes must be an integer or array of integers")


def _validate_offset_list(items: list[object]) -> list[int]:
    out: list[int] = []
    for item in items:
        if not isinstance(item, int) or isinstance(item, bool):
            raise ToolError("offset_minutes entries must be integers")
        if item < 0 or item > 60 * 24 * 366:
            raise ToolError("offset_minutes entries must be between 0 and 527040")
        out.append(item)
    return out


def _optional_offset_minutes(input_data: dict[str, object]) -> list[int]:
    return _coerce_offset_minutes(input_data.get("offset_minutes"))


class CurrentTimeTool(ToolSpec):
    def name(self) -> str:
        return "current_time"

    def description(self) -> str:
        return (
            "Get the current date and time in UTC and the machine local timezone. "
            "Pass timezone (e.g. Asia/Shanghai) and offset_minutes (e.g. [1]) for "
            "scheduling. Use in_Nmin_utc for next_run_at and in_Nmin_local when "
            "confirming to the user. Call before automation_create for relative times."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "Optional IANA timezone (e.g. Asia/Shanghai, America/New_York). "
                        "Prefer the user's timezone from the automation playbook."
                    ),
                },
                "offset_minutes": {
                    "description": (
                        "Future offsets in minutes: use [2] for 'in 2 minutes' "
                        "(a single integer 2 is also accepted). "
                        "Returns in_Nmin_utc and in_Nmin_local fields."
                    ),
                    "oneOf": [
                        {"type": "integer"},
                        {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    ],
                },
            },
            "additionalProperties": False,
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, object], context: ToolContext
    ) -> ToolResult:
        _ = context
        now_utc = datetime.now(timezone.utc)
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        now_local = now_utc.astimezone(local_tz)
        local_label = _timezone_label(local_tz)

        payload: dict[str, object] = {
            "utc": now_utc.isoformat(),
            "local": now_local.isoformat(),
            "local_timezone": local_label,
            "unix_seconds": int(now_utc.timestamp()),
        }

        confirm_tz = local_label
        confirm_tzinfo: ZoneInfo | timezone = local_tz  # type: ignore[assignment]

        tz_raw = input_data.get("timezone")
        if isinstance(tz_raw, str) and tz_raw.strip():
            try:
                tz = ZoneInfo(tz_raw.strip())
            except ZoneInfoNotFoundError as exc:
                raise ToolError(f"unknown timezone: {tz_raw}") from exc
            converted = now_utc.astimezone(tz)
            payload["timezone"] = tz_raw.strip()
            payload["in_timezone"] = converted.isoformat()
            confirm_tz = tz_raw.strip()
            confirm_tzinfo = tz

        content_lines = [
            f"utc: {payload['utc']}",
            f"local ({local_label}): {payload['local']}",
            f"user_timezone ({confirm_tz}): {payload.get('in_timezone', payload['local'])}",
            f"unix_seconds: {payload['unix_seconds']}",
        ]

        for minutes in _optional_offset_minutes(input_data):
            future_utc = now_utc + timedelta(minutes=minutes)
            future_local = future_utc.astimezone(confirm_tzinfo)
            utc_key = f"in_{minutes}min_utc"
            local_key = f"in_{minutes}min_local"
            payload[utc_key] = future_utc.isoformat()
            payload[local_key] = future_local.isoformat()
            content_lines.append(f"{utc_key}: {payload[utc_key]}")
            content_lines.append(f"{local_key} ({confirm_tz}): {payload[local_key]}")

        content_lines.append(
            "Use in_Nmin_utc for automation_create.next_run_at; quote in_Nmin_local to the user."
        )
        return ToolResult(success=True, content="\n".join(content_lines), metadata=payload)
