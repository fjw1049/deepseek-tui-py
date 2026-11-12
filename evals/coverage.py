"""Inventory of declared task origins, never a claim of universal coverage."""

from collections import Counter
from typing import Any

from evals.schema import EvalCase


def corpus_coverage(cases: list[EvalCase]) -> dict[str, Any]:
    tasks = [c for c in cases if c.runner in {"product_session", "workspace_task"}]
    families = {}
    for family in sorted({c.task_family for c in tasks if c.task_family}):
        members = [c for c in tasks if c.task_family == family]
        families[family] = {
            "tasks": len(members),
            "sources": len({c.source_group for c in members if c.source_group}),
            "holdout_sources": len({c.source_group for c in members
                                    if c.split == "holdout" and c.source_group}),
        }
    return {
        "cases": len(cases), "by_runner": dict(sorted(Counter(c.runner for c in cases).items())),
        "end_to_end_tasks": len(tasks),
        "declared_sources": len({c.source_group for c in tasks if c.source_group}),
        "holdout_sources": len({c.source_group for c in tasks
                                if c.split == "holdout" and c.source_group}),
        "missing_metadata": sorted(c.id for c in tasks if not c.source_group or not c.task_family),
        "families": families,
        "note": "来源标签依据任务出处人工维护；同源变体不是独立样本。"
                "未覆盖的场景和未封存的题不能提供泛化证明。",
    }
