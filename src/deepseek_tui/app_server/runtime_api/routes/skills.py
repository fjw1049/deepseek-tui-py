"""GET /v1/skills — discovered skills for Workbench settings/diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.runtime_delegate import runtime_from_request
from deepseek_tui.skills import discover_in_workspace

router = APIRouter(prefix="/v1")


@router.get("/skills")
async def list_skills(request: Request) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    workspace = request.query_params.get("workspace")
    wd = (
        Path(workspace).expanduser().resolve()
        if workspace
        else runtime.working_directory
    )
    skills_dir = Path(runtime.config.skills_dir).expanduser()
    try:
        registry = discover_in_workspace(skills_dir=skills_dir, workspace=wd)
    except (OSError, ValueError) as exc:
        raise api_error(503, f"skill discovery failed: {exc}", error="skills_unavailable") from exc
    return {
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "path": str(skill.path),
            }
            for skill in registry.skills
        ],
        "warnings": registry.warnings,
    }
