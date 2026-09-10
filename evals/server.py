"""Independent loopback-only eval application. Never mounts Workbench routes."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from evals.experiments import compare_runs
from evals.report import redact, write_json
from evals.runner import DEFAULT_ARTIFACTS_ROOT, REPO_ROOT, load_cases, validate_cases

STATIC = Path(__file__).parent / "web"


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="", max_length=100)
    mode: Literal["offline", "live"] = "offline"
    case_ids: list[str] = Field(min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=150)
    trials: int = Field(default=1, ge=1, le=20)
    max_live_requests: int = Field(default=20, ge=1, le=1000)
    max_output_tokens: int = Field(default=2048, ge=16, le=16384)
    max_cost_usd: float | None = Field(default=None, gt=0, le=1000)
    timeout_seconds: float = Field(default=120, ge=5, le=1800)
    prompt_suffix: str = Field(default="", max_length=16000)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class Experiments:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.jobs = self.root / "_jobs"
        self.active: dict[str, asyncio.subprocess.Process] = {}
        self.monitors: set[asyncio.Task[None]] = set()
        self.lock = asyncio.Lock()

    def path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", run_id):
            raise HTTPException(400, "无效实验 ID")
        path = self.root / run_id
        if path.is_symlink():
            raise HTTPException(400, "不支持符号链接实验目录")
        return path

    def detail(self, run_id: str) -> dict[str, Any]:
        path = self.path(run_id)
        manifest = read_json(path / "manifest.json")
        job = read_json(self.jobs / f"{run_id}.json", {})
        if manifest is None and not job:
            raise HTTPException(404, "实验不存在")
        summary = read_json(path / "summary.json")
        rows = []
        if (path / "cases.jsonl").exists():
            for line in (path / "cases.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # A worker can be in the middle of its final append.
        status = job.get("status", "completed" if summary else "interrupted")
        if status in {"running", "stopping"} and run_id not in self.active:
            status = "interrupted"
        return cast(
            dict[str, Any],
            redact(
                {
                    "id": run_id,
                    "manifest": manifest or {},
                    "summary": summary,
                    "cases": rows,
                    "status": status,
                    "error": job.get("error"),
                    "label": job.get("label")
                    or (manifest or {}).get("settings", {}).get("label")
                    or run_id,
                }
            ),
        )

    def listing(self) -> list[dict[str, Any]]:
        ids = {p.parent.name for p in self.root.glob("*/manifest.json")}
        ids.update(p.stem for p in self.jobs.glob("*.json") if not p.name.endswith(".request.json"))
        return [
            {k: v for k, v in self.detail(i).items() if k != "cases"}
            for i in sorted(ids, reverse=True)
        ]

    async def start(self, spec: StartRequest) -> str:
        corpus = load_cases()
        selected = [c for c in corpus if c.id in spec.case_ids]
        if len(set(spec.case_ids)) != len(spec.case_ids) or len(selected) != len(spec.case_ids):
            raise HTTPException(400, "场景不存在或重复")
        if validate_cases(selected):
            raise HTTPException(400, "场景校验失败")
        if spec.mode == "offline" and any(c.live for c in selected):
            raise HTTPException(400, "离线模式不能运行真实模型场景")
        if spec.mode == "live" and any(not c.live for c in selected):
            raise HTTPException(400, "请分开运行离线机制与真实模型场景")
        if spec.prompt_suffix and (
            spec.mode == "offline" or any(c.runner == "live_cache" for c in selected)
        ):
            raise HTTPException(400, "提示词补充仅适用于真实决策或文件任务，不适用于离线/缓存探针")
        if spec.mode == "live":
            from deepseek_tui.client.factory import build_llm_client
            from deepseek_tui.config.loader import ConfigLoader

            try:
                cfg = ConfigLoader().load(
                    provider=spec.provider,
                    model=spec.model,
                    workspace=REPO_ROOT,
                    no_project_config=True,
                )
                client = build_llm_client(cfg)
                await client.close()  # Configuration check only, no API request.
                spec = spec.model_copy(
                    update={"provider": cfg.provider, "model": cfg.model or cfg.default_text_model}
                )
            except Exception:
                raise HTTPException(
                    400, "模型配置不可用，请先在用户级配置中设置对应 provider、模型和 API Key"
                ) from None
        async with self.lock:
            if self.active:
                raise HTTPException(409, "已有实验运行中，请等待或停止后再开始")
            self.jobs.mkdir(parents=True, exist_ok=True)
            run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
            payload = spec.model_dump()
            payload["output_dir"] = str(self.path(run_id))
            request_path = self.jobs / f"{run_id}.request.json"
            write_json(request_path, payload)
            env = dict(os.environ)
            env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
            env["PYTHONUNBUFFERED"] = "1"
            log = (self.jobs / f"{run_id}.log").open("wb")
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "evals.worker",
                    str(request_path),
                    cwd=REPO_ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
            finally:
                log.close()
            self.active[run_id] = process
            write_json(self.jobs / f"{run_id}.json", {"status": "running", "label": spec.label})
            monitor = asyncio.create_task(self.monitor(run_id, process))
            self.monitors.add(monitor)
            monitor.add_done_callback(self.monitors.discard)
            return run_id

    async def monitor(self, run_id: str, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        state_path = self.jobs / f"{run_id}.json"
        state = read_json(state_path, {})
        state["status"] = (
            "cancelled"
            if state.get("status") == "stopping"
            else "completed"
            if code == 0
            else "error"
        )
        if code != 0 and state["status"] == "error":
            state["error"] = "评测进程异常退出；已完成结果已保留，请查看本地 _jobs 日志。"
        write_json(state_path, state)
        self.active.pop(run_id, None)

    async def stop(self, run_id: str) -> None:
        self.path(run_id)
        process = self.active.get(run_id)
        if process is None:
            raise HTTPException(409, "实验当前未运行")
        path = self.jobs / f"{run_id}.json"
        state = read_json(path, {})
        state["status"] = "stopping"
        write_json(path, state)
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=8)
        except TimeoutError:
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def close(self) -> None:
        for run_id in list(self.active):
            await self.stop(run_id)
        if self.monitors:
            try:
                await asyncio.wait_for(asyncio.gather(*list(self.monitors)), timeout=8)
            except TimeoutError:
                for process in self.active.values():
                    if process.returncode is None:
                        process.kill()
                await asyncio.gather(*(p.wait() for p in self.active.values()))


def create_app(artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT) -> FastAPI:
    service = Experiments(artifacts_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await service.close()

    app = FastAPI(
        title="Eval Lab", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.experiments = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def local_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            expected = urlsplit(str(request.base_url)).netloc
            if (
                origin
                and (urlsplit(origin).netloc != expected or urlsplit(origin).scheme != "http")
            ) or request.headers.get("x-eval-request") != "1":
                return JSONResponse({"detail": "仅允许本地评测页面发起操作"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.get("/api/bootstrap")
    async def bootstrap() -> dict[str, Any]:
        from deepseek_tui.config.loader import ConfigLoader

        defaults = {"provider": "deepseek", "model": "", "providers": []}
        try:
            cfg = ConfigLoader().load(workspace=REPO_ROOT, no_project_config=True)
            defaults = {
                "provider": cfg.provider,
                "model": cfg.model or cfg.default_text_model,
                "providers": sorted(set(cfg.providers) | {cfg.provider}),
            }
        except Exception:
            pass
        return {"cases": [c.model_dump(mode="json") for c in load_cases()], "defaults": defaults}

    @app.get("/api/runs")
    async def runs() -> list[dict[str, Any]]:
        return service.listing()

    @app.post("/api/runs", status_code=202)
    async def start(spec: StartRequest) -> dict[str, str]:
        return {"id": await service.start(spec)}

    @app.get("/api/compare")
    async def compare(a: str, b: str) -> dict[str, Any]:
        if a == b:
            raise HTTPException(400, "请选择两个不同的实验")
        return compare_runs(service.detail(a), service.detail(b))

    @app.get("/api/runs/{run_id}")
    async def detail(run_id: str) -> dict[str, Any]:
        return service.detail(run_id)

    @app.post("/api/runs/{run_id}/stop", status_code=202)
    async def stop(run_id: str) -> dict[str, str]:
        await service.stop(run_id)
        return {"status": "stopping"}

    @app.get("/api/runs/{run_id}/trace/{case_id}/{trial}")
    async def trace(run_id: str, case_id: str, trial: int) -> Any:
        detail = service.detail(run_id)
        if not any(row["case_id"] == case_id and row["trial"] == trial for row in detail["cases"]):
            raise HTTPException(404, "试验不存在")
        return redact(
            read_json(service.path(run_id) / "traces" / f"{case_id}-trial-{trial}.json", [])
        )

    @app.get("/api/runs/{run_id}/export")
    async def export(run_id: str) -> JSONResponse:
        data = service.detail(run_id)
        data["traces"] = {
            f"{row['case_id']}/{row['trial']}": await trace(run_id, row["case_id"], row["trial"])
            for row in data["cases"]
        }
        return JSONResponse(
            data, headers={"Content-Disposition": f'attachment; filename="eval-{run_id}.json"'}
        )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
