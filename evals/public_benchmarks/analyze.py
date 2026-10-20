"""Summarize verifiable outcomes and runtime evidence without an LLM judge."""

import argparse
import json
from collections import Counter
from pathlib import Path

from evals.public_benchmarks.campaign import summarize, write_json


def analyze(directory):
    out = Path(directory)
    manifest = json.loads((out / "manifest.json").read_text())
    ledger = out / "results.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    metrics = summarize(rows, len(manifest["tasks"]))
    tools = Counter()
    errors = Counter()
    repeated_calls = []
    api_errors = 0
    final_but_failed = []
    for row in rows:
        previous = None
        streak = 0
        if row["runtime_state"] == "completed" and row["reward"] == 0:
            final_but_failed.append({"task": row["task"], "evidence": row["job"]})
        for trace in Path(row["job"]).glob("*/agent/trace.jsonl"):
            with trace.open() as stream:
                for line in stream:
                    event = json.loads(line)
                    if event["type"] == "api_error":
                        api_errors += 1
                    data = event.get("event", {})
                    if event["type"] == "ToolResultEvent":
                        tools[data["tool_name"]] += 1
                        if not data["success"]:
                            errors[data["tool_name"]] += 1
                    if event["type"] == "ToolCallEvent":
                        call = data["tool_call"]
                        signature = json.dumps(
                            {key: value for key, value in call.items() if key != "id"},
                            sort_keys=True,
                        )
                        streak = streak + 1 if signature == previous else 1
                        previous = signature
                        if streak == 3:
                            repeated_calls.append(
                                {"task": row["task"], "call": call, "trace": str(trace)}
                            )
    count = sum(tools.values())
    metrics["process"] = {
        "tool_results": dict(tools),
        "tool_errors": dict(errors),
        "tool_success_percent": 100 * (count - sum(errors.values())) / count if count else None,
        "api_errors": api_errors,
        "repeated_call_candidates": repeated_calls,
        "completed_but_failed_verifier": final_but_failed,
    }
    write_json(out / "analysis.json", metrics)
    score = metrics["full_suite_pass_rate_percent"]
    text = [
        "# GLM-5.3 / Workbench 公开评测",
        "",
        f"覆盖：{metrics['graded']}/{metrics['planned']} 道题；"
        f"官方验证器通过：{metrics['passed']} 道。",
        f"全套端到端通过率：{score if score is not None else '尚未形成，不能用部分题目外推'}。",
        f"官方参考：88.2%；差值（百分点）：{metrics['gap_to_official_percentage_points']}。",
        "",
        "该差值仅为描述性比较：当前使用众安网关、Workbench、单次运行和本机容器；"
        "官方使用 Claude Code 2.1.207。不能把差值直接归因于架构。",
        "工具调用成功率只衡量执行可靠性，不能替代任务正确率。重复调用和已结束但验证失败的任务只是人工复核线索。",
        "",
        "运行状态：`" + json.dumps(metrics["runtime_states"], ensure_ascii=False) + "`",
        f"累计请求：{metrics['requests']}。网关价格未知，未估算费用。",
        "",
        "逐题证据见 results.jsonl；过程统计和待复核轨迹见 analysis.json；原始日志在 jobs/。",
        "官方来源：https://huggingface.co/zai-org/GLM-5.3/blob/main/README.md",
        "",
    ]
    (out / "analysis.md").write_text("\n".join(text))
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    args = parser.parse_args()
    print(json.dumps(analyze(args.directory), ensure_ascii=False, indent=2))
