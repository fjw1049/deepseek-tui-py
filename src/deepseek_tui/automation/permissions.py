"""User-issued, revocable automation grants, separate from model CRUD inputs."""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from deepseek_tui.utils import write_json_atomic


def _scope(record: dict[str, Any]) -> str:
    payload = {key: record.get(key) for key in ("id", "prompt", "cwds", "digest")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def descriptor(root: Path, automation_id: str) -> dict[str, str]:
    if not automation_id or any(c in automation_id for c in "/\\\0:"):
        raise ValueError("Invalid automation ID")
    return {
        "automation_path": str(root / f"{automation_id}.json"),
        "grant_path": str(root / "state" / "permissions" / f"{automation_id}.json"),
    }


def browser_grant(root: Path, automation_id: str) -> dict[str, str] | None:
    value = descriptor(root, automation_id)
    try:
        value["revision"] = json.loads(Path(value["grant_path"]).read_text())["revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return value if browser_grant_valid(value) else None


def set_browser_permission(root: Path, automation_id: str, enabled: bool) -> None:
    if type(enabled) is not bool:
        raise ValueError("allow_browser must be a boolean")
    value = descriptor(root, automation_id)
    record = json.loads(Path(value["automation_path"]).read_text())
    write_json_atomic(
        Path(value["grant_path"]),
        {
            "allow_browser": enabled,
            "scope": _scope(record),
            "revision": uuid.uuid4().hex,
        },
    )


def browser_grant_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        grant = json.loads(Path(value["grant_path"]).read_text())
        record = json.loads(Path(value["automation_path"]).read_text())
        return (
            grant.get("allow_browser") is True
            and bool(value.get("revision"))
            and grant.get("revision") == value["revision"]
            and grant.get("scope") == _scope(record)
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def browser_authorized(context: Any) -> bool:
    return browser_grant_valid(context.metadata.get("automation_browser_grant"))


class AutomationBrowser:
    """One private service per task; children get distinct sessions and cookies."""

    def __init__(self, data_dir: Path, task_id: str, grant: dict[str, str]) -> None:
        from deepseek_tui.browser.service import BrowserService

        self.service = BrowserService(
            data_dir / "browser" / task_id / "artifacts",
            profile_root=data_dir / "browser" / task_id / "private",
        )
        self.task_id = task_id
        self.grant = grant

    def bind(self, context: Any) -> None:
        context.metadata.update(
            browser_service=self.service,
            runtime_thread_id=f"{self.task_id}-{context.mutation_agent_id or 'main'}",
            automation_browser_grant=dict(self.grant),
        )

    async def close(self) -> None:
        await self.service.close_all()
