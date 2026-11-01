"""The whole task path against a scripted model: only the model is fake."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from deepseek_tui.engine.transcript import read_transcript
from evals.graders import grade
from evals.harness import HarnessContext
from evals.harness.product import EnvironmentInvalid, ProductServer, run_product_session
from evals.regrade import regrade
from evals.report import append_result, write_json
from evals.schema import EvalCase, TrialResult
from evals.session_metrics import load_sessions, turn_answers

VERDICT = json.dumps({
    "verdict": "pass",
    "criteria": [{"id": 1, "met": True, "evidence": "result.txt 存在"}],
    "claims_complete": True,
    "disclosed_limitations": [],
    "undisclosed_problems": [],
    "reason": "可用",
}, ensure_ascii=False)


def _call(name: str, arguments: dict) -> dict:
    return {"tool_calls": [{
        "index": 0, "id": f"call_{name}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }]}


def script(body: dict) -> dict:
    """Decide the next model reply from what the request contains."""
    if "独立的任务验收人" in str(body.get("messages", [{}])[0]):
        return {"content": VERDICT}
    text = json.dumps(body["messages"], ensure_ascii=False)
    if "只回复 OK" in text:
        return {"content": "OK"}
    if "继续收尾" in text:
        return {"content": "第二轮完成。"}
    if "Shell cannot" not in text:
        return _call("exec_shell", {"command": "rm -f keep.py"})
    if "call_write_file" not in text:
        return _call("write_file", {"path": "result.txt", "content": "done"})
    return {"content": "已完成，结果在 result.txt。"}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.server.model_down:  # type: ignore[attr-defined]
            self.send_error(401)
            return
        delta = script(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        chunks = [
            {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}},
        ]
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def model_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.model_down = False  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "config.toml"
    config.write_text(
        'provider = "fake"\napproval_policy = "auto"\n\n[providers.fake]\n'
        f'protocol = "openai"\nbase_url = "http://127.0.0.1:{server.server_port}/v1"\n'
        'api_key = "test"\nmodel = "fake-model"\n'
    )
    monkeypatch.setenv("DEEPSEEK_CONFIG_PATH", str(config))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    yield server
    server.shutdown()


def make_case() -> EvalCase:
    return EvalCase(
        id="daily.fixture",
        suite="daily_tasks",
        runner="product_session",
        grader="rubric",
        live=True,
        setup={"files": {"keep.py": "print(1)\n"}},
        input={"turns": ["生成 result.txt", "继续收尾"]},
        expect={
            "checks": [
                {"name": "有结果", "type": "file_exists", "glob": "result.txt"},
                {"name": "输入未改动", "type": "unchanged", "paths": ["keep.py"]},
            ],
            "rubric": ["result.txt 存在"],
        },
    )


def context_for(tmp_path: Path) -> HarnessContext:
    return HarnessContext(
        workspace=str(tmp_path),
        provider="fake",
        model="fake-model",
        remaining_live_requests=20,
        turn_timeout_seconds=60,
        artifacts_dir=tmp_path / "run",
    )


async def test_a_task_runs_through_the_product_and_comes_back_graded(
    tmp_path: Path, model_server: ThreadingHTTPServer
) -> None:
    case = make_case()
    context = context_for(tmp_path)
    try:
        observation = await run_product_session(case, context)
        server = await context.product_server()
        repository = Path(__file__).resolve().parents[2]
        assert not server.root.is_relative_to(repository)
    finally:
        await context.close()

    data = observation.data
    assert [turn["status"] for turn in data["turns"]] == ["completed", "completed"]
    assert data["answers"] == ["已完成，结果在 result.txt。", "第二轮完成。"]
    assert all(check["passed"] for check in data["checks"]), data["checks"]
    assert data["session"]["guard_blocks"] == 1
    assert data["session"]["interventions.guard"] == 1
    assert grade(case, observation).passed

    session_dir = tmp_path / "run" / "sessions" / data["session_dir"]
    state = read_transcript(next((session_dir / "transcripts").glob("*.jsonl")))
    assert state is not None and len(state.turn_ids) == 2
    assert state.messages()[-1].text_content() == "第二轮完成。"
    # The boundary reached the model as a project instruction, from the trial itself.
    assert (session_dir / "workspace" / "AGENTS.md").is_file()
    session = load_sessions(session_dir)[0]
    assert turn_answers(session) == data["answers"]


async def test_a_finished_run_can_be_graded_again_without_the_agent(
    tmp_path: Path, model_server: ThreadingHTTPServer
) -> None:
    case = make_case()
    context = context_for(tmp_path)
    try:
        observation = await run_product_session(case, context)
    finally:
        await context.close()
    run = tmp_path / "run"
    write_json(run / "manifest.json", {"run_id": "r", "provider": "fake", "model": "fake-model"})
    append_result(run / "cases.jsonl", TrialResult(
        case_id=case.id, suite=case.suite, risk="medium", trial=1, status="failed",
        duration_ms=1, observation=observation,
    ))
    import evals.regrade as module

    original = module.load_cases
    module.load_cases = lambda: [case]
    try:
        output, summary = await regrade(run, None, None, 5)
    finally:
        module.load_cases = original

    assert summary.passed == 1
    assert (output / "cases.jsonl").is_file()


async def test_a_model_that_cannot_be_reached_stops_the_run_at_preflight(
    tmp_path: Path, model_server: ThreadingHTTPServer
) -> None:
    model_server.model_down = True  # type: ignore[attr-defined]
    server = ProductServer("fake", "fake-model")
    try:
        await server.start()
        with pytest.raises(EnvironmentInvalid):
            await server.preflight()
    finally:
        await server.close()


async def test_repeated_timeouts_do_not_look_like_a_broken_environment(
    tmp_path: Path, model_server: ThreadingHTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = context_for(tmp_path)

    async def timed_out(self, thread_id, prompt, folder, *, timeout):
        return {"turn_id": "t", "status": "timeout", "error": None, "elapsed_seconds": 1}

    server = await context.product_server()
    monkeypatch.setattr(ProductServer, "drive_turn", timed_out)
    try:
        for _ in range(4):
            await run_product_session(make_case(), context)
    finally:
        await context.close()

    assert server.failed_trials == 0


def test_a_trial_does_not_see_skills_from_the_developers_home(tmp_path, monkeypatch) -> None:
    from deepseek_tui.integrations import skills
    from evals.product_server import _USER_SKILL_DIRECTORIES, hide_user_skills

    monkeypatch.setattr(skills.Path, "home", lambda: tmp_path)
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    assert tmp_path / ".agents" / "skills" in skills.skills_directories()
    for name in _USER_SKILL_DIRECTORIES:
        monkeypatch.setattr(skills, name, getattr(skills, name))  # restored after the test
    hide_user_skills()
    assert tmp_path / ".agents" / "skills" not in skills.skills_directories()
