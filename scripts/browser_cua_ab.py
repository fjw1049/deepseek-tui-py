"""One bounded real-world A/B attempt; explicit account/model and no automatic reruns.

Run this same harness in separate processes with PYTHONPATH pointing at each frozen
source tree. The output directory is also the attempt ledger (maximum 20 entries).
Grading data is read only after the model has finished and is never given to it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock

CASES = [
    {
        "id": "python_search",
        "url": "https://docs.python.org/3/",
        "prompt": (
            "使用文档站内搜索找到 pathlib 的 Path.read_text 文档"
            "，查明 newline 参数在哪个 Python 版本加入，回答版本和文档链"
            "接。"
        ),
        "answer": ["3.13"],
        "evidence": ["read_text", "newline"],
        "url_contains": "pathlib",
    },
    {
        "id": "mdn_options",
        "url": "https://developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API",
        "prompt": (
            "在这份文档的 Intersection observer options 部"
            "分查 rootMargin 和 threshold 的默认值，分别回答并给出"
            "来源链接。"
        ),
        "answer": ["rootMargin", "threshold", "0"],
        "evidence": ["rootMargin", "threshold"],
    },
    {
        "id": "wikipedia_search",
        "url": "https://www.wikipedia.org/",
        "prompt": (
            "用首页搜索框查找英文 Ada Lovelace 条目，报告她的出生日期和出生"
            "地，给出条目链接。"
        ),
        "answer": ["1815", "12", "10"],
        "evidence": ["Lovelace", "1815"],
        "url_contains": "Ada_Lovelace",
    },
    {
        "id": "github_license",
        "url": "https://github.com/Tencent/BrowserSkill",
        "prompt": (
            "从此仓库的文件列表打开 LICENSE 文件，报告许可证名称和版权行中的年份"
            "及持有人，给出文件链接。"
        ),
        "answer": ["MIT", "Tencent"],
        "evidence": ["MIT", "Copyright"],
        "url_contains": "LICENSE",
    },
    {
        "id": "rfc_sections",
        "url": "https://www.rfc-editor.org/rfc/rfc9110.html",
        "prompt": (
            "在 RFC 9110 中定位 Retry-After 和 503 Servi"
            "ce Unavailable 两节。回答它们的节号、Retry-After "
            "允许的两种格式，以及 503 是否必须带该字段。给出来源链接。"
        ),
        "answer": ["10.2.3", "15.6.4"],
        "evidence": ["Retry-After", "HTTP-date", "delay-seconds"],
    },
    {
        "id": "excalidraw_canvas",
        "url": "https://excalidraw.com/",
        "prompt": (
            "在这块空白画布上画一个矩形，并在矩形内部写上 Review ready。检查"
            "画布结果后完成；不分享、不登录。"
        ),
    },
    {
        "id": "textedit_save",
        "app": "com.apple.TextEdit",
        "prompt": (
            "文本编辑已打开测试文件 {file}。将全文替换为‘会议时间为周三下午’，保"
            "存到原文件并核对完成。只操作这份测试文件。"
        ),
    },
    {
        "id": "finder_rename",
        "app": "com.apple.finder",
        "prompt": (
            "Finder 已打开测试目录 {work}。把其中 draft-note.t"
            "xt 重命名为 reviewed-note.txt，核对结果并保留文件内容；"
            "不要操作其他目录。"
        ),
    },
    {
        "id": "calculator",
        "app": "com.apple.calculator",
        "prompt": (
            "使用计算器，先清除当前输入，再计算 128×7+64。报告计算器显示的最终结"
            "果。"
        ),
    },
    {
        "id": "preview_rotate",
        "app": "com.apple.Preview",
        "prompt": (
            "预览已打开测试图片 {file}。将图片向左旋转 90 度一次，保存到原文件"
            "并核对。只操作这份测试图片。"
        ),
    },
]


def prepare(case, work):
    """Controlled initial files; these setup actions are outside model timing."""
    file = work / f"acceptance-{work.parent.name}.txt"
    if case["id"] == "textedit_save":
        file.write_text("会议时间待定\n")
    elif case["id"] == "finder_rename":
        file = work / "draft-note.txt"
        file.write_text("Acceptance file: preserve this content.\n")
    elif case["id"] == "preview_rotate":
        from PIL import Image, ImageDraw

        file = work / f"acceptance-{work.parent.name}.png"
        image = Image.new("RGB", (640, 400), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 250, 90), fill="navy")
        draw.text((30, 110), "NORTH - Acceptance", fill="black")
        image.save(file)
        image.transpose(Image.Transpose.ROTATE_90).save(work / "expected-rotation.png")
    if case.get("app"):
        command = ["/usr/bin/open", "-b", case["app"]]
        if case["id"] != "calculator":
            command.append(str(work if case["id"] == "finder_rename" else file))
        subprocess.run(command, check=True, capture_output=True)
    return file


async def oracle(case, answer, calls, service, session, work, file):
    from deepseek_tui.browser.observation import evaluate

    identifier = case["id"]
    if identifier == "textedit_save":
        text = file.read_text()
        return {"passed": text.strip() == "会议时间为周三下午", "saved_text": text}
    if identifier == "finder_rename":
        renamed = work / "reviewed-note.txt"
        return {
            "passed": not file.exists()
            and renamed.exists()
            and renamed.read_text() == "Acceptance file: preserve this content.\n"
        }
    if identifier == "preview_rotate":
        from PIL import Image, ImageChops, ImageOps

        with Image.open(file) as saved, Image.open(work / "expected-rotation.png") as expected:
            actual = ImageOps.exif_transpose(saved).convert("RGB")
            return {
                "passed": actual.size == expected.size
                and ImageChops.difference(actual, expected).getbbox() is None,
                "size": list(actual.size),
            }
    if identifier == "calculator":
        observed = await session.call(
            "observe", {"app": case["app"], "screenshot": False},
            session.turn_id or "acceptance", "independent-oracle"
        )
        text = (observed.get("observation") or {}).get("text", "")
        return {
            "passed": bool(re.search(r"(?:Value:|value:)\s*960\b", text)) and "960" in answer,
            "final_ax": text,
        }
    client = service.runs["acceptance"].session._internal.client
    if identifier == "excalidraw_canvas":
        data = await evaluate(client, "JSON.parse(localStorage.getItem('excalidraw') || '[]')")
        elements = [e for e in data if isinstance(e, dict) and not e.get("isDeleted")]
        rectangles = [e for e in elements if e.get("type") == "rectangle"]
        texts = [
            e
            for e in elements
            if e.get("type") == "text" and e.get("text", "").strip() == "Review ready"
        ]
        inside = any(
            t.get("containerId") == r.get("id")
            or (
                r["x"] <= t["x"]
                and r["y"] <= t["y"]
                and t["x"] + t["width"] <= r["x"] + r["width"]
                and t["y"] + t["height"] <= r["y"] + r["height"]
            )
            for r in rectangles
            for t in texts
        )
        return {"passed": len(rectangles) == 1 and len(texts) == 1 and inside, "elements": elements}
    # Public-page claims still receive a human semantic audit, not substring-only grading.
    page = await evaluate(client, "({url:location.href,text:document.body.innerText})")
    delivered = "\n".join(c.get("content", "") for c in calls)
    matched = all(s.casefold() in answer.casefold() for s in case["answer"])
    evidence = all(s.casefold() in delivered.casefold() for s in case["evidence"])
    navigation = case.get("url_contains", "") in page["url"]
    return {
        "passed": bool(matched and evidence and navigation),
        "manual_review_required": True,
        "answer_matches": matched,
        "raw_tool_evidence": evidence,
        "final_url": page["url"],
        "page_text": page["text"][:200000],
    }


async def run(args, case, directory):
    from deepseek_tui.browser.service import BrowserAction, BrowserService
    from deepseek_tui.client import LLMClient, RetryConfig, build_llm_client
    from deepseek_tui.config.loader import ConfigLoader
    from deepseek_tui.config.models import FeatureConfig
    from deepseek_tui.config.routing import config_for_model
    from deepseek_tui.cua.approval import auto_allow_response
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator import Engine
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import StreamDone, StreamError

    cfg = config_for_model(ConfigLoader().load(), args.model, provider=args.provider)
    cfg.default_text_model = args.model
    cfg.features = FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False)
    cfg.cua.enabled = bool(case.get("app"))
    cfg.cua.chrome = False
    cfg.cua.auto_allow_apps = False
    cfg.vision.model = None  # Flash itself receives images; no secondary model.
    os.environ["DEEPSEEK_HOME"] = str(directory / "home")
    os.environ["DEEPSEEK_BROWSER_KEYCHAIN"] = "0"
    work = directory / "workspace"
    work.mkdir()
    file = prepare(case, work)
    delegate = build_llm_client(cfg)
    retry = RetryConfig(max_transparent_retries=0, max_error_retries=0)
    delegate.retry_config = retry
    calls, usage, errors = [], [], []

    class LimitedClient(LLMClient):
        def __init__(self):
            super().__init__(retry_config=retry)
            self.rounds = 0
            self.media_config = cfg
            self.infrastructure_error = False

        async def stream_chat_completion(self, request):
            if self.infrastructure_error:
                raise RuntimeError("Evaluation infrastructure failed; no further paid calls")
            if request.model != "deepseek-flash" or self.rounds >= 12:
                raise RuntimeError("Authorized model/request budget exceeded")
            self.rounds += 1
            print(f"{args.variant}/{case['id']} round={self.rounds}", flush=True)
            request = request.model_copy(update={"max_tokens": 2048})
            try:
                async for event in delegate.stream_chat_completion(request):
                    if isinstance(event, StreamDone) and event.usage:
                        usage.append(event.usage.model_dump())
                    if isinstance(event, StreamError):
                        errors.append("provider_stream_error")
                    yield event
            except Exception as exc:
                errors.append(
                    {
                        "type": type(exc).__name__,
                        "status": getattr(getattr(exc, "response", None), "status_code", None),
                    }
                )
                raise

        async def close(self):
            await delegate.close()

    client = LimitedClient()
    service = BrowserService(directory / "browser")
    service.configure("acceptance", persistent=False)
    engine = None
    output = {
        "case": case["id"],
        "variant": args.variant,
        "provider": args.provider,
        "model": args.model,
        "source_root": str(args.source_root),
        "artifact_root": str(directory),
        "calls": calls,
        "usage": usage,
        "provider_errors": errors,
        "status": "started",
    }
    started = None
    try:
        engine = await Engine.create(
            handle=EngineHandle(),
            client=client,
            working_directory=work,
            config=cfg,
            start_mcp=False,
        )
        engine.tool_context.metadata.update(
            browser_service=service,
            runtime_thread_id="acceptance",
            task_config=cfg,
            task_model=args.model,
            unattended=True,
        )
        engine._handle_approval_flow = AsyncMock(return_value=False)
        engine._handle_subagent_turn_handoff = AsyncMock(return_value=False)
        engine._handle_shell_process_turn_handoff = AsyncMock(return_value=False)
        await engine._prepare_cua()
        allowed = (
            {"cua_js", "cua_js_reset", "cua_observe", "cua_act"}
            if case.get("app")
            else {"browser_use"}
        )
        engine.tool_registry.filter_by_names(allowed)
        session = getattr(engine, "_cua_session", None)
        if case.get("app"):
            if not session or not engine.tool_registry.all():
                raise RuntimeError("CUA runtime unavailable")

            async def approve(params):
                meta = params.get("_meta") or params.get("meta") or {}
                target = (meta.get("tool_params") or {}).get("app", "")
                if target.casefold() == case["app"].casefold():
                    return auto_allow_response(params) or {"action": "cancel"}
                return {"action": "cancel"}

            session.on_approval = approve
        else:
            opened = await service.action(
                "acceptance", BrowserAction(action="open", url=case["url"])
            )
            if not opened.get("success"):
                raise RuntimeError("Initial website unavailable")
        execute = engine.tool_registry.execute

        async def measured(name, data, context):
            if len(calls) >= 24 or name not in allowed:
                raise ValueError("Tool budget or authorized surface exceeded")
            if name in {"cua_observe", "cua_act"} and data.get("app") != case.get("app"):
                raise ValueError("Use only the authorized app bundle ID")
            entry = {"tool": name, "arguments": data}
            calls.append(entry)
            # The public engine entry point normally binds these host identities.
            # This bounded harness calls the inner loop, so supply real per-run/call IDs.
            context.metadata.update(cua_turn_id=f"ab-{directory.name}",
                                    cua_call_id=f"call-{len(calls)}")
            try:
                result = await execute(name, data, context)
            except Exception as exc:
                entry.update(success=False, content=str(exc)[:500])
                if "real host turn/call identities" in str(exc):
                    client.infrastructure_error = True
                raise
            entry.update(
                success=result.success,
                content=result.content,
                images=[i.model_dump() for i in result.images],
                metadata=result.metadata,
            )
            return result

        engine.tool_registry.execute = measured
        prompt = case["prompt"].format(work=work, file=file)
        if case.get("app"):
            prompt += f" 授权应用 ID：{case['app']}。只能通过 CUA 操作该应用。"
        else:
            prompt = f"当前已打开 {case['url']}。只用 browser_use 完成。" + prompt
        prompt_file = "computer_use.md" if case.get("app") else "browser.md"
        system = (args.source_root / "deepseek_tui/prompts" / prompt_file).read_text()
        output["prompt"] = prompt
        started = time.monotonic()
        result = await asyncio.wait_for(
            engine._run_conversation([Message.user(prompt)], args.model, system, None), 180
        )
        output["seconds"] = round(time.monotonic() - started, 2)
        output["answer"] = (
            result.assistant_message.text_content() if result.assistant_message else ""
        )
        output["engine_error"] = bool(result.error_message)
        output["oracle"] = await oracle(case, output["answer"], calls, service, session, work, file)
        output["status"] = "executed"
        output["passed"] = bool(output["oracle"]["passed"] and not result.error_message)
    except Exception as exc:
        output.update(status="error", passed=False, error=type(exc).__name__)
        if started and (not case.get("app") or session):
            try:
                output["oracle"] = await oracle(
                    case, output.get("answer", ""), calls, service, session, work, file)
            except Exception as oracle_error:
                output["oracle_error"] = type(oracle_error).__name__
    finally:
        output["rounds"] = client.rounds
        output.setdefault("seconds", round(time.monotonic() - started, 2) if started else 0)
        (directory / "result.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n"
        )
        if engine:
            await engine.shutdown_session()
        await client.close()
        await service.close_all()
    print(
        json.dumps(
            {k: output.get(k) for k in ("case", "variant", "passed", "rounds", "seconds", "error")}
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", choices=["deepseek-flash"], required=True)
    parser.add_argument("--account", choices=["company", "personal-exception"], required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--variant", choices=["before", "after"], required=True)
    parser.add_argument("--case", choices=[c["id"] for c in CASES], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.source_root = args.source_root.resolve()
    import deepseek_tui

    if Path(deepseek_tui.__file__).resolve().parent.parent != args.source_root:
        parser.error("PYTHONPATH must select the exact --source-root")
    args.output.mkdir(parents=True, exist_ok=True)
    if len(list(args.output.glob("*/attempt.json"))) >= 20:
        parser.error("Maximum 20 attempts; no automatic reruns")
    directory = args.output / f"{args.case}-{args.variant}"
    directory.mkdir()  # Refuse a repeated attempt, including one that crashed.
    (directory / "attempt.json").write_text(
        json.dumps(
            {
                "case": args.case,
                "variant": args.variant,
                "account": args.account,
                "provider": args.provider,
                "model": args.model,
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "limits": {
                    "rounds": 12,
                    "output_tokens_per_request": 2048,
                    "seconds": 180,
                    "tool_calls": 24,
                },
            },
            indent=2,
        )
        + "\n"
    )
    logging.disable(logging.CRITICAL)
    asyncio.run(run(args, next(c for c in CASES if c["id"] == args.case), directory))
