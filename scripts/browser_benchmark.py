"""Local browser behavior and real primary-model tasks; JSON evidence, no account data.

Run with PYTHONPATH=src .venv/bin/python scripts/browser_benchmark.py --real-model
--output /absolute/path/results.json. Uses the configured provider only when requested.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock

from deepseek_tui.browser.context import project_result
from deepseek_tui.browser.observation import evaluate
from deepseek_tui.browser.service import BrowserAction, BrowserService


def fixture(language, variant):
    labels = {
        "en": ("Record A", "Record B", "Draft", "Save", "Saved"),
        "zh": ("记录 A", "记录 B", "草稿", "保存", "已保存"),
    }[language]
    a, b, field, save, saved = labels
    sections = [
        f"<section data-record='{record}'><h2>{title}</h2>"
        f"<label for='draft{record}'>{field}</label><input id='draft{record}'>"
        f"<button onclick=\"saveRecord('{record}')\">{save}</button>"
        f"<div id='result{record}'></div></section>"
        for record, title in (("A", a), ("B", b))
    ]
    if variant == 1:
        sections.reverse()
    body = "".join(sections)
    script = (
        "window.saves={A:0,B:0};window.values={};"
        + f"function saveRecord(r){{window.saves[r]++;window.values[r]=document.querySelector('#draft'+r).value;setTimeout(()=>document.querySelector('#result'+r).textContent='{saved} '+r+': '+window.values[r],350)}}"
    )
    if variant == 2:
        script += "setTimeout(()=>document.querySelector('main').prepend(document.querySelector('section:last-child')),500);"
    return f"<!doctype html><meta charset=utf-8><title>Browser task fixture</title><style>section{{margin:20px;padding:10px;border:1px solid #ccc}}button{{margin:8px}}</style><main>{body}</main><script>{script}</script>".encode()


async def serve_fixture(body):
    async def serve(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    return server, f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"


async def deterministic_case(service, thread, url):
    from deepseek_tui.browser.input import BrowserInput
    from deepseek_tui.engine.context import estimate_tokens

    await service.action(thread, BrowserAction(action="open", url=url))
    run = service.runs[thread]
    observed = (
        await service.action(thread, BrowserAction(action="observe", selector='[data-record="A"]'))
    )["observation"]
    field = next(e for e in observed["elements"] if e["role"] in {"textbox", "input"})
    filled = await service.action(
        thread,
        BrowserAction(
            action="fill",
            ref=field["ref"],
            observation_id=observed["observation_id"],
            text="benchmark draft",
        ),
        require_observation=True,
    )
    observed = (
        await service.action(thread, BrowserAction(action="observe", selector='[data-record="A"]'))
    )["observation"]
    button = next(e for e in observed["elements"] if e["role"] == "button")
    clicked = await service.action(
        thread,
        BrowserAction(action="click", ref=button["ref"], observation_id=observed["observation_id"]),
        require_observation=True,
    )
    checked = await service.action(
        thread,
        BrowserAction(action="wait", selector="#resultA", text="benchmark draft", timeout_ms=2000),
    )
    truth = await evaluate(
        run.session._internal.client, "({saves:window.saves,values:window.values})"
    )
    await service.control(thread, "user")
    scene = ((await service.view(thread)).get("scene") or {}).get("scene_id")
    latencies = []
    for _ in range(30):
        start = time.perf_counter()
        input_args = dict(
            kind="mouse",
            event="mouseMoved",
            x=10,
            y=10,
            generation=run.generation,
        )
        if "scene_id" in BrowserInput.model_fields:
            input_args["scene_id"] = scene
        await service.input(thread, BrowserInput(**input_args))
        latencies.append((time.perf_counter() - start) * 1000)
    projection = project_result(
        {"success": True, "content": "observed", "observation": observed}, budget=6000
    )
    return {
        "completed": filled["success"]
        and clicked["success"]
        and checked["success"]
        and truth["saves"] == {"A": 1, "B": 0}
        and truth["values"]["A"] == "benchmark draft",
        "truth": truth,
        "input_p50_ms": statistics.median(latencies),
        "input_p95_ms": sorted(latencies)[int(len(latencies) * 0.95) - 1],
        "projection_chars": len(projection),
        "projection_utf8_bytes": len(projection.encode()),
        "projection_token_estimate": estimate_tokens(projection),
        "token_estimator": "o200k_base_or_char_fallback",
        "stages": getattr(run, "metrics", [])[-10:],
    }


async def model_case(service, thread, url, language, cfg, root):
    from deepseek_tui.client import build_llm_client
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.config.models import FeatureConfig
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import StreamDone

    cfg = cfg.model_copy(deep=True)
    cfg.features = FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False)
    delegate = build_llm_client(cfg)

    class MeasuredClient(LLMClient):
        def __init__(self):
            super().__init__()
            self.media_config = cfg
            self.rounds = 0
            self.usage = []
            self.latencies = []

        async def stream_chat_completion(self, request):
            self.rounds += 1
            if self.rounds > 16:
                raise RuntimeError("Benchmark model round limit reached")
            started = time.perf_counter()
            async for event in delegate.stream_chat_completion(request):
                if isinstance(event, StreamDone) and event.usage:
                    self.usage.append(event.usage.model_dump())
                yield event
            self.latencies.append(time.perf_counter() - started)

        async def close(self):
            await delegate.close()

    client = MeasuredClient()
    work = root / thread
    work.mkdir()
    engine = await Engine.create(
        handle=EngineHandle(), client=client, working_directory=work, config=cfg, start_mcp=False
    )
    engine.tool_registry.filter_by_names({"browser_use"})
    engine.tool_context.metadata.update(
        browser_service=service, runtime_thread_id=thread, task_config=cfg
    )
    # The human authorized these exact local fixture effects in this benchmark task.
    engine._handle_approval_flow = AsyncMock(return_value=False)
    engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
    engine._handle_shell_process_turn_handoff = AsyncMock(return_value=False)
    await service.action(thread, BrowserAction(action="open", url=url))
    original = service.action

    async def confined(thread_id, action, **kwargs):
        if action.action in {"open", "new_tab"} and action.url and action.url != url:
            raise ValueError("Benchmark navigation must stay on its local fixture")
        if action.action in {"upload", "handle_dialog", "recover", "close_session"}:
            raise ValueError("This benchmark does not authorize that effect")
        return await original(thread_id, action, **kwargs)

    service.action = confined
    prompt = (
        f"页面已经打开：{url}。只用 browser_use，将记录 A 的草稿改成“模型验收”，点击保存一次。不要修改记录 B。"
        "等待并核对记录 A 自己的已保存内容后再回答，不要把字段已填写等同于已保存。"
        if language == "zh"
        else f"The page is open at {url}. Use only browser_use to change Record A's Draft to '模型验收', save once, "
        "and verify the saved content in Record A itself. Leave Record B untouched. Filling a field is not business completion."
    )
    started = time.perf_counter()
    answer, error = "", None
    try:
        result = await asyncio.wait_for(
            engine._run_conversation(
                [Message.user(prompt)],
                cfg.model or cfg.default_text_model,
                Path("src/deepseek_tui/prompts/browser.md").read_text(),
                None,
            ),
            360,
        )
        answer = result.assistant_message.text_content() if result.assistant_message else ""
    except Exception as exc:
        error = type(
            exc
        ).__name__  # Never serialize transport credentials or provider response headers.
    finally:
        service.action = original
        await engine.shutdown_session()
    run = service.runs[thread]
    truth = await evaluate(
        run.session._internal.client, "({saves:window.saves,values:window.values})"
    )
    complete = truth["saves"] == {"A": 1, "B": 0} and truth["values"].get("A") == "模型验收"
    return {
        "completed": complete,
        "truth": truth,
        "model": cfg.model or cfg.default_text_model,
        "rounds": client.rounds,
        "usage": client.usage,
        "model_seconds": client.latencies,
        "total_seconds": time.perf_counter() - started,
        "error": error,
        "answer": answer,
        "wrong_record_mutations": truth["saves"]["B"],
        "duplicate_mutations": max(0, truth["saves"]["A"] - 1),
        "assistance_requested": run.assistance is not None,
        "success_claim_requires_review": bool(answer) and not complete,
        "stages": getattr(run, "metrics", [])[-20:],
    }


async def main(args):
    root = Path(tempfile.mkdtemp(prefix="browser-benchmark-"))
    config = None
    if args.real_model:
        from deepseek_tui.config.loader import ConfigLoader

        config = ConfigLoader().load()
    # Isolate local transcript/media/cache writes after loading the user's provider configuration.
    os.environ["DEEPSEEK_HOME"] = str(root / "home")
    service = BrowserService(root / "artifacts")
    results = {
        "fixture_version": 1,
        "source": "current_workspace",
        "behavior": [],
        "real_model": [],
    }
    try:
        for language, variant in [("en", 0), ("zh", 1), ("en", 2)]:
            server, url = await serve_fixture(fixture(language, variant))
            try:
                thread = f"behavior_{language}_{variant}"
                result = await deterministic_case(service, thread, url)
                results["behavior"].append({"language": language, "variant": variant, **result})
                await service.close(thread)
                args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
                if config:
                    thread = f"model_{language}_{variant}"
                    result = await model_case(service, thread, url, language, config, root)
                    results["real_model"].append(
                        {"language": language, "variant": variant, **result}
                    )
                    await service.close(thread)
                    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
            finally:
                server.close()
                await server.wait_closed()
    finally:
        await service.close_all()
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "behavior_completed": sum(c["completed"] for c in results["behavior"]),
                "behavior_cases": len(results["behavior"]),
                "real_model_completed": sum(c["completed"] for c in results["real_model"]),
                "real_model_cases": len(results["real_model"]),
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    asyncio.run(main(parser.parse_args()))
