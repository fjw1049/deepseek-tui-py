"""Thread-owned remote PTYs backed by the shared Workbench terminal core."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deepseek_tui.workspace.execution import execution_root

router = APIRouter(prefix="/v1/threads/{thread_id}/terminal", tags=["terminal"])


class CreateTerminal(BaseModel):
    confirm: bool = False
    cols: int = Field(default=80, ge=2, le=240)
    rows: int = Field(default=24, ge=1, le=100)


class TerminalInput(BaseModel):
    data: str = Field(max_length=8192)


class TerminalSize(BaseModel):
    cols: int = Field(ge=2, le=240)
    rows: int = Field(ge=1, le=100)


class TerminalBridge:
    def __init__(self):
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.sequence = 0

    async def close(self):
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def call(self, payload: dict) -> object:
        async with self.lock:
            if self.process is None or self.process.returncode is not None:
                helper = Path(os.environ.get("DEEPSEEK_MOBILE_TERMINAL_HELPER", ""))
                if not helper.is_file():
                    raise HTTPException(503, "电脑尚未安装终端适配服务")
                self.process = await asyncio.create_subprocess_exec(
                    os.environ.get("MOBILE_NODE_BINARY", "node"), str(helper),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, limit=1_000_000,
                )
            self.sequence += 1
            assert self.process.stdin and self.process.stdout
            try:
                self.process.stdin.write((json.dumps({**payload, "id": self.sequence}) + "\n").encode())
                await self.process.stdin.drain()
                line = await asyncio.wait_for(self.process.stdout.readline(), 10)
                result = json.loads(line)
                if result.get("id") != self.sequence:
                    raise ValueError("Terminal transport out of sync")
            except (TimeoutError, ValueError, BrokenPipeError, ConnectionResetError) as exc:
                await self.close()
                raise HTTPException(503, "终端连接已中断，请重新打开终端") from exc
            if not result.get("ok"):
                raise HTTPException(409, result.get("message", "终端操作失败"))
            return result.get("result")


def _service(request: Request, thread_id: str) -> tuple[TerminalBridge, str]:
    try:
        thread = request.app.state.thread_manager.store.load_thread(thread_id)
        root = execution_root(thread).resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(404, "会话或工作区不存在") from exc
    if not hasattr(request.app.state, "mobile_terminal"):
        request.app.state.mobile_terminal = TerminalBridge()
    return request.app.state.mobile_terminal, str(root)


async def close_mobile_terminals(app):
    service = getattr(app.state, "mobile_terminal", None)
    if service:
        await service.close()


@router.get("")
async def terminal_list(request: Request, thread_id: str):
    service, _ = _service(request, thread_id)
    return await service.call({"action": "list", "thread_id": thread_id})


@router.post("")
async def terminal_create(request: Request, thread_id: str, body: CreateTerminal):
    if body.confirm is not True:
        raise HTTPException(400, "请确认：终端直接以电脑用户权限执行 Shell 命令，不经过 Agent 工具审批")
    service, root = _service(request, thread_id)
    return await service.call({"action": "create", "thread_id": thread_id, "cwd": root, **body.model_dump()})


@router.get("/{session_id}")
async def terminal_read(request: Request, thread_id: str, session_id: str, offset: int = 0):
    service, _ = _service(request, thread_id)
    return await service.call({"action": "read", "thread_id": thread_id, "session_id": session_id, "offset": offset})


@router.post("/{session_id}/input")
async def terminal_write(request: Request, thread_id: str, session_id: str, body: TerminalInput):
    service, _ = _service(request, thread_id)
    return await service.call({"action": "write", "thread_id": thread_id, "session_id": session_id, "data": body.data})


@router.post("/{session_id}/resize")
async def terminal_resize(request: Request, thread_id: str, session_id: str, body: TerminalSize):
    service, _ = _service(request, thread_id)
    return await service.call({"action": "resize", "thread_id": thread_id, "session_id": session_id, **body.model_dump()})


@router.delete("/{session_id}")
async def terminal_close(request: Request, thread_id: str, session_id: str):
    service, _ = _service(request, thread_id)
    return await service.call({"action": "close", "thread_id": thread_id, "session_id": session_id})
