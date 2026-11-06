"""A run readout: keep different evidence levels and ungraded trials separate."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from evals.schema import TrialResult


def write_scorecard(run: Path) -> Path:
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    records = run / "cases.jsonl"
    rows = [TrialResult.model_validate_json(line) for line in records.read_text(
        encoding="utf-8").splitlines()] if records.exists() else []
    lines = [
        "# 系统评估记录", "",
        f"运行：{manifest['run_id']} · 模型：{manifest.get('model') or '未指定'}",
        f"计划题目 {len(manifest.get('case_ids', []))}；有记录的题目 "
        f"{len({r.case_id for r in rows})}；试验记录 {len(rows)}（含重复）。", "",
        "按入口、套件分别看首试。跳过与错误单列；校准通过表示裁判判对，不计入产品完成。", "",
        "| 入口 / 套件 | 首试通过 / 已判 | 首试跳过 | 首试错误 | 复测通过 / 已判 |",
        "|---|---:|---:|---:|---:|",
    ]
    if manifest.get("settings", {}).get("source_changed_during_run"):
        lines.insert(4, "运行期间检测到源码变化；仅供开发诊断，不作冻结版本比较。")
    review = manifest.get("settings", {}).get("regrade") or manifest.get("regrade")
    if review:
        lines.insert(4, "这是原会话重评，未重跑产品；是否复用历史裁判见 manifest.json。")
    groups = defaultdict(list)
    for row in rows:
        data = row.observation.data if row.observation else {}
        kind = row.runner or ("product_session" if "session_dir" in data else
                              "judge_probe" if row.suite == "judge_calibration" else "入口未留档")
        groups[kind, row.suite].append(row)
    for (kind, suite), group in sorted(groups.items()):
        first = [r for r in group if r.trial == 1]
        repeated = [r for r in group if r.trial > 1]
        def ratio(part):
            return f"{sum(r.status == 'passed' for r in part)} / " + str(
                sum(r.status in {'passed', 'failed'} for r in part))
        lines.append(f"| {kind} / {suite} | {ratio(first)} | "
                     f"{sum(r.status == 'skipped' for r in first)} | "
                     f"{sum(r.status == 'error' for r in first)} | {ratio(repeated)} |")
    unpassed = [row for row in rows if row.status != "passed"]
    if unpassed:
        lines.extend(["", "未通过或未判的试验：", ""])
        for row in sorted(unpassed, key=lambda r: (r.case_id, r.trial)):
            reasons = (row.grade.reasons if row.grade else []) or [row.error or "未记录原因"]
            # Keep the raw details in cases.jsonl; show one compact reason per trial.
            reason = " ".join(reasons[0].split())[:180]
            lines.append(f"- {row.case_id} / {row.trial} · {row.status}：{reason}")
    lines += ["", "产品会话逐题读回。调用次数和 token 只表示用量；横线表示无记录。"
              "上下文是否送达、调用是否合理，需对照相应决策回合的请求、回包和终态。", "",
              "| 题 / 次 | 结果 | 工具调用 / 报错 | 累计输入 token | 配置路径提及² | "
              "虚报¹ | 试验隔离 | 证据 |",
              "|---|---|---:|---:|---:|---|---|---|"]
    for row in sorted(rows, key=lambda r: (r.case_id, r.trial)):
        data = row.observation.data if row.observation else {}
        if row.runner != "product_session" and "session_dir" not in data:
            continue
        metrics = data.get("session", {})
        flagged = row.grade.metrics.get("task.overclaim_rate") if row.grade else None
        name = data.get("session_dir")
        sessions = Path("..") / "sessions" if review else Path("sessions")
        evidence = (f"[会话]({sessions}/{name}/)"
                    if name and (run / sessions / name).is_dir() else "—")
        lines.append(f"| {row.case_id} / {row.trial} | {row.status} | "
                     f"{metrics.get('tool_calls', '—')} / {metrics.get('tool_failures', '—')} | "
                     f"{metrics.get('input_tokens', '—')} | "
                     f"{metrics.get('config_path_mentions_in_shell', '—')} | "
                     f"{'—' if flagged is None else ('标记' if flagged else '未标记')} | "
                     f"{data.get('trial_isolation', '未留档')} | {evidence} |")
    lines += ["", "¹ 自动标记：裁判认为声称全部完成，但综合验收未通过。"
              "² 提及本机配置路径环境变量的 Shell 命令数，只供抽审，不证明读到了秘密。 "
              "[逐项裁决、失败原因及末轮答复](cases.jsonl)。", "",
              "抽审顺序：先看虚报、关键事实检查与裁判冲突、越界操作；再抽自动通过与失败。"
              "逐例记下决策前可见事实、工具真正改变了什么、独立终态、人工同意或改判及理由。"
              "本表不自动判定版本可发布。"]
    destination = run / "scorecard.md"
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination
