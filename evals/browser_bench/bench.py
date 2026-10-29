"""Browser-use bench: widget coverage, observation cost and real-model tasks.

Every mode imports the product from ``--src`` so a baseline checkout and the
working tree run the identical bench. Results are verified only from events the
fixture pages post to the local server, or from the final answer text.

    python evals/browser_bench/bench.py offline --src src --out after-offline.json
    python evals/browser_bench/bench.py live --src src --repeats 2 --out after-live.json
    python evals/browser_bench/bench.py compare before.json after.json
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class Server:
    """Serves the fixtures and records what each page reports, isolated per task."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        events = self.events

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(FIXTURES), **kwargs)

            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("content-length") or 0))
                events.append(json.loads(body or b"{}"))
                self.send_response(204)
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, page: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/{page}"

    def close(self) -> None:
        self.httpd.shutdown()


def new_service():
    from deepseek_tui.browser.service import BrowserService

    root = Path(tempfile.mkdtemp(prefix="browser-bench-"))
    service = BrowserService(root / "artifacts", profile_root=root / "private")
    return service


async def act(service, thread: str, **arguments) -> dict[str, Any]:
    from deepseek_tui.browser.service import BrowserAction, BrowserActionError

    try:
        return await service.action(thread, BrowserAction(**arguments), require_observation=True)
    except BrowserActionError as exc:
        return exc.response


def model_chars(response: dict[str, Any]) -> int:
    """Size of what the model receives for this result, before any context budget."""
    from deepseek_tui.browser.context import project_result

    return len(project_result(response, 10**9))


# Widget id -> how a user would operate it.
WIDGETS = {f"W{i:02d}": "click" for i in range(1, 21)}
WIDGETS.update(W02="check", W03="check", W16="check", W09="slider")


async def coverage(service) -> dict[str, Any]:
    server = Server()
    thread = "coverage"
    service.configure(thread, persistent=False)
    rows = {}
    try:
        response = await act(service, thread, action="open", url=server.url("widgets.html"))
        for widget, kind in WIDGETS.items():
            observation = response.get("observation") or (
                await act(service, thread, action="observe"))["observation"]
            element = next((e for e in observation["elements"]
                            if str(e.get("name", "")).startswith(widget + " ")), None)
            row = {"detected": element is not None, "operable": False}
            if element:
                target = {"ref": element["ref"], "observation_id": observation["observation_id"]}
                if kind == "check":
                    response = await act(service, thread, action="set_checked", checked=True, **target)
                elif kind == "slider":
                    response = await act(service, thread, action="press", key="ArrowRight", **target)
                else:
                    response = await act(service, thread, action="click", **target)
                await asyncio.sleep(0.3)
                row["operable"] = any(e.get("id") == widget for e in server.events)
                if not row["operable"]:
                    row["error"] = str(response.get("content", ""))[:200]
            else:
                response = {}
            rows[widget] = row
    finally:
        await service.close(thread)
        server.close()
    return {
        "widgets": rows,
        "detected": sum(r["detected"] for r in rows.values()),
        "operable": sum(r["operable"] for r in rows.values()),
        "total": len(rows),
    }


async def cost(service) -> dict[str, Any]:
    server = Server()
    results = {}
    try:
        for page, action in (("orders.html", "Edit"), ("products.html", "Next"),
                             ("cards.html", None), ("widgets.html", "W01 Native button")):
            thread = "cost-" + page
            service.configure(thread, persistent=False)
            try:
                opened = await act(service, thread, action="open", url=server.url(page))
                observed = await act(service, thread, action="observe")
                row = {"open_chars": model_chars(opened), "observe_chars": model_chars(observed)}
                if action:
                    observation = observed["observation"]
                    element = next(e for e in observation["elements"]
                                   if str(e.get("name", "")).startswith(action))
                    clicked = await act(service, thread, action="click", ref=element["ref"],
                                        observation_id=observation["observation_id"])
                    row["after_click_chars"] = model_chars(clicked)
                results[page] = row
            finally:
                await service.close(thread)
    finally:
        server.close()
    return results


def find(observation: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((e for e in observation["elements"] if str(e.get("name", "")).startswith(name)), None)


async def features(service) -> dict[str, bool]:
    """Deterministic scripted use of per-key typing, dragging and console reading."""
    server = Server()
    results = {}

    async def scripted(name, page, steps):
        thread = "feature-" + name
        service.configure(thread, persistent=False)
        try:
            response = await act(service, thread, action="open", url=server.url(page))
            results[name] = bool(await steps(thread, response["observation"]))
        except Exception as exc:  # noqa: BLE001 - an unsupported feature is a failed check
            results[name] = False
            results[name + "_error"] = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            await service.close(thread)

    async def invite(thread, observation):
        first = find(observation, "Character 1")
        typed = await act(service, thread, action="type", text="K7Q2MX", ref=first["ref"],
                          observation_id=observation["observation_id"])
        observation = (await act(service, thread, action="observe"))["observation"]
        await act(service, thread, action="click", ref=find(observation, "Join")["ref"],
                  observation_id=observation["observation_id"])
        await asyncio.sleep(0.3)
        return typed.get("success") and any(e.get("code") == "K7Q2MX" for e in server.events)

    async def kanban(thread, observation):
        card, drop = find(observation, "Write release notes"), find(observation, "Set up CI")
        await act(service, thread, action="drag", ref=card["ref"], to_ref=drop["ref"],
                  observation_id=observation["observation_id"])
        await asyncio.sleep(0.3)
        return any(e.get("column") == "done" for e in server.events)

    async def console(thread, observation):
        clicked = await act(service, thread, action="click", ref=find(observation, "Save draft")["ref"],
                            observation_id=observation["observation_id"])
        logs = await act(service, thread, action="console")
        return "42 KB" in json.dumps(logs, ensure_ascii=False) and "42 KB" in json.dumps(
            clicked.get("console_errors"), ensure_ascii=False)

    try:
        await scripted("type_keystrokes", "invite.html", invite)
        await scripted("drag", "kanban.html", kanban)
        await scripted("console", "console.html", console)
    finally:
        server.close()
    return results


async def offline(args) -> dict[str, Any]:
    service = new_service()
    try:
        return {"coverage": await coverage(service), "features": await features(service),
                "cost": await cost(service)}
    finally:
        await service.close_all()


def answer_has(*needles: str):
    return lambda events, answer: all(n.lower() in answer.lower() for n in needles)


def last_event(kind: str, **expected):
    def check(events, answer):
        found = [e for e in events if e.get("type") == kind]
        return bool(found) and all(found[-1].get(k) == v for k, v in expected.items())
    return check


def both(*checks):
    return lambda events, answer: all(c(events, answer) for c in checks)


TASKS = {
    "form": ("form.html",
             "在 {url} 注册账号：姓名 Lin Chen，邮箱 lin.chen@example.com，选择 Team 套餐，"
             "勾选订阅 newsletter，然后提交。",
             last_event("submit", name="Lin Chen", email="lin.chen@example.com", plan="team",
                        newsletter=True)),
    "orders": ("orders.html", "在 {url} 删除客户 Hana Ito 的订单（页面会要求确认删除）。",
               lambda events, answer: [e.get("id") for e in events if e.get("type") == "delete"]
               == ["1027"]),
    "settings": ("settings.html", "在 {url} 打开邮件通知（Email notifications），把音量调到 7，然后保存设置。",
                 last_event("save", notify=True, volume=7)),
    "cards": ("cards.html", "打开 {url}，点开订单 #1042 的卡片，告诉我它的物流单号（Tracking code）。",
              both(last_event("open", id="1042"),
                   answer_has((FIXTURES / "cards.answer").read_text().strip()))),
    "console": ("console.html",
                "{url} 是我本地开发中的页面。点击 Save draft 后出错了，请告诉我浏览器控制台里具体的错误信息。",
                answer_has("42 KB", "DraftStore")),
    "invite": ("invite.html", "在 {url} 输入邀请码 K7Q2MX 并加入工作区。",
               last_event("join", code="K7Q2MX")),
    "kanban": ("kanban.html", "在 {url} 把卡片 “Write release notes” 拖到 Done 列。",
               last_event("move", card="Write release notes", column="done")),
    "products": ("products.html", "在 {url} 的库存表里，哪个商品库存为 0？告诉我它的名字和价格。",
                 answer_has("Lamp Quartz Ember", "42")),
}


async def live_task(name: str, cfg, semaphore) -> dict[str, Any]:
    from deepseek_tui.client.base import LLMClient, RetryConfig
    from deepseek_tui.client.factory import build_llm_client
    from deepseek_tui.client.pricing import calculate_turn_cost_estimate_from_usage
    from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.engine.prompts import AppMode, build_system_prompt
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import StreamDone
    from deepseek_tui.tools.browser import BrowserUseTool
    from deepseek_tui.tools.registry import ToolContext, ToolRegistry
    from deepseek_tui.tools.task_delivery import FinishTaskTool, RequestTaskToolsTool

    meter = {"requests": 0, "input_tokens": 0, "cache_read_input_tokens": 0,
             "output_tokens": 0, "cost_usd": 0.0}

    class Metered(LLMClient):
        def __init__(self, inner):
            super().__init__(retry_config=RetryConfig(max_transparent_retries=0, max_error_retries=0))
            self.inner = inner

        def cache_fingerprint_units(self, request):
            return self.inner.cache_fingerprint_units(request)

        async def close(self):
            await self.inner.close()

        async def stream_chat_completion(self, request):
            meter["requests"] += 1
            async for event in self.inner.stream_chat_completion(request):
                if isinstance(event, StreamDone) and event.usage is not None:
                    meter["input_tokens"] += event.usage.total_input_tokens
                    meter["cache_read_input_tokens"] += event.usage.cache_read_input_tokens
                    meter["output_tokens"] += event.usage.output_tokens
                    estimate = calculate_turn_cost_estimate_from_usage(request.model, event.usage)
                    meter["cost_usd"] += estimate.usd if estimate else 0
                yield event

    calls: dict[str, int] = {}
    errors: list[str] = []
    timeline: list[list[Any]] = []  # [seconds since start, tool, duration, success]

    class CountingRegistry(ToolRegistry):
        async def execute(self, tool, input_data, context):
            label = tool if tool != "browser_use" else "browser_use:" + str(input_data.get("action"))
            calls[label] = calls.get(label, 0) + 1
            began = time.monotonic()
            result = await super().execute(tool, input_data, context)
            timeline.append([round(began - started, 1), label, round(time.monotonic() - began, 1),
                             result.success])
            if not result.success:
                errors.append(f"{label}: {str(result.content)[:160]}")
            return result

    page, prompt, verify = TASKS[name]
    async with semaphore:
        server = Server()
        service = new_service()
        client = Metered(build_llm_client(cfg))
        started = time.monotonic()
        answer, outcome = "", "error"
        try:
            with tempfile.TemporaryDirectory(prefix="browser-bench-task-") as tmp:
                thread = "live-" + name
                service.configure(thread, persistent=False)
                registry = CountingRegistry()
                registry.register_all([BrowserUseTool(), FinishTaskTool(), RequestTaskToolsTool()])
                context = ToolContext(working_directory=Path(tmp), metadata={
                    "browser_service": service, "runtime_thread_id": thread})
                engine = Engine(handle=EngineHandle(), client=client, tool_registry=registry,
                                tool_context=context, approval_handler=AutoApprovalHandler(),
                                max_tool_round_trips=40,
                                default_model=cfg.model or cfg.default_text_model)
                system = build_system_prompt(mode=AppMode.AGENT, workspace=Path(tmp),
                                             project_context_enabled=False,
                                             browser_guidelines=True, auto_approve=True)
                turn = asyncio.create_task(engine._run_conversation(
                    [Message.user(prompt.format(url=server.url(page)))],
                    engine.default_model, system, 8192))
                done, _ = await asyncio.wait({turn}, timeout=900)
                if not done:
                    # Where the turn waits is the diagnosis; keep the innermost frames.
                    import io
                    import traceback

                    stack = io.StringIO()
                    turn.print_stack(limit=None, file=stack)
                    errors.append("stuck: " + stack.getvalue()[-1500:])
                    turn.cancel()
                    await asyncio.gather(turn, return_exceptions=True)
                    raise TimeoutError("turn exceeded 900s")
                result = turn.result()
                outcome = result.outcome.value
                answer = (result.task_outcome or {}).get("answer") or (
                    result.assistant_message.text_content() if result.assistant_message else "")
        except Exception as exc:  # noqa: BLE001 - the bench reports every failure as data
            errors.append(f"run: {type(exc).__name__}: {exc}"[:300])
        finally:
            await asyncio.sleep(0.3)
            events = list(server.events)
            await service.close_all()
            await client.close()
            server.close()
    return {
        "task": name, "passed": bool(verify(events, answer)), "outcome": outcome,
        "seconds": round(time.monotonic() - started, 1), "browser_calls": sum(
            v for k, v in calls.items() if k.startswith("browser_use")),
        "calls": calls, "timeline": timeline, "events": events, "answer": answer[:600], "errors": errors[-6:], **meter,
    }


async def live(args) -> dict[str, Any]:
    from deepseek_tui.config.loader import ConfigLoader

    cfg = ConfigLoader().load(workspace=Path(tempfile.gettempdir()), no_project_config=True,
                              **({"model": args.model} if args.model else {}))
    semaphore = asyncio.Semaphore(args.parallel)
    names = args.tasks.split(",") if args.tasks else list(TASKS)
    runs = await asyncio.gather(*(live_task(n, cfg, semaphore)
                                  for n in names for _ in range(args.repeats)))
    return {"model": cfg.model or cfg.default_text_model, "runs": runs}


def summarize_live(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    table: dict[str, dict[str, float]] = {}
    for run in data["runs"]:
        row = table.setdefault(run["task"], {"n": 0, "passed": 0, "browser_calls": 0,
                                             "input_tokens": 0, "cost_usd": 0, "seconds": 0})
        row["n"] += 1
        for key in ("passed", "browser_calls", "input_tokens", "cost_usd", "seconds"):
            row[key] += run[key]
    return table


def compare(before: dict[str, Any], after: dict[str, Any]) -> None:
    if "coverage" in before:
        b, a = before["coverage"], after["coverage"]
        print(f"widgets detected  {b['detected']}/{b['total']} -> {a['detected']}/{a['total']}")
        print(f"widgets operable  {b['operable']}/{b['total']} -> {a['operable']}/{a['total']}")
        for widget in a["widgets"]:
            x, y = b["widgets"][widget], a["widgets"][widget]
            if (x["detected"], x["operable"]) != (y["detected"], y["operable"]):
                print(f"  {widget}: detected {x['detected']}->{y['detected']} "
                      f"operable {x['operable']}->{y['operable']}")
        for name, ok in after.get("features", {}).items():
            if not name.endswith("_error"):
                print(f"feature {name:16} {before.get('features', {}).get(name)} -> {ok}")
        for page, row in after["cost"].items():
            print(page, {k: f"{before['cost'][page].get(k)} -> {v}" for k, v in row.items()})
    if "runs" in before:
        b, a = summarize_live(before), summarize_live(after)
        print(f"{'task':10} {'pass':>11} {'browser calls':>15} {'input tokens':>19} {'seconds':>13}")
        totals = [0, 0, 0, 0]
        for task in a:
            x, y = b.get(task), a[task]
            if not x:
                continue
            print(f"{task:10} {x['passed']:>4}/{x['n']} -> {y['passed']}/{y['n']}"
                  f" {x['browser_calls'] / x['n']:6.1f} -> {y['browser_calls'] / y['n']:5.1f}"
                  f" {x['input_tokens'] / x['n']:8.0f} -> {y['input_tokens'] / y['n']:7.0f}"
                  f" {x['seconds'] / x['n']:5.0f} -> {y['seconds'] / y['n']:4.0f}")
            totals = [totals[0] + x["passed"], totals[1] + y["passed"],
                      totals[2] + x["n"], totals[3] + y["n"]]
        print(f"overall pass {totals[0]}/{totals[2]} -> {totals[1]}/{totals[3]}; "
              f"cost ${sum(r['cost_usd'] for r in before['runs']):.3f} -> "
              f"${sum(r['cost_usd'] for r in after['runs']):.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["offline", "live", "compare"])
    parser.add_argument("files", nargs="*")
    parser.add_argument("--src", default=str(Path(__file__).resolve().parents[2] / "src"))
    parser.add_argument("--out")
    parser.add_argument("--tasks", default="")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    if args.mode == "compare":
        before, after = (json.loads(Path(f).read_text()) for f in args.files)
        compare(before, after)
        return
    sys.path.insert(0, str(Path(args.src).resolve()))
    result = asyncio.run(offline(args) if args.mode == "offline" else live(args))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text)
    print(text[:4000])


if __name__ == "__main__":
    main()
