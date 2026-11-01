"""Drive one scenario through the real product: HTTP API, Engine, tools, persistence.

Each run owns a server on a throwaway home and each trial a workspace outside the
repository, so the product's AGENTS.md, the user's threads and other cases' files
cannot reach the model. Execution only collects evidence; ``grade_session`` judges
what was collected and can run again later on the saved session.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import socket
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from deepseek_tui.config.paths import user_config_path, user_deepseek_dir
from evals.harness.budget import BudgetExceeded
from evals.judge import judge_session
from evals.rubric import run_checks
from evals.schema import EvalCase, EvalObservation
from evals.session_metrics import load_sessions, run_record, session_metrics, turn_answers

if TYPE_CHECKING:
    from evals.harness import HarnessContext

BOUNDARY = (
    "本任务的输入资料和产物均在当前工作目录。只修改当前目录及其子目录，不要修改用户已有资料，"
    "不要安装软件、提交 Git、对外发布、发消息、付款或创建长期定时任务。"
    "网页可读取公开资料。若缺少权限或能力如实说明，不要伪造成功。\n"
)
# What a user's setup contributes to reaching the model, and nothing that shapes
# its behaviour: no AGENTS.md, skills, plugins, hooks, MCP servers or memories.
_LINKED_FROM_USER_HOME = ("settings.json", "network.json", "secrets")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ACTIVE = {"in_progress", "queued", "running", "pending"}
_UNANSWERED_AFTER_SECONDS = 60
_POLL_SECONDS = 2.0
_SERVER_START_SECONDS = 90
_START_ATTEMPTS = 3
_MAX_CONSECUTIVE_FAILED_TRIALS = 3


class EnvironmentInvalid(RuntimeError):
    """The runtime cannot reach a model; further trials would measure the setup."""


class ProductServer:
    def __init__(self, provider: str | None, model: str | None) -> None:
        self.provider = provider
        self.model = model
        self.root = Path(tempfile.mkdtemp(prefix="deepseek-eval-")).resolve()
        self.home = self.root / "home"
        self.process: asyncio.subprocess.Process | None = None
        self.client: httpx.AsyncClient | None = None
        self.failed_trials = 0

    def _prepare_home(self) -> None:
        self.home.mkdir()
        for name in _LINKED_FROM_USER_HOME:
            source = user_deepseek_dir() / name
            if source.exists():
                (self.home / name).symlink_to(source, target_is_directory=source.is_dir())

    async def start(self) -> None:
        self._prepare_home()
        for _ in range(_START_ATTEMPTS):
            await self._start_process()
            if await self._wait_until_healthy():
                return
            # The probed port can be taken before the server binds it.
            if self.process is None or self.process.returncode is None:
                break
        raise EnvironmentInvalid(f"product server did not start; see {self.root / 'server.log'}")

    async def _start_process(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(24)
        arguments = ["--port", str(port), "--token", token, "--workspace", str(self.root)]
        if self.provider:
            arguments += ["--provider", self.provider]
        if self.model:
            arguments += ["--model", self.model]
        log = open(self.root / "server.log", "ab")  # noqa: ASYNC230 - created beside the home
        try:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "evals.product_server", *arguments,
                cwd=_REPO_ROOT,
                env={
                    **os.environ,
                    "DEEPSEEK_HOME": str(self.home),
                    "DEEPSEEK_CONFIG_PATH": str(user_config_path()),
                    "PYTHONPATH": "src:.",
                },
                stdout=log,
                stderr=log,
            )
        finally:
            log.close()
        self.client = httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
            trust_env=False,
        )

    async def _wait_until_healthy(self) -> bool:
        deadline = time.monotonic() + _SERVER_START_SECONDS
        while time.monotonic() < deadline:
            if self.process.returncode is not None:
                return False
            try:
                if (await self.client.get("/healthz")).status_code == 200:
                    return True
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.5)
        return False

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
            await self.process.wait()
        shutil.rmtree(self.root, ignore_errors=True)

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        assert self.client is not None
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    async def preflight(self) -> None:
        """One real exchange before any trial counts: a run that cannot reach the
        model must stop, not record a batch of failures that look like behaviour."""
        workspace = self.root / "preflight"
        workspace.mkdir()
        thread_id = await self.create_thread(workspace, "eval preflight")
        turn = await self.drive_turn(thread_id, "只回复 OK。", workspace, timeout=120)
        if turn["status"] != "completed":
            raise EnvironmentInvalid(f"preflight turn ended {turn['status']}: {turn['error']}")

    async def create_thread(self, workspace: Path, title: str) -> str:
        created = await self.request(
            "POST",
            "/v1/threads",
            json={
                "provider": self.provider,
                "model": self.model,
                "workspace": str(workspace),
                "title": title,
                "mode": "agent",
                "allow_shell": True,
                "auto_approve": True,
            },
        )
        return created["id"]

    async def drive_turn(
        self, thread_id: str, prompt: str, folder: Path, *, timeout: float
    ) -> dict[str, Any]:
        created = await self.request(
            "POST",
            f"/v1/threads/{thread_id}/turns",
            json={
                "prompt": prompt,
                "provider": self.provider,
                "model": self.model,
                "allow_shell": True,
                "auto_approve": True,
            },
        )
        turn_id = created["turn"]["id"]
        started = time.monotonic()
        waiting_since: float | None = None
        try:
            while True:
                detail = await self.request("GET", f"/v1/threads/{thread_id}")
                turn = next(t for t in detail["turns"] if t["id"] == turn_id)
                if turn["status"] not in _ACTIVE:
                    return {
                        "turn_id": turn_id,
                        "status": turn["status"],
                        "error": turn.get("error"),
                        "elapsed_seconds": round(time.monotonic() - started),
                    }
                pending = [
                    *await self.request("GET", f"/v1/user-inputs/pending?thread_id={thread_id}"),
                    *await self.request("GET", f"/v1/approvals/pending?thread_id={thread_id}"),
                ]
                waiting_since = (waiting_since or time.monotonic()) if pending else None
                unanswered = (
                    waiting_since is not None
                    and time.monotonic() - waiting_since > _UNANSWERED_AFTER_SECONDS
                )
                if unanswered or time.monotonic() - started > timeout:
                    await self._interrupt(thread_id, turn_id)
                    return {
                        "turn_id": turn_id,
                        "status": "needs_user_input" if unanswered else "timeout",
                        "error": None,
                        "elapsed_seconds": round(time.monotonic() - started),
                    }
                await asyncio.sleep(_POLL_SECONDS)
        except asyncio.CancelledError:
            await asyncio.shield(self._interrupt(thread_id, turn_id))
            raise

    async def _interrupt(self, thread_id: str, turn_id: str) -> None:
        await self.request("POST", f"/v1/threads/{thread_id}/turns/{turn_id}/interrupt", json={})
        for _ in range(30):
            detail = await self.request("GET", f"/v1/threads/{thread_id}")
            if next(t for t in detail["turns"] if t["id"] == turn_id)["status"] not in _ACTIVE:
                return
            await asyncio.sleep(1)
        raise EnvironmentInvalid(f"turn {turn_id} did not stop after interrupt")

    def save_session(self, thread_id: str, destination: Path) -> None:
        """Copy one thread's durable records, so grading never needs the server."""
        store = self.home / "threads"
        for name in ("turns", "items", "events", "transcripts"):
            (destination / name).mkdir(parents=True, exist_ok=True)
        for name in ("events", "transcripts"):
            source = store / name / f"{thread_id}.jsonl"
            if source.exists():
                shutil.copy2(source, destination / name)
        for path in (store / "turns").glob("*.json"):
            turn = json.loads(path.read_text(encoding="utf-8"))
            if turn["thread_id"] != thread_id:
                continue
            shutil.copy2(path, destination / "turns")
            for item_id in turn.get("item_ids") or []:
                item = store / "items" / f"{item_id}.json"
                if item.exists():
                    shutil.copy2(item, destination / "items")


def seed_workspace(case: EvalCase, workspace: Path) -> None:
    workspace.mkdir(parents=True)
    (workspace / "AGENTS.md").write_text(BOUNDARY, encoding="utf-8")
    _write_files(workspace, case.setup.get("files", {}))


def _write_files(workspace: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


async def grade_session(
    case: EvalCase,
    session_dir: Path,
    turns: list[dict[str, Any]],
    context: HarnessContext,
    *,
    saved_judge: dict[str, Any] | None = None,
) -> EvalObservation:
    """Everything derived from a finished session; the same on first run and regrade.

    ``saved_judge`` reuses an earlier review, so a change to the deterministic
    checks alone can be applied to old runs without a model call.
    """
    sessions = load_sessions(session_dir)
    session = sessions[0] if sessions else None
    answers = turn_answers(session) if session else []
    metrics = session_metrics(session) if session else {}
    workspace = session_dir / "workspace"
    checks = await asyncio.to_thread(run_checks, case, workspace, answers)
    record = run_record(session) if session else ""
    judge = saved_judge or await judge_session(case, answers, workspace, context, record)
    return EvalObservation(
        data={
            "turns": turns,
            "answers": answers,
            "checks": checks,
            "judge": judge,
            "session": metrics,
            "session_dir": session_dir.name,
            "target": "product_session",
        },
        evidence=["真实产品 HTTP 入口；隔离 home；仓库外工作区；确定性检查 + 独立评审"],
    )


async def run_product_session(case: EvalCase, context: HarnessContext) -> EvalObservation:
    if (
        context.max_input_tokens is not None
        and context.usage.get("input_tokens", 0) >= context.max_input_tokens
    ):
        raise BudgetExceeded("输入 token 预算已用完")
    server = await context.product_server()
    trial = uuid.uuid4().hex[:8]
    workspace = server.root / "workspaces" / f"{case.id}-{trial}"
    seed_workspace(case, workspace)
    thread_id = await server.create_thread(workspace, f"eval {case.id}")
    turns: list[dict[str, Any]] = []
    releases = case.setup.get("release_before_turn", {})
    for number, prompt in enumerate(case.input["turns"], 1):
        _write_files(workspace, releases.get(number, {}))
        turn = await server.drive_turn(
            thread_id, prompt, workspace, timeout=context.turn_timeout_seconds
        )
        turns.append(turn)
        if turn["status"] != "completed":
            break
    # Only a failed model request says anything about the environment: a timeout
    # or an unanswered question is the task's own result.
    last_status = turns[-1]["status"]
    if last_status == "failed":
        server.failed_trials += 1
    elif last_status == "completed":
        server.failed_trials = 0
    if server.failed_trials >= _MAX_CONSECUTIVE_FAILED_TRIALS:
        raise EnvironmentInvalid(f"{server.failed_trials} consecutive turns failed")
    session_dir = context.artifacts_dir / "sessions" / f"{case.id}-{trial}"
    server.save_session(thread_id, session_dir)
    shutil.copytree(
        workspace,
        session_dir / "workspace",
        symlinks=True,
        ignore=shutil.ignore_patterns("node_modules", ".git", ".venv", "__pycache__"),
    )
    (session_dir / "turns.json").write_text(json.dumps(turns), encoding="utf-8")
    observation = await grade_session(case, session_dir, turns, context)
    session = observation.data["session"]
    for key in ("input_tokens", "output_tokens"):
        context.usage[key] = context.usage.get(key, 0) + session.get(key, 0)
    return observation
