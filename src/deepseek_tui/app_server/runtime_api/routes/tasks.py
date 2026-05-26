"""GET/POST /v1/tasks — durable background task queue."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from deepseek_tui.app_server.runtime_api.errors import api_error
from deepseek_tui.app_server.runtime_api.runtime_delegate import (
    runtime_from_request,
    unwrap_runtime_result,
)

router = APIRouter(prefix="/v1")


@router.get("/tasks")
async def list_tasks(request: Request) -> list[dict[str, Any]]:
    runtime = runtime_from_request(request)
    limit_str = request.query_params.get("limit")
    limit = int(limit_str) if limit_str else None
    result = unwrap_runtime_result(await runtime.list_tasks(limit=limit))
    if isinstance(result, dict):
        tasks = result.get("tasks")
        if isinstance(tasks, list):
            return tasks
    if isinstance(result, list):
        return result
    return []


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    result = unwrap_runtime_result(await runtime.get_task(task_id))
    if isinstance(result, dict) and "task" in result:
        task = result["task"]
        if isinstance(task, dict):
            return task
    if isinstance(result, dict):
        return result
    raise api_error(404, f"task not found: {task_id}", error="task_not_found")


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str) -> dict[str, Any]:
    runtime = runtime_from_request(request)
    result = unwrap_runtime_result(await runtime.cancel_task(task_id))
    if isinstance(result, dict) and "task" in result:
        task = result["task"]
        if isinstance(task, dict):
            return task
    if isinstance(result, dict):
        return result
    raise api_error(404, f"task not found: {task_id}", error="task_not_found")
