"""Comparable, case-weighted experiment differences with explicit uncertainty."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

METRICS = (
    "task.pass_rate",
    "task.honest_rate",
    "task.overclaim_rate",
    "session.answers_lost",
    "session.harness_rounds",
    "session.rounds",
    "session.input_tokens",
    "session.output_tokens",
)


def load_run(path: Path) -> dict[str, Any]:
    """Read a run directory into the shape ``compare_runs`` takes."""
    summary_path = path / "summary.json"
    return {
        "manifest": json.loads((path / "manifest.json").read_text(encoding="utf-8")),
        "cases": [
            json.loads(line)
            for line in (path / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        ],
        "status": "completed" if summary_path.is_file() else "running",
        "metrics": (
            json.loads(summary_path.read_text(encoding="utf-8"))["metrics"]
            if summary_path.is_file()
            else {}
        ),
    }


def format_comparison(a: dict[str, Any], b: dict[str, Any]) -> str:
    result = compare_runs(a, b)
    lines = [f"结论：{result['conclusion']}"]
    lines += [f"不可比较：{reason}" for reason in result["reasons"]]
    if result["delta"] is not None:
        lines.append(f"按场景等权的通过率变化：{result['delta']:+.3f}，区间 {result['interval']}")
    lines.append(f"改善 {result['improved']} 个，退步 {result['regressed']} 个")
    lines += [
        f"  {row['case_id']}: {row['a']} -> {row['b']}"
        for row in result["rows"]
        if row["delta"]
    ]
    for name in METRICS:
        left, right = a["metrics"].get(name), b["metrics"].get(name)
        if left and right:
            lines.append(
                f"{name}: 均值 {left['mean']:.3f} -> {right['mean']:.3f}"
                f"，p90 {left.get('p90', 0):.3f} -> {right.get('p90', 0):.3f}"
            )
    lines.append(result["note"])
    return "\n".join(lines)


def compare_runs(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    ma, mb = a["manifest"], b["manifest"]
    reasons = []
    field_labels = {
        "dataset_hash": "场景版本",
        "grader_hash": "评分规则版本",
        "mode": "评测模式",
        "trials": "重复次数",
        "max_live_requests": "请求上限",
        "max_output_tokens": "输出上限",
        "max_cost_usd": "费用上限",
        "timeout_seconds": "超时限制",
        "judge_model": "评审模型",
        "judge_provider": "评审服务商",
        "max_input_tokens": "输入上限",
        "concurrency": "并发数",
        "retry_policy": "请求计数规则",
    }
    for key in ("dataset_hash", "grader_hash", "mode", "trials"):
        if not ma.get(key) or ma.get(key) != mb.get(key):
            reasons.append(f"{field_labels[key]}不同或未记录")
    for key in (
        "max_live_requests",
        "max_output_tokens",
        "max_cost_usd",
        "timeout_seconds",
        "judge_model",
        "judge_provider",
        "max_input_tokens",
        "concurrency",
        "retry_policy",
    ):
        if ma.get("settings", {}).get(key) != mb.get("settings", {}).get(key):
            reasons.append(f"预算/执行条件不同：{field_labels[key]}")
    for run in (a, b):
        if run["manifest"].get("settings", {}).get("source_changed_during_run"):
            reasons.append("实验执行期间源文件发生变化，请固定代码后重跑")
        if run["status"] != "completed":
            reasons.append("实验尚未完整结束")
        expected = run["manifest"].get("settings", {}).get("expected_trials")
        if not expected or len(run["cases"]) != expected:
            reasons.append("计划试验数缺失或结果不完整")
        identities = [(row["case_id"], row["trial"]) for row in run["cases"]]
        if len(identities) != len(set(identities)):
            reasons.append("存在重复的场景/试验编号")
        plan = run["manifest"].get("settings", {}).get("case_trials")
        if plan and set(identities) != {
            (case_id, trial) for case_id, count in plan.items() for trial in range(1, count + 1)
        }:
            reasons.append("逐题试验编号与运行计划不一致")
        planned_ids = run["manifest"].get("case_ids")
        if planned_ids and set(planned_ids) != {row["case_id"] for row in run["cases"]}:
            reasons.append("实际场景与运行计划不一致")
        if any(row["status"] not in {"passed", "failed"} for row in run["cases"]):
            reasons.append("存在跳过或运行错误")

    def grouped(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(row["case_id"], []).append(row)
        return result

    ga, gb = grouped(a["cases"]), grouped(b["cases"])
    if set(ga) != set(gb):
        reasons.append("两侧场景不一致")
    rows: list[dict[str, Any]] = []
    for case_id in sorted(set(ga) | set(gb)):
        left, right = ga.get(case_id, []), gb.get(case_id, [])
        for key in ("source_group", "task_family", "split", "runner", "suite", "risk"):
            values = {r.get(key) for r in left + right}
            if len(values) > 1:
                reasons.append(f"场景元数据不一致：{case_id}/{key}")
        if {r["trial"] for r in left} != {r["trial"] for r in right}:
            reasons.append(f"重复试验不匹配：{case_id}")
        pa = sum(r["status"] == "passed" for r in left) / len(left) if left else None
        pb = sum(r["status"] == "passed" for r in right) / len(right) if right else None
        rows.append(
            {
                "case_id": case_id,
                "source_group": (left or right)[0].get("source_group", ""),
                "task_family": (left or right)[0].get("task_family", ""),
                "split": (left or right)[0].get("split", "development"),
                "a": pa,
                "b": pb,
                "delta": pb - pa if pa is not None and pb is not None else None,
            }
        )
    deltas = [r["delta"] for r in rows if r["delta"] is not None]
    delta = sum(deltas) / len(deltas) if deltas else None
    interval = None
    if len(deltas) >= 2 and not reasons:
        rng = random.Random(20260906)
        samples = sorted(sum(rng.choices(deltas, k=len(deltas))) / len(deltas) for _ in range(2000))
        interval = [samples[49], samples[1949]]
    return {
        "comparable": not reasons,
        "reasons": sorted(set(reasons)),
        "rows": rows,
        "delta": delta,
        "interval": interval,
        "improved": sum(d > 0 for d in deltas),
        "regressed": sum(d < 0 for d in deltas),
        "conclusion": "不可比较"
        if reasons
        else "观察到差异，尚需复核"
        if delta
        else "本次未观察到净变化",
        "note": (
            "按场景等权；区间为场景重采样的探索性估计，不覆盖同源题、服务漂移等影响。"
            "小样本不能证明泛化增益。"
        ),
        "changes": [
            key
            for key in ("git_commit", "dirty_diff_hash", "provider", "model", "prompt_hash")
            if ma.get(key) != mb.get(key)
        ]
        + (
            ["prompt_suffix"]
            if ma.get("settings", {}).get("prompt_suffix")
            != mb.get("settings", {}).get("prompt_suffix")
            else []
        ),
    }
