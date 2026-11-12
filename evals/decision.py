"""Conservative version decisions from paired evidence, never from an overall score."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.experiments import compare_runs, resource_summary


class DecisionPolicy(BaseModel):
    """Pilot thresholds; freeze these before executing, calibrate them using A/A."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    min_source_groups: int = Field(default=8, ge=2)
    min_trials: int = Field(default=3, ge=2)
    min_gain: float = Field(default=0.05, ge=0, le=1)
    max_family_regression: float = Field(default=0, ge=0, le=1)
    max_aa_disagreement: float = Field(default=0.15, ge=0, le=1)
    require_holdout: bool = True
    max_trial_duration_increase: float | None = Field(default=None, ge=0)
    max_cost_per_success_increase: float | None = Field(default=None, ge=0)
    efficiency_metric: Literal["cost_usd", "duration_ms"] | None = None
    max_quality_loss: float = Field(default=0, ge=0, le=1)
    min_efficiency_gain: float = Field(default=0.10, gt=0, lt=1)


def _group_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[row["source_group"]].append(row["delta"])
    return {key: sum(values) / len(values) for key, values in groups.items()}


def _estimate(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"groups": 0, "delta": None, "interval": None}
    interval = None
    if len(values) >= 2:
        rng = random.Random(20261112)
        samples = sorted(
            sum(rng.choices(values, k=len(values))) / len(values) for _ in range(2000)
        )
        interval = [samples[49], samples[1949]]
    return {"groups": len(values), "delta": sum(values) / len(values), "interval": interval}


def _efficiency(
    baseline: dict[str, Any], candidate: dict[str, Any], rows: list[dict[str, Any]], metric: str,
) -> dict[str, Any]:
    """Compare cost per completion within each origin, including failed attempts."""
    groups: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        groups[row["source_group"]].add(row["case_id"])
    gains = []
    missing = []
    for source, ids in groups.items():
        values = []
        for run in (baseline, candidate):
            summary = resource_summary({"cases": [r for r in run["cases"] if r["case_id"] in ids]})
            value = summary["cost_per_success_usd"]
            if metric == "duration_ms":
                duration = summary["mean_trial_duration_ms"]
                value = (duration * summary["trials"] / summary["successes"]
                         if duration is not None and summary["successes"] else None)
            values.append(value)
        left, right = values
        if left is None or right is None or left <= 0:
            missing.append(source)
        else:
            gains.append((left - right) / left)
    return {**_estimate(gains), "metric": metric, "missing_sources": sorted(missing)}


def decide(
    baseline: dict[str, Any], candidate: dict[str, Any], policy: DecisionPolicy,
    repeat: dict[str, Any] | None = None,
) -> dict[str, Any]:
    comparison = compare_runs(baseline, candidate)
    reasons = list(comparison["reasons"])
    failures: list[str] = []
    ma, mb = baseline["manifest"], candidate["manifest"]
    for key in ("provider", "model", "python_version", "package_versions"):
        if ma.get(key) != mb.get(key):
            reasons.append(f"架构实验必须固定 {key}")
    if ma.get("mode") == "live" and (not ma.get("provider") or not ma.get("model")):
        reasons.append("实际模型与服务商未明确记录")
    for run in (baseline, candidate):
        if run["manifest"].get("settings", {}).get("regrade"):
            reasons.append("重评记录需核对有效评分器和题集，不能直接用于自动放行")
    sa = ma.get("settings", {}).get("source_snapshot") or {}
    sb = mb.get("settings", {}).get("source_snapshot") or {}
    if any(run["manifest"].get("settings", {}).get("prompt_suffix")
           and any(row.get("runner") not in {"live_decision", "workspace_task"}
                   for row in run["cases"]) for run in (baseline, candidate)):
        reasons.append("该任务入口未应用提示词补充，不能把配置变化当作实际实验")
    same_source = (sa.get("product_hash") == sb.get("product_hash")
                   if sa.get("product_hash") and sb.get("product_hash") else
                   all(ma.get(key) and ma.get(key) == mb.get(key)
                       for key in ("git_commit", "dirty_diff_hash")))
    # Generated prompt hashes may differ only because snapshot workspace paths differ.
    same_prompt = (ma.get("settings", {}).get("prompt_suffix")
                   == mb.get("settings", {}).get("prompt_suffix"))
    if same_source and same_prompt:
        reasons.append("两侧产品源码与提示词相同；只能作为同版本重复，不能声称架构收益")

    aa = compare_runs(baseline, repeat) if repeat is not None else None
    if aa is None:
        reasons.append("缺少同版本 A/A 重复实验")
    elif not aa["comparable"]:
        reasons.extend(f"A/A：{reason}" for reason in aa["reasons"])
    else:
        assert repeat is not None
        mr = repeat["manifest"]
        for key in ("git_commit", "dirty_diff_hash", "provider", "model", "prompt_hash",
                    "tool_catalog_hash", "python_version", "package_versions"):
            if ma.get(key) != mr.get(key):
                reasons.append(f"A/A 并非同版本/同条件：{key}")
        if (ma.get("settings", {}).get("prompt_suffix")
                != mr.get("settings", {}).get("prompt_suffix")):
            reasons.append("A/A 提示词补充不同")
        aa_disagreement = sum(abs(r["delta"]) for r in aa["rows"]) / len(aa["rows"])
        if aa_disagreement > policy.max_aa_disagreement:
            reasons.append(f"A/A 逐题波动 {aa_disagreement:.3f} 超过预设上限")

    invalid = bool(reasons)
    task_ids = {r["case_id"] for r in candidate["cases"]
                if r.get("runner") in {"product_session", "workspace_task"}}
    task_rows = [r for r in comparison["rows"] if r["case_id"] in task_ids]
    if not task_rows:
        reasons.append("没有可重置的端到端任务；离线/单步/裁判题不能证明任务可靠性")
    if any(not r["source_group"] or not r["task_family"] for r in task_rows):
        reasons.append("端到端任务缺少独立来源分组或任务类别")
    usable = [r for r in task_rows if r["source_group"] and r["task_family"]
              and r["delta"] is not None]
    splits: dict[str, set[str]] = defaultdict(set)
    for row in usable:
        splits[row["source_group"]].add(row["split"])
    if any(len(value) > 1 for value in splits.values()):
        reasons.append("同源任务跨开发/回归/封存分区")
    for run in (baseline, candidate, *([repeat] if repeat is not None else [])):
        for case_id in task_ids:
            trials = [r["trial"] for r in run["cases"] if r["case_id"] == case_id]
            if len(set(trials)) < policy.min_trials:
                reasons.append("端到端任务的独立重复次数不足")
                break

    families = {}
    for family in sorted({r["task_family"] for r in usable}):
        estimate = _estimate(list(_group_scores(
            [r for r in usable if r["task_family"] == family]
        ).values()))
        families[family] = estimate
        if estimate["delta"] < -policy.max_family_regression:
            failures.append(f"任务类别 {family} 退化 {estimate['delta']:.3f}")
    if len(families) < 2:
        reasons.append("不足两个任务类别，不能判断跨任务收益")
    for row in candidate["cases"]:
        if row.get("risk") == "critical" and row["status"] == "failed":
            failures.append(f"关键保护题失败：{row['case_id']}")
        data = (row.get("observation") or {}).get("data", {})
        checks = data.get("grading_checks", data.get("checks", []))
        if any(check.get("critical") and check.get("passed") is False
               and "release_blocker" not in check for check in checks):
            reasons.append(f"旧检查缺少发布保护语义，需复核：{row['case_id']}")
        if any(check.get("release_blocker") and check.get("passed") is False for check in checks):
            failures.append(f"发布保护检查失败：{row['case_id']}")
    for row in usable:
        if row["split"] == "regression" and row["delta"] < 0:
            failures.append(f"受保护回归任务退化：{row['case_id']}")
    overclaims = []
    for run in (baseline, candidate):
        values = [(row.get("grade") or {}).get("metrics", {}).get("task.overclaim_rate")
                  for row in run["cases"] if row.get("runner") == "product_session"]
        overclaims.append(values)
    product_ids = {r["case_id"] for r in candidate["cases"] if r.get("runner") == "product_session"}
    if any((row.get("grade") or {}).get("metrics", {}).get("task.overclaim_rate") not in (0, 1)
           for run in (baseline, candidate) for row in run["cases"]
           if row["case_id"] in product_ids):
        reasons.append("虚报完成指标覆盖不完整；需有具体声明和事实证据")
    elif all(value is not None for values in overclaims for value in values):
        if sum(overclaims[1]) > sum(overclaims[0]):
            failures.append("候选虚报完成次数增加")

    resources = {"baseline": resource_summary(baseline), "candidate": resource_summary(candidate)}
    for metric, limit, label in (
        ("mean_trial_duration_ms", policy.max_trial_duration_increase, "完整试验平均耗时"),
        ("cost_per_success_usd", policy.max_cost_per_success_increase, "每个完成任务的成本"),
    ):
        if limit is None:
            continue
        left, right = resources["baseline"][metric], resources["candidate"][metric]
        if left is None or right is None:
            reasons.append(f"{label}证据不足，无法核对预设上限")
        elif right > left * (1 + limit):
            failures.append(f"{label}增幅超过预设上限 {limit:.1%}")

    evidence = [r for r in usable if r["split"] == "holdout"] if policy.require_holdout else usable
    if len({r["task_family"] for r in evidence}) < 2:
        reasons.append("用于判断收益的来源未覆盖两个任务类别")
    gain = _estimate(list(_group_scores(evidence).values()))
    if gain["groups"] < policy.min_source_groups:
        reasons.append(f"独立来源不足：{gain['groups']} / {policy.min_source_groups}"
                       + ("（要求封存任务）" if policy.require_holdout else ""))
    efficiency = None
    if policy.efficiency_metric is None:
        if gain["interval"] is None or gain["interval"][0] <= policy.min_gain:
            reasons.append("来源分组区间的下界尚未超过预设最小收益")
    else:
        if gain["interval"] is None or gain["interval"][0] < -policy.max_quality_loss:
            reasons.append("质量变化区间不能排除超过预设容忍值的退化")
        efficiency = _efficiency(baseline, candidate, evidence, policy.efficiency_metric)
        if (efficiency["missing_sources"] or efficiency["interval"] is None
                or efficiency["interval"][0] <= policy.min_efficiency_gain):
            reasons.append("来源级效率收益证据不足或区间未超过预设收益")
        if repeat is not None:
            efficiency_aa = _efficiency(baseline, repeat, evidence, policy.efficiency_metric)
            efficiency["aa"] = efficiency_aa
            if (efficiency_aa["missing_sources"] or efficiency_aa["interval"] is None
                    or max(abs(v) for v in efficiency_aa["interval"])
                    >= policy.min_efficiency_gain):
                reasons.append("A/A 代价波动过大或证据缺失，不能归因于架构优化")
    # Incomparable or corrupted records cannot even support a regression decision.
    status = "insufficient_evidence" if invalid else (
        "keep_baseline" if failures else "insufficient_evidence" if reasons else "review_candidate"
    )
    return {
        "decision": status,
        "label": {"keep_baseline": "保留基线", "insufficient_evidence": "证据不足",
                  "review_candidate": "可进入候选评审"}[status],
        "reasons": sorted(set(reasons + failures)), "policy": policy.model_dump(),
        "gain": gain, "families": families, "comparison": comparison, "aa": aa,
        "resources": resources,
        "efficiency": efficiency,
        "note": "区间按独立来源聚类重采样；不证明未知任务普遍有效。封存标签不证明环境隔离。"
                "通过仅进入人工候选评审，不自动合并或发布。",
    }
