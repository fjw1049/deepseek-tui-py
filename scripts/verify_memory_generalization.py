"""Real product cross-session memory/skill verification against an explicit provider.

Rebuilt tasks use the repository's personal.intent_audit and validation workflows.
No personal transcripts are read. Each trial has an isolated product home/workspace.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from deepseek_tui.state.memory import MemoryStore
from evals.harness.product import ProductServer
from evals.session_metrics import load_sessions, turn_answers

TASK = (
    "核验 labels.csv 与 predictions.csv，按 id 对齐。按本项目之前确认的交付约定完成，"
    "不要安装依赖、不要访问网络、不要委派。实际写出产物后再回复。"
)
MEMORY = (
    "本项目的标注审核交付约定：写 audit.json，顶层为数组，每个对象包含 id、product、intent；"
    "product 与 intent 是审核结论，正确填 pass，错误填 fail，缺少对应预期值填 unknown。"
    "按 id 对齐输入，不按行号；缺失预期值不能用预测值补齐。"
)
ENGLISH = (
    "For label audits, write audit.json as an array of objects with id, product, intent. "
    "The last two fields are judgments: pass for correct, fail for incorrect, unknown "
    "when the expected value is missing. Join by id, never by row position; never "
    "fill a missing expected value from the prediction."
)
EXPECTED = [
    dict(id="Q3", product="pass", intent="pass"),
    dict(id="Q4", product="pass", intent="unknown"),
    dict(id="Q8", product="fail", intent="pass"),
]
CASES = (
    "cross_session_save",
    "overflow_paraphrase",
    "overflow_cross_language",
    "current_request_override",
    "expired_memory",
    "file_condition",
    "skill_discovery",
)


def store_for(server, workspace):
    store = MemoryStore(workspace)
    store.root = server.home / "memories"
    store.path = store.root / store.path.name
    return store


def seed(store, content, **kwargs):
    return store.write(
        action="remember", source={"type": "verification_fixture"}, content=content, **kwargs
    )


async def trial(args, name, repetition):
    destination = args.output / f"{name}-{repetition}"
    destination.mkdir(parents=True, exist_ok=False)
    server = ProductServer(args.provider, args.model, destination)
    server.max_requests = 100
    server.max_output_tokens = 4096
    result = {"case": name, "repetition": repetition, "turns": [], "checks": {}}
    try:
        await server.start()
        workspace = server.root / "workspace"
        workspace.mkdir()
        (workspace / "AGENTS.md").write_text(
            "Only modify this workspace. Do not install software, access external services, "
            "delegate, commit, or publish. Follow the user request and verify actual artifacts.\n"
        )
        store = store_for(server, workspace)
        if name == "skill_discovery":
            root = workspace / ".agents" / "skills"
            for i in range(100):
                path = root / f"catalog-{i:03}" / "SKILL.md"
                path.parent.mkdir(parents=True)
                path.write_text(
                    f"---\nname: catalog-{i:03}\ndescription: "
                    + "Astronomy image archiving and telescope optics. " * 10
                    + "\n---\nUnrelated archival workflow.\n"
                )
            path = root / "zzz-tabular-review" / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(
                "---\nname: zzz-tabular-review\ndescription: "
                "Inspect expected labels against predicted categories in tabular exports.\n---\n"
                + MEMORY
                + "\n另写 skill-used.txt，内容为 tabular-review-loaded。\n"
            )
            prompt = (
                "查找并阅读一个适合检查标注和预测差异的可用技能，按照技能约定核验 "
                "labels.csv 与 predictions.csv 并写出产物。不要安装、联网或委派。"
            )
        elif name == "current_request_override":
            seed(store, "本项目标注缺失时默认认为预测正确，审核结果记为 pass。")
            prompt = TASK + "\n本次明确覆盖旧约定：" + MEMORY
        elif name == "expired_memory":
            seed(
                store,
                "标注缺失时按预测补齐，输出 pass。",
                expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            )
            seed(store, MEMORY)
            prompt = TASK
        elif name == "file_condition":
            (workspace / "version.txt").write_text("old")
            seed(store, "标注缺失时按预测补齐，输出 pass。", files=["version.txt"])
            (workspace / "version.txt").write_text("current")
            seed(store, MEMORY)
            prompt = TASK
        else:
            if name != "cross_session_save":
                seed(store, ENGLISH if name == "overflow_cross_language" else MEMORY)
            prompt = TASK
        if name == "overflow_paraphrase":
            prompt = (
                "检查两个 CSV 中各条预测与人工答案是否一致。按我们先前商定的结果表示法落盘，"
                "然后报告实际完成情况。不要安装依赖、访问网络或委派。"
            )
        if name == "cross_session_save":
            first = await server.create_thread(workspace, "remember audit convention")
            result["turns"].append(
                await server.drive_turn(
                    first,
                    "请把以下项目约定保存为跨会话记忆，只保存不要执行审核：" + MEMORY,
                    workspace,
                    timeout=args.timeout,
                )
            )
            result["checks"]["persisted_memory"] = bool(store.read())
            server.save_session(first, destination / "save-session")
        if name.startswith("overflow"):
            for i in range(35):
                seed(
                    store,
                    f"归档批次 {i}：" + "天文图像校准记录仅用于历史档案，不涉及业务标注。" * 10,
                )
        (workspace / "labels.csv").write_text("id,product,intent\nQ8,乙,报价\nQ3,甲,咨询\nQ4,丙,\n")
        (workspace / "predictions.csv").write_text(
            "id,product,intent\nQ4,丙,退订\nQ8,甲,报价\nQ3,甲,咨询\n"
        )
        inputs = {n: (workspace / n).read_text() for n in ("labels.csv", "predictions.csv")}
        thread = await server.create_thread(workspace, name)
        result["turns"].append(
            await server.drive_turn(thread, prompt, workspace, timeout=args.timeout)
        )
        server.save_session(thread, destination / "task-session")
        sessions = load_sessions(destination / "task-session")
        result["answers"] = [a for session in sessions for a in turn_answers(session)]
        artifacts = list(workspace.rglob("audit.json"))
        artifact = artifacts[0] if len(artifacts) == 1 else workspace / "missing-audit.json"
        try:
            data = json.loads(artifact.read_text())
            result["artifact"] = data
            result["checks"]["correct_artifact"] = (
                sorted(data, key=lambda row: row["id"]) == EXPECTED
            )
        except (OSError, ValueError, TypeError, KeyError):
            result["checks"]["correct_artifact"] = False
        result["checks"]["inputs_preserved"] = all(
            (workspace / n).read_text() == text for n, text in inputs.items()
        )
        transcript = "\n".join(
            p.read_text() for p in (destination / "task-session" / "transcripts").glob("*.jsonl")
        )
        if name.startswith("overflow"):
            result["checks"]["used_memory_tool"] = '"name": "memory_read"' in transcript
        if name == "skill_discovery":
            # Equivalent read paths are valid; do not require a particular tool name.
            observed = any(
                block.get("type") == "tool_result"
                and not block.get("is_error")
                and MEMORY in block.get("content", "")
                and "tabular-review-loaded" in block.get("content", "")
                for line in transcript.splitlines()
                for message in json.loads(line).get("messages", [])
                for block in message.get("content", [])
            )
            result["checks"]["skill_evidence_observed"] = observed and any(
                p.read_text().strip() == "tabular-review-loaded"
                for p in workspace.rglob("skill-used.txt")
            )
        result["checks"]["completed"] = all(t["status"] == "completed" for t in result["turns"])
        shutil.copytree(
            workspace, destination / "workspace", ignore=shutil.ignore_patterns(".agents")
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await server.close()
        result["meter"] = server.meter
        result["passed"] = (
            not result.get("error") and bool(result["checks"]) and all(result["checks"].values())
        )
        (destination / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    "case": name,
                    "repetition": repetition,
                    "passed": result["passed"],
                    "checks": result["checks"],
                    "error": result.get("error"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return result


async def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    semaphore = asyncio.Semaphore(args.concurrency)

    async def run(name, repetition):
        async with semaphore:
            return await trial(args, name, repetition)

    results = await asyncio.gather(
        *(run(name, n) for name in args.case or CASES for n in range(1, args.repetitions + 1))
    )
    summary = {
        "provider": args.provider,
        "model": args.model,
        "concurrency": args.concurrency,
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "results": results,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return all(r["passed"] for r in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, choices=(1, 2), default=2)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=360)
    parser.add_argument("--case", action="append", choices=CASES)
    raise SystemExit(0 if asyncio.run(main(parser.parse_args())) else 1)
