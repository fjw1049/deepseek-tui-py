#!/usr/bin/env python3
"""Demo: trace workflow IR execution with a fake runner (no real LLM)."""

from __future__ import annotations

import asyncio
import json
import textwrap
from typing import Any

from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    FanoutStep,
    PipelineStage,
    PipelineStep,
    StepOutput,
    SynthesisStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowSpec,
)
from deepseek_tui.workflow.runtime import run_workflow
from deepseek_tui.workflow.template import make_step_output, render_template


class TracingRunner:
    """Fake runner that logs every spawn with rendered prompt."""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.calls: list[dict[str, str]] = []
        self._responses = responses or {}

    async def run(
        self,
        *,
        prompt: str,
        label: str,
        agent_type: str = "general",
        model: str | None = None,
        allowed_tools: list[str] | None = None,
        output_schema: dict | None = None,
        policy: object = None,
        cancel_event: asyncio.Event | None = None,
        on_agent_id: object = None,
    ) -> StepOutput | None:
        self.calls.append({"label": label, "agent_type": agent_type, "prompt": prompt})
        text = self._responses.get(label, f"[mock] {label} completed")
        structured = None
        if output_schema:
            structured = {
                "ok": True,
                "verdict": f"approved by {label}",
                "findings": [f"finding from {label}"],
            }
        return make_step_output(text, structured)


def _hr(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _print_trace(runner: TracingRunner) -> None:
    for i, call in enumerate(runner.calls, 1):
        print(f"\n  [{i}] label={call['label']!r}  agent_type={call['agent_type']}")
        prompt = textwrap.indent(call["prompt"].strip(), "      ")
        print(f"      prompt:\n{prompt}")


async def example_1_fanout_synthesis() -> None:
    """Query → fanout 3 modules → synthesis merge."""
    _hr("例子 1：并行审查 + 汇总")

    print("\n📌 用户 Query:")
    print('  "用 workflow 并行检查 frontend、backend、database 三个模块的 API 兼容性，')
    print('   然后汇总出最终建议。"')

    ir = {
        "version": 1,
        "meta": {"name": "api_compat_review", "description": "三模块并行审查后汇总"},
        "policy": {
            "approval_mode": "trusted_workflow",
            "on_error": "continue",
            "max_agents": 10,
            "concurrency": 3,
            "wall_clock_seconds": 600,
        },
        "phases": [
            {
                "id": "inspect",
                "title": "并行检查",
                "steps": [
                    {
                        "id": "parallel_checks",
                        "type": "fanout",
                        "concurrency": 3,
                        "items": ["frontend", "backend", "database"],
                        "agent": {
                            "label_template": "check {{item}}",
                            "agent_type": "explore",
                            "prompt_template": (
                                "Inspect the {{item}} module. "
                                "List API breaking changes and integration risks."
                            ),
                        },
                    }
                ],
            },
            {
                "id": "merge",
                "title": "汇总",
                "steps": [
                    {
                        "id": "final_report",
                        "type": "synthesis",
                        "label": "final report",
                        "agent_type": "review",
                        "prompt_template": (
                            "You received parallel inspection results:\n"
                            "{{outputs.parallel_checks}}\n\n"
                            "Produce a final recommendation."
                        ),
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean"},
                                "verdict": {"type": "string"},
                                "findings": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["ok", "verdict"],
                        },
                    }
                ],
            },
        ],
    }

    print("\n📋 生成的 Workflow IR JSON:")
    _print_json(ir)

    runner = TracingRunner(
        {
            "check frontend": "frontend: 2 deprecated endpoints, auth header mismatch",
            "check backend": "backend: pagination API changed, no versioning",
            "check database": "database: migration script missing rollback",
            "final report": "All three modules have compatibility issues.",
        }
    )

    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(**ir["meta"]),
        policy=WorkflowPolicy(**ir["policy"]),
        phases=[
            WorkflowPhase(
                id="inspect",
                title="并行检查",
                steps=[
                    FanoutStep(
                        id="parallel_checks",
                        type="fanout",
                        items=["frontend", "backend", "database"],
                        concurrency=3,
                        agent=AgentStepConfig(
                            label_template="check {{item}}",
                            agent_type="explore",
                            prompt_template=(
                                "Inspect the {{item}} module. "
                                "List API breaking changes and integration risks."
                            ),
                        ),
                    )
                ],
            ),
            WorkflowPhase(
                id="merge",
                title="汇总",
                steps=[
                    SynthesisStep(
                        id="final_report",
                        type="synthesis",
                        label="final report",
                        agent_type="review",
                        prompt_template=(
                            "You received parallel inspection results:\n"
                            "{{outputs.parallel_checks}}\n\n"
                            "Produce a final recommendation."
                        ),
                        output_schema={
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean"},
                                "verdict": {"type": "string"},
                                "findings": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["ok", "verdict"],
                        },
                    )
                ],
            ),
        ],
    )

    result = await run_workflow(spec, runner=runner)

    print("\n⚙️  Step 执行顺序（spawn 的 4 个子 Agent）:")
    _print_trace(runner)

    print("\n📦 ctx.outputs 继承关系:")
    print("  parallel_checks:frontend → StepOutput(preview='frontend: 2 deprecated...')")
    print("  parallel_checks:backend  → StepOutput(preview='backend: pagination...')")
    print("  parallel_checks:database → StepOutput(preview='database: migration...')")
    print("  parallel_checks          → 合并 preview:")
    print("      'frontend: 2 deprecated...\\nbackend: pagination...\\ndatabase: migration...'")
    print("  final_report             → synthesis 读取 outputs['parallel_checks'] 的 preview")

    print("\n🏁 workflow 最终 result (= 最后 synthesis 的 structured):")
    _print_json(result.result)


async def example_2_pipeline_synthesis() -> None:
    """Pipeline with {{previous}} chain, then synthesis."""
    _hr("例子 2：流水线（扫描→审查）+ 汇总")

    print("\n📌 用户 Query:")
    print('  "对 src/auth 和 src/billing 两个目录分别做：先扫描模块结构，')
    print('   再基于扫描结果做代码审查，最后汇总两份报告。"')

    ir = {
        "version": 1,
        "meta": {"name": "two_dir_pipeline", "description": "两目录流水线审查"},
        "policy": {"concurrency": 2, "on_error": "continue"},
        "phases": [
            {
                "id": "deep_dive",
                "title": "逐目录深挖",
                "steps": [
                    {
                        "id": "dir_pipeline",
                        "type": "pipeline",
                        "items": ["src/auth", "src/billing"],
                        "stages": [
                            {
                                "label_template": "scan {{item}}",
                                "agent_type": "explore",
                                "prompt_template": "Map all files and exports under {{item}}.",
                            },
                            {
                                "label_template": "review {{item}}",
                                "agent_type": "review",
                                "prompt_template": (
                                    "Scan result for {{item}}:\n{{previous}}\n\n"
                                    "Now review security and error-handling issues."
                                ),
                            },
                        ],
                    }
                ],
            },
            {
                "id": "wrap_up",
                "title": "汇总",
                "steps": [
                    {
                        "id": "summary",
                        "type": "synthesis",
                        "label": "cross-dir summary",
                        "prompt_template": (
                            "Auth and billing pipeline results:\n"
                            "{{outputs.dir_pipeline}}\n\n"
                            "Give a single prioritized action list."
                        ),
                    }
                ],
            },
        ],
    }

    print("\n📋 生成的 Workflow IR JSON:")
    _print_json(ir)

    runner = TracingRunner(
        {
            "scan src/auth": "auth: 14 files, 3 routers, uses JWT middleware",
            "review src/auth": "auth review: token refresh missing, 1 SQL injection risk",
            "scan src/billing": "billing: 9 files, Stripe webhook handler, invoice model",
            "review src/billing": "billing review: webhook signature not verified",
            "cross-dir summary": "Priority: fix auth SQL injection, then billing webhook.",
        }
    )

    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(**ir["meta"]),
        policy=WorkflowPolicy(**ir["policy"]),
        phases=[
            WorkflowPhase(
                id="deep_dive",
                title="逐目录深挖",
                steps=[
                    PipelineStep(
                        id="dir_pipeline",
                        type="pipeline",
                        items=["src/auth", "src/billing"],
                        stages=[
                            PipelineStage(
                                label_template="scan {{item}}",
                                agent_type="explore",
                                prompt_template="Map all files and exports under {{item}}.",
                            ),
                            PipelineStage(
                                label_template="review {{item}}",
                                agent_type="review",
                                prompt_template=(
                                    "Scan result for {{item}}:\n{{previous}}\n\n"
                                    "Now review security and error-handling issues."
                                ),
                            ),
                        ],
                    )
                ],
            ),
            WorkflowPhase(
                id="wrap_up",
                title="汇总",
                steps=[
                    SynthesisStep(
                        id="summary",
                        type="synthesis",
                        label="cross-dir summary",
                        prompt_template=(
                            "Auth and billing pipeline results:\n"
                            "{{outputs.dir_pipeline}}\n\n"
                            "Give a single prioritized action list."
                        ),
                    )
                ],
            ),
        ],
    )

    result = await run_workflow(spec, runner=runner)

    print("\n⚙️  Step 执行顺序（注意 pipeline 的 {{previous}} 传递）:")
    _print_trace(runner)

    print("\n📦 关键继承链（以 src/auth 为例）:")
    print("  stage1 scan src/auth")
    print("    prompt = 'Map all files... under src/auth.'")
    print("    → text = 'auth: 14 files, 3 routers...'")
    print("    → preview = 'auth: 14 files, 3 routers, uses JWT middleware'")
    print()
    print("  stage2 review src/auth")
    print("    {{previous}} 被替换成 stage1 的 preview（不是全文！）")
    print("    prompt = 'Scan result for src/auth:\\nauth: 14 files...\\n\\nNow review...'")
    print("    → text = 'auth review: token refresh missing...'")
    print()
    print("  ctx.outputs['dir_pipeline:src/auth'] = stage2 的最终 StepOutput")
    print("  ctx.outputs['dir_pipeline'] = 两个 item 的 preview 合并")

    print("\n🏁 workflow 最终 result (无 output_schema → 取 synthesis.text):")
    print(f"  {result.result!r}")


async def example_3_full_combo() -> None:
    """agent → fanout → pipeline → synthesis — full combo."""
    _hr("例子 3：四种类型的完整组合")

    print("\n📌 用户 Query:")
    print('  "先定审查范围，再并行粗查 3 个包，对风险最高的包做扫描→深挖流水线，')
    print('   最后出结构化 JSON 报告。"')

    ir = {
        "version": 1,
        "meta": {"name": "full_combo_audit", "description": "四步组合审查"},
        "policy": {"concurrency": 2, "max_agents": 12},
        "phases": [
            {
                "id": "scope",
                "title": "定范围",
                "steps": [
                    {
                        "id": "define_scope",
                        "type": "agent",
                        "label": "scope planner",
                        "agent_type": "general",
                        "prompt": "List the 3 highest-risk packages in this monorepo for API audit.",
                    }
                ],
            },
            {
                "id": "broad",
                "title": "粗查",
                "steps": [
                    {
                        "id": "quick_scan",
                        "type": "fanout",
                        "items": ["pkg-a", "pkg-b", "pkg-c"],
                        "agent": {
                            "label_template": "quick {{item}}",
                            "agent_type": "explore",
                            "prompt_template": "Quick API surface scan of {{item}}. One paragraph.",
                        },
                    }
                ],
            },
            {
                "id": "deep",
                "title": "深挖",
                "steps": [
                    {
                        "id": "risk_pipeline",
                        "type": "pipeline",
                        "items": ["pkg-a"],
                        "stages": [
                            {
                                "label_template": "map {{item}}",
                                "prompt_template": "List all public exports of {{item}}.",
                            },
                            {
                                "label_template": "audit {{item}}",
                                "prompt_template": (
                                    "Exports of {{item}}:\n{{previous}}\n\n"
                                    "Flag breaking changes vs v1."
                                ),
                            },
                        ],
                    }
                ],
            },
            {
                "id": "report",
                "title": "出报告",
                "steps": [
                    {
                        "id": "json_report",
                        "type": "synthesis",
                        "label": "JSON report",
                        "agent_type": "review",
                        "prompt_template": (
                            "Scope:\n{{outputs.define_scope}}\n\n"
                            "Quick scans:\n{{outputs.quick_scan}}\n\n"
                            "Deep audit:\n{{outputs.risk_pipeline}}\n\n"
                            "Return structured verdict."
                        ),
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean"},
                                "verdict": {"type": "string"},
                                "risk_packages": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    }
                ],
            },
        ],
    }

    print("\n📋 生成的 Workflow IR JSON:")
    _print_json(ir)

    runner = TracingRunner(
        {
            "scope planner": "Top risks: pkg-a (auth), pkg-b (payments), pkg-c (notifications)",
            "quick pkg-a": "pkg-a: 12 endpoints, 2 undocumented",
            "quick pkg-b": "pkg-b: stable, well documented",
            "quick pkg-c": "pkg-c: 3 experimental endpoints",
            "map pkg-a": "pkg-a exports: login, refresh, revoke, validate",
            "audit pkg-a": "pkg-a: revoke endpoint removed in v2 without deprecation",
            "JSON report": "structured report body",
        }
    )

    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(**ir["meta"]),
        policy=WorkflowPolicy(**ir["policy"]),
        phases=[
            WorkflowPhase(
                id="scope",
                title="定范围",
                steps=[
                    AgentStep(
                        id="define_scope",
                        type="agent",
                        label="scope planner",
                        agent_type="general",
                        prompt="List the 3 highest-risk packages in this monorepo for API audit.",
                    )
                ],
            ),
            WorkflowPhase(
                id="broad",
                title="粗查",
                steps=[
                    FanoutStep(
                        id="quick_scan",
                        type="fanout",
                        items=["pkg-a", "pkg-b", "pkg-c"],
                        agent=AgentStepConfig(
                            label_template="quick {{item}}",
                            agent_type="explore",
                            prompt_template="Quick API surface scan of {{item}}. One paragraph.",
                        ),
                    )
                ],
            ),
            WorkflowPhase(
                id="deep",
                title="深挖",
                steps=[
                    PipelineStep(
                        id="risk_pipeline",
                        type="pipeline",
                        items=["pkg-a"],
                        stages=[
                            PipelineStage(
                                label_template="map {{item}}",
                                prompt_template="List all public exports of {{item}}.",
                            ),
                            PipelineStage(
                                label_template="audit {{item}}",
                                prompt_template=(
                                    "Exports of {{item}}:\n{{previous}}\n\n"
                                    "Flag breaking changes vs v1."
                                ),
                            ),
                        ],
                    )
                ],
            ),
            WorkflowPhase(
                id="report",
                title="出报告",
                steps=[
                    SynthesisStep(
                        id="json_report",
                        type="synthesis",
                        label="JSON report",
                        agent_type="review",
                        prompt_template=(
                            "Scope:\n{{outputs.define_scope}}\n\n"
                            "Quick scans:\n{{outputs.quick_scan}}\n\n"
                            "Deep audit:\n{{outputs.risk_pipeline}}\n\n"
                            "Return structured verdict."
                        ),
                        output_schema={
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean"},
                                "verdict": {"type": "string"},
                                "risk_packages": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    )
                ],
            ),
        ],
    )

    result = await run_workflow(spec, runner=runner)

    print("\n⚙️  全部 spawn 顺序（共 8 个子 Agent）:")
    for i, call in enumerate(runner.calls, 1):
        print(f"  [{i}] {call['label']}")

    print("\n📦 outputs 字典最终形态:")
    outputs_desc = {
        "define_scope": "agent step 直接产出",
        "quick_scan:pkg-a/b/c": "fanout 每项独立产出",
        "quick_scan": "fanout 合并 preview",
        "risk_pipeline:pkg-a": "pipeline 最后 stage 产出",
        "risk_pipeline": "pipeline 合并 preview",
        "json_report": "synthesis 最终产出（含 structured）",
    }
    for k, v in outputs_desc.items():
        print(f"  outputs['{k}'] ← {v}")

    print("\n🔗 synthesis 渲染后的 prompt 长什么样（模拟）:")
    mock_outputs = {
        "define_scope": make_step_output(runner._responses["scope planner"]),
        "quick_scan": make_step_output(
            "pkg-a: 12 endpoints...\npkg-b: stable...\npkg-c: 3 experimental..."
        ),
        "risk_pipeline": make_step_output("pkg-a: revoke endpoint removed in v2..."),
    }
    rendered = render_template(
        ir["phases"][3]["steps"][0]["prompt_template"],
        outputs=mock_outputs,
    )
    print(textwrap.indent(rendered, "  "))

    print("\n🏁 workflow 最终 result:")
    _print_json(result.result)


async def main() -> None:
    await example_1_fanout_synthesis()
    await example_2_pipeline_synthesis()
    await example_3_full_combo()
    print("\n" + "=" * 72)
    print("  演示结束 — 以上均由 FakeRunner 模拟，未调用真实 LLM")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
