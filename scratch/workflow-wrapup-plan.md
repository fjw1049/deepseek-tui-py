# Workflow 引擎收尾实现计划

## 目标
三个收尾项，让 workflow 引擎从"能跑"到"能放心用"。原则：最小改动、向后兼容、opt-in 优先。不碰上一轮 review 标的 bug（原子写、checkpoint 异常、loop resume 轮次），避免范围蔓延。

---

## 改动 1：token_budget 诚实化（最低风险，先做）

**问题**：`policy.token_budget` 能解析（`models.py:304/318`）、能存盘（`store.py:364`），但 runtime 从不读它。用户设了以为有成本护栏，实际没有--虚假承诺。

**方案**：保留字段（不破坏现有 spec），加注释 + 运行时警告，不 advertised。
- `workflow/models.py:50` `token_budget` 字段上方加注释：`# NOTE: declared but not yet enforced; no cost cap is applied at runtime.`
- `workflow/runtime.py` `run_workflow`（spec 解析后、执行前，约 :88 附近 `ctx = WorkflowRunContext(...)` 之后）：若 `spec.policy.token_budget is not None`，调 `log("warning: policy.token_budget is set but not yet enforced; no cost cap will be applied")`
- 不改 `tools/workflow.py` 的 tool description（本就没 specifically advertised token_budget）
- 不改 `store.py`（保留存盘，向前兼容未来实现）

**测试**（`tests/workflow/test_runtime_fake_runner.py`）：
- `test_token_budget_warning_emitted`：构造带 `token_budget=50000` 的 spec，用 FakeRunner 跑，断言 `on_log` 收到含 "not yet enforced" 的警告；断言不带 token_budget 时不发警告。

---

## 改动 2：workflow_list 工具（新工具，纯加法）

**问题**：`catalog.list_workflows()`（`catalog.py:138`）和 `store.list_runs()`（`store.py:184`）都已实现但没暴露。模型发现不了用户自定义的命名工作流，也列不出历史 run--命名工作流 + resume 两个功能都半残。

**方案**：在 `tools/workflow.py` 新增 `WorkflowListTool(ToolSpec)`，匹配 `TaskListTool`（`tools/task/tools.py:109`）的模式。在 `build_default_registry`（`registry.py:643-646`，`cfg.features.subagents` 块）注册。

**`WorkflowListTool` 设计**：
- `name()` = `"workflow_list"`
- `description()` = `"List available named workflows (bundled presets + project + user) and recent workflow runs. Call this before picking a workflow name or resuming a run by run_id."`
- `input_schema()` = `{"type":"object","properties":{"runs_limit":{"type":"integer","minimum":1,"default":20}},"additionalProperties":false}`
- `capabilities()` = `[ToolCapability.READ_ONLY]`（免审批，`approval_requirement` 默认 AUTO）
- `execute(input_data, context)`：
  - `workflows = list_workflows(cwd=context.working_directory)` -> 投影成 `[{"name","description","source"}]`
  - `runs_limit = input_data.get("runs_limit") or 20`
  - `runs = list_runs(workspace=context.working_directory, limit=runs_limit)` -> 投影成 `[{"run_id","status","task","created_at","updated_at","completed_steps"}]`（只取摘要，不返回完整 outputs/spec，避免 payload 过大）
  - `return ToolResult(success=True, content=f"{len(workflows)} workflow(s), {len(runs)} run(s)", metadata={"workflows": ..., "runs": ...})`
- 容错：`list_workflows` 已对单条失败容错（catalog.py try/except）；`list_runs` 已 try/except（store.py:198）。整体返回能返回的，不因单条坏 record 崩。

**注册**：`registry.py:643-646` 块内 `registry.register(WorkflowTool())` 后加 `registry.register(WorkflowListTool())`。

**import**：`tools/workflow.py` 顶部加 `from deepseek_tui.workflow.catalog import list_workflows` 和 `from deepseek_tui.workflow.store import list_runs`。

**测试**（`tests/workflow/test_catalog.py` 或新 `test_workflow_list_tool.py`）：
- `test_workflow_list_returns_presets_and_runs`：用 tmp workspace，放一个命名工作流 JSON + 跑一次 run 留 record，构造 ToolContext，调 `WorkflowListTool().execute`，断言 metadata.workflows 含 preset 和自定义工作流、metadata.runs 含那条 record。

---

## 改动 3：per-step 可配置超时（opt-in，复用已有 cancel 机制）

**问题**：`DeepSeekAgentRunner.run`（`runtime.py:723`）硬编码 `timeout_s = WAIT_TIMEOUT_MS / 1000`（1 小时）。一个 hang 的 agent step 最多吃 1h，远超 `wall_clock`，等于没保护。**机制其实已存在**（deadline + `_try_cancel` 取消 agent + 返回 None，:745-747），只是 timeout 值不可配。

**方案**：加 `timeout_seconds` 到 step 配置，透传到 `runner.run`，复用现有 deadline/cancel 逻辑。不设则保持 1h fallback（零回归）。超时返回 None，与现有 agent-FAILED 语义一致（不触发 fail_fast，step 无输出，`on_error: continue` 时 synthesis 容忍缺失）。

**models.py 改动**：
- `AgentStepConfig`（:55）加 `timeout_seconds: int | None = None`
- `AgentStep`（:67）加 `timeout_seconds: int | None = None`
- `SynthesisStep`（:113）加 `timeout_seconds: int | None = None`
- （`PipelineStage` 不用单独加--pipeline 用 `AgentStepConfig` 构造 stage，自动继承）
- `_parse_agent_config`（:639）加 `timeout_seconds=_parse_int_opt(raw.get("timeout_seconds"), "timeout_seconds", min_val=1, max_val=3600)`
- `_parse_step` agent 分支（:346 附近）和 synthesis 分支（:442 附近）加 `timeout_seconds=...`
- 新增 `_parse_int_opt` helper（或复用 `_parse_int` + 显式范围校验）：None 时返回 None，否则校验 1..3600

**runtime.py 改动**：
- `WorkflowRunner.run` Protocol（:642）签名加 `timeout_seconds: float | None = None`
- `DeepSeekAgentRunner.run`（:681）签名加 `timeout_seconds: float | None = None`
- `:723` 改 `timeout_s = (timeout_seconds if timeout_seconds is not None else WAIT_TIMEOUT_MS / 1000)`（其余 deadline + _try_cancel 逻辑不变）
- `run_agent_cfg`（:238）签名加 `timeout_seconds: int | None = None`，传给 `runner.run(..., timeout_seconds=timeout_seconds)`
- agent dispatch（:318 附近）传 `cfg.timeout_seconds`（从 AgentStep）
- fanout `_fanout_item`（:351 附近）传 `s.agent.timeout_seconds`
- pipeline `_pipeline_item`（:389 附近）传 `stage` 对应 config 的 timeout（pipeline 用 AgentStepConfig 构造，已有字段）
- synthesis dispatch（:456 附近）传 `step.timeout_seconds`

**测试**（`tests/workflow/test_runtime_fake_runner.py`）：
- `test_agent_step_timeout_cancels_slow_agent`：FakeRunner 加 `delay` 能力模拟慢 agent，spec 设 `timeout_seconds=1`，断言 step 在 ~1s 被中断、返回 None、`on_error=continue` 时后续 step 仍跑。
- 可能需 FakeRunner 支持"被取消时返回 None"语义；若 FakeRunner 不好模拟超时，改为直接测 `DeepSeekAgentRunner` 层（mock SubAgentManager.get_result 一直返回 RUNNING 直到超时）。

---

## 改动 4：文档/指南同步
- `workflow/prompt_guidelines.md`：加 `timeout_seconds` 字段说明；token_budget 标注"declared but not enforced"。
- `integrations/skills.py` 的 `WORKFLOW_GUIDE_BODY`：同步加 `timeout_seconds` 说明 + 提一句 `workflow_list` 工具用法。
- `tools/workflow.py` 的 `WorkflowTool.description()`：加一句 "Use `workflow_list` to discover named workflows and past runs before choosing `name` or `run_id`."

---

## 文件改动清单
| 文件 | 改动 | 风险 |
|------|------|------|
| `workflow/models.py` | token_budget 注释；3 个 step 类加 timeout_seconds；parse+校验 | 低（加字段） |
| `workflow/runtime.py` | run_workflow 加 token_budget 警告；run_agent_cfg/runner.run 透传 timeout_seconds；deadline 用透传值 | 低（opt-in，fallback 不变） |
| `tools/workflow.py` | 新增 WorkflowListTool；WorkflowTool description 加提示 | 低（纯加法） |
| `tools/registry.py` | 注册 WorkflowListTool | 低 |
| `integrations/skills.py` | WORKFLOW_GUIDE_BODY 同步 | 低 |
| `workflow/prompt_guidelines.md` | 文档同步 | 低 |
| `tests/workflow/` | 3 个新测试 | - |

## 验证
- `uv run python -m pytest tests/workflow/ -q` 全绿（现有 42 + 新增 3）
- 手动：`workflow_list` 工具能列出 3 个 preset + 历史 run
- 手动：spec 设 `timeout_seconds: 2` + 慢 agent，确认 ~2s 中断

## 不在本计划内（明确排除）
- `save_run` 原子写、`on_checkpoint` 异常兜底、loop round 持久化、`/workflow list` slash 命令、条件分支 step、step retry、deep-research/impact-review preset。这些是后续单独议题，不混入本次收尾。

## 实施顺序
1. token_budget 诚实化（10 min）
2. workflow_list 工具 + 注册 + 测试（30 min）
3. per-step timeout 透传 + 测试（1 h）
4. 文档/skill 同步（15 min）
5. 跑全量 workflow 测试确认绿
