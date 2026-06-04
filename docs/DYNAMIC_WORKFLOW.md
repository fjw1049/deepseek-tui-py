# DeepSeek Dynamic Workflow — 实施规格

> 合并 Pi dynamic workflows 语义审阅、Cursor 方案取舍、Codex IR 方案（2026-06-04）  
> 本文档为**实施规格**：实现逻辑、模块划分、分阶段计划。不含实现代码。  
> 参考：`pi-main`（Pi 扩展与 agent-loop）、`pi-dynamic-workflows`（语义参考，**不**直接依赖 npm 包）

### 修订记录

| 版本 | 变更 |
|------|------|
| v1 | 初版：Workflow IR 为核心；DeepSeek 原生 `workflow` 工具；分阶段计划 |
| v2 | Codex 审阅修订：SubAgent API 前置改造、审批接入点、进度事件身份、取消/超时、prompt 注入、outputs 截断、移除顶层 `result_schema` |

---

## 1.5 实施前必读（v2 规格修订）

> 对照当前代码审阅（2026-06-04）。**Phase 3 之前必须先完成 §1.5.1 两项 P0 改造**，否则 structured 与 trusted 审批会实现到一半发现 API 承不住。

### 1.5.1 P0：现有 API 差距与前置改造

#### A. 结构化输出通道（当前不可直接实现）

**现状（代码事实）**

| 位置 | 现状 |
|------|------|
| `SpawnRequest` | 无 `output_schema` / `extra_tools`（`manager.py`） |
| `SubAgent.result` | `str \| None` |
| `SubAgentExecutor` | `Callable[..., Awaitable[str]]` |
| `build_subagent_registry` | 无 `extra_tools` 参数（`builder.py`） |
| `run_subagent_loop` | 返回 `str`（最终 assistant 文本） |

**v2 规格（必须先做，再写 workflow）**

1. 新增 **`AgentRunOutput`**（放 `workflow/models.py` 或 `tools/subagent/output.py`）：

   ```python
   @dataclass
   class AgentRunOutput:
       text: str
       structured: dict[str, Any] | list[Any] | None = None
   ```

2. **`SpawnRequest` 增加** `output_schema: dict[str, Any] | None = None`（JSON Schema）。

3. **`build_subagent_registry` 增加** `extra_tools: list[ToolSpec] | None = None`，在 `filter_by_names` 之后 `register_all(extra_tools)`。

4. **`run_subagent_loop` 修改**：
   - 若 `agent` 携带 schema（经 `SpawnRequest` 或 spawn 时挂到 `SubAgent` 字段）：注册 `StructuredOutputTool(schema=...)`；
   - 执行到 `structured_output` 成功 → **break**，`structured = tool_result.metadata["value"]`；
   - 返回 **`AgentRunOutput`**，不再只返回字符串。

5. **`SubAgentExecutor` / `real_subagent_executor`**：返回类型改为 `AgentRunOutput`；`SubAgent.result` 存 **预览文本**，另增 `SubAgent.structured_result: Any | None`（或仅在 `SubAgentResult` 快照里带 `structured` 字段）。

6. **workflow `outputs[step_id]`** 存：

   ```python
   @dataclass
   class StepOutput:
       text: str
       structured: Any | None
       preview: str          # 供模板注入，已截断
   ```

**不要**：把 JSON dict `json.dumps` 进 `SubAgent.result` 再让 synthesis 解析文本。

#### B. `trusted_workflow` 审批（`metadata` 无效）

**现状**：子 agent 工具审批读 **`SubAgentRuntime.auto_approve`**（`run_subagent_loop` → `_execute_subagent_tool`），在 `Engine.create` 时从 `approval_handler.auto_approve_enabled()` **固化一次**。写 `ToolContext.metadata["workflow_auto_approve"]` **不会生效**。

**v2 规格**

`DeepSeekAgentRunner` 每次 spawn 使用 **workflow 专用 runtime**，不要共用会话级 `loop_runtime` 的 `auto_approve`：

```python
# 伪代码：agent_runner.py
def _runtime_for_policy(base: SubAgentRuntime, policy: WorkflowPolicy) -> SubAgentRuntime:
    if policy.approval_mode == "trusted_workflow":
        return replace(base, auto_approve=True)
    if policy.approval_mode == "strict":
        return replace(base, auto_approve=False)
    # analysis_only
    return replace(base, auto_approve=True)  # 配合只读 allowlist
```

| `approval_mode` | `auto_approve` | `allowed_tools` |
|-----------------|----------------|-----------------|
| `analysis_only` | `True` | **强制** explore 类只读 allowlist（`read_file`, `grep_files`, `list_dir`, `file_search`, git read-only 等）；忽略 IR 写工具 |
| `trusted_workflow` | `True` | IR 指定；未指定则 agent 类型默认集 |
| `strict` | `False` | IR 指定；写/执行工具在子 loop 返回 Error（现有行为） |

`workflow` 工具本身仍 **`REQUIRES_APPROVAL` 一次**（整段编排），与上表子 agent 内策略分离。

**实现注意**：`SubAgent.loop_runtime` 来自 `manager._loop_runtime.with_spawn_depth(...)`。workflow spawn 需能注入 **per-spawn** 的 `auto_approve`（例如在 `SpawnRequest` 增加 `auto_approve: bool | None`，spawn 时 `replace(loop_runtime, auto_approve=...)` 再 `with_spawn_depth`）。

### 1.5.2 P1：接口写实修订

#### C. `WorkflowProgressEvent` 身份字段

```python
@dataclass(frozen=True)
class WorkflowProgressEvent:
    tool_call_id: str          # 与 ToolCallEvent 一致，Workbench upsert 主键
    thread_id: str | None      # 可选，ThreadManager 填充
    workflow_name: str
    snapshot: WorkflowSnapshot
    completed: bool = False    # True = 终态，可合并进 tool result
```

- ThreadManager：`workflow.progress` SSE payload **必须含 `tool_call_id`**，对同一 `item_id == tool_call_id` upsert（对标 `ToolResultEvent.tool_call_id`）。
- 持久化：可复用 `TurnItemKind.TOOL_CALL` + `metadata.workflow_progress=True`，或专用 kind。

#### D. 取消 / `wall_clock_seconds`

仅依赖 `parent_cancel` **不够**：fanout 已 spawn 的 agent 在 `gather` 阻塞时，需在 workflow 层：

1. **`WorkflowRunContext.spawned_agent_ids: list[str]`** — 每次 `spawn` 后记录；
2. **`asyncio.create_task` 包装** fanout/pipeline 分支时登记，便于 cancel；
3. **取消路径**（Esc / wall_clock / fail_fast 中止）：
   - 设本地 `workflow_cancel_event`；
   - 对每个 running id 调用 **`SubAgentManager.cancel(agent_id)`**（`manager.py:548`）；
   - `gather` 使用 `return_exceptions=True`，已取消分支 → `skipped`；
4. `wall_clock_seconds`：`asyncio.wait_for(run_workflow(...), timeout=...)` 外层包裹，超时走同一 teardown。

#### E. 主模型指南注入（双通道）

当前 `build_system_prompt()` **无** `active_tools` 参数，也无 Pi 式 `promptGuidelines` 汇总（`prompts.py`）。

| 优先级 | 做法 |
|--------|------|
| **v1 必做** | 把 §7 要点写进 **`WorkflowTool.description` + `input_schema` 各字段 description**（模型看 tool 定义即够） |
| **v1.1 可选** | `Engine._build_tool_catalog` / `prepare_turn_for_model` 增加：若 active tools 含 `workflow`，追加 `## Workflow tool` 段落（新建 `workflow/prompt_guidelines.md` 片段） |

不要阻塞 Phase 3 on prompts.py 大改。

### 1.5.3 P2：语义收紧

#### F. `{{outputs.*}}` 截断（防 context 爆炸）

`template.py` 默认规则：

| 引用 | 行为 |
|------|------|
| `{{outputs.<step_id>}}` | 注入 **`StepOutput.preview`**（默认最多 2000 字符 / step） |
| `{{outputs.<step_id>.full}}` | 注入完整 `text`（仍设硬上限，如 32KB，超出附 `…[truncated]`） |
| `{{outputs}}` | 所有已完成 step 的 **一行 preview** 列表，不注入全文 |
| fanout 多项 | 每项 preview 最多 800 字符 |

校验：若 synthesis 引用 `outputs.X` 且 X 为 fanout，校验器提示「建议用 summary step」可选 warning。

#### G. 顶层 `result_schema` — v1 移除

- **v1**：仅 **`synthesis` / `agent` step 上的 `output_schema`** 定义结构化终态。
- **workflow 最终 `result`**：`outputs[<last_synthesis_step_id>].structured` 若存在，否则 `.text`；若无 synthesis step，`{ "outputs": { step_id: preview } }`。
- 顶层 `result_schema` 字段 **v2 再引入**（仅作最终 JSON Schema 校验器），避免「隐藏 synthesis step」歧义。

---

## 1. 目标与定案

### 1.1 要解决的问题

| 现状 | 目标 |
|------|------|
| 主模型多次 `agent_spawn` / `delegate_to_agent` 手工编排 | 单次 `workflow` 工具提交**结构化计划**，运行时确定性 fan-out / fan-in |
| 子 agent 进度靠 Mailbox 卡片，无「整段编排」视图 | 可校验、可渲染、可取消的 **Workflow 进度树** |
| 多路结果合成靠自然语言 JSON，易失败 | **structured_output** 子工具 + 子 loop 早停 |
| 直接接入 `pi-dynamic-workflows` npm 包 | **不可行**（Python/TS 栈、ToolSpec vs ToolDefinition、UI/SSE 不同） |

### 1.2 一句话定案

**`workflow` 是普通 `ToolSpec`：主模型提交 Workflow Spec（JSON IR）→ 校验 → 解释执行 → 每步经 `DeepSeekAgentRunner` 复用 `SubAgentManager` + `run_subagent_loop` → 流式进度事件 + 最终 `ToolResult` 回主 Engine。**

**核心执行层 = Workflow IR，不是 Python `exec`、不是 Node `vm`。**  
Pi / Cursor 提到的脚本仅可作为**可选适配器**（`script → IR`），不作 v1 主路径。

### 1.3 设计原则

1. **宿主为主**：`Engine` 主回合不被改写；workflow 在**一次工具调用内**完成，不走 `subagent handoff` 续回合。
2. **IR 优先**：可 schema 校验、可持久化、可单测、可渲染、可演进。
3. **复用子 agent**：in-process `run_subagent_loop`，**不** spawn 新 `deepseek-tui` 进程（不断审批 / Mailbox / cancel）。
4. **语义对齐 Pi**：保留 `phase / agent / parallel / pipeline / synthesis / budget` 语义，不照搬 VM 实现。
5. **平台适配隔离**：编排内核只依赖 `AgentRunner` 协议；DeepSeek 绑定在 L3。
6. **失败可恢复**：单 step 失败 → `null` + log（默认 continue）；整段可 cancel。

### 1.4 明确不做（v1）

- Python / JS 可执行 DSL 作为主入口
- 嵌套完整 `Engine.create`  per step（留给 `TaskManager` 长任务场景）
- `multi_tool_use.parallel` 充当 workflow 并发（只读工具批，语义不同）
- `isolation: worktree`（除非后续真接 git worktree）
- workflow 断点恢复 / 持久化队列（可 Phase 8）
- 直接 `import @earendil-works/pi-*` 或 Node 侧车跑 Pi 包

---

## 2. 背景：Pi 里 workflow 真实链路（对照用）

Pi 中 dynamic workflow **不是**独立 agent 系统，而是**普通扩展工具**：

```
extension 注册 workflow tool
  → AgentSession 刷新工具表 + promptGuidelines
  → agent-loop 执行 tool
  → workflow tool 内：node:vm 跑 JS，多次 agent()
  → 每次 agent()：createAgentSession + SessionManager.inMemory
  → onUpdate 流式进度 → renderResult
  → tool result 回主 agent
```

关键源码锚点（`pi-main` / `pi-dynamic-workflows`）：

| 能力 | Pi 位置 |
|------|---------|
| Tool 契约 | `packages/coding-agent/src/core/extensions/types.ts` — `execute(..., signal, onUpdate, ctx)` |
| 工具流式更新 | `packages/agent/src/agent-loop.ts` — `tool_execution_update` |
| 扩展注册 | `pi-dynamic-workflows/extensions/workflow.ts` — `registerTool` + `session_start` 激活 |
| 子 agent | `pi-dynamic-workflows/src/agent.ts` — `createAgentSession(inMemory)` |
| 结构化结束 | `structured_output` + `terminate: true` |
| 官方 subagent 示例（不同路线） | `examples/extensions/subagent/` — **子进程** `spawn(pi)`，非本方案 |

DeepSeek 对照链：

```
WorkflowTool.execute
  → run_workflow(IR)
  → DeepSeekAgentRunner
  → SubAgentManager.spawn + wait
  → run_subagent_loop
  → WorkflowProgressEvent / StatusEvent → ThreadManager SSE → Workbench
  → ToolResult(metadata.workflow) → 主 Engine 继续
```

---

## 3. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│  L1 编排语义层  deepseek_tui/workflow/runtime.py                  │
│  解释 WorkflowSpec：phase / agent / fanout / pipeline / synthesis │
│  只依赖 AgentRunner + cancel + callbacks                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  L2 计划层      models.py + validate.py + template.py            │
│  JSON IR 校验、依赖检查、{{item}}/{{previous}}/{{outputs.*}}       │
│  可选 adapters/pi_js.py（Phase 7）                               │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  L3 DeepSeek 适配  tools/workflow_tool.py + agent_runner.py      │
│  ToolSpec、审批策略、Engine emit/cancel、SubAgentManager           │
└────────────────────────────┬────────────────────────────────────┘
                             │
         现有：Engine / ThreadManager / Workbench / Mailbox
```

---

## 4. Workflow IR（v1 规范）

### 4.1 顶层结构

```json
{
  "version": 1,
  "meta": {
    "name": "repo_review",
    "description": "multi-agent review"
  },
  "policy": {
    "approval_mode": "trusted_workflow",
    "on_error": "continue",
    "max_agents": 10,
    "concurrency": 4,
    "wall_clock_seconds": 600,
    "token_budget": null
  },
  "phases": []
}
```

| 字段 | 说明 |
|------|------|
| `meta.name` | 必填，snake_case，非空 |
| `meta.description` | 必填，人类可读 |
| `policy.approval_mode` | 见 §6.3（接入 `SubAgentRuntime.auto_approve`，非 metadata） |
| `policy.on_error` | `continue`（默认，失败 step → null）或 `fail_fast` |
| `policy.max_agents` | 与 `SubAgentManager` 上限对齐，默认 10 |
| `policy.concurrency` | fanout / pipeline 跨 item 并发上限，≤ max_agents |
| `policy.wall_clock_seconds` | 整段 workflow 墙钟超时；触发时 cancel 所有 `spawned_agent_ids`（§1.5.2-D） |
| `policy.token_budget` | 可选，字符估算即可（对标 Pi `budget`） |

> v1 **无**顶层 `result_schema`；结构化终态只通过某个 step 的 `output_schema`（通常是最终 `synthesis`）。见 §1.5.3-G。

### 4.2 Phase 与 Step

每个 **phase**：`id`（唯一）、`title`、`steps[]`。

#### Step 类型一览

| `type` | 语义 | 对标 Pi |
|--------|------|---------|
| `agent` | 单次 spawn + 同步 wait | `await agent(...)` |
| `fanout` | 对 `items[]` 并行，每项一次 agent | `parallel(() => agent(...))` |
| `pipeline` | 对 `items[]` 每项按 `stages[]` 串行 | `pipeline(items, s1, s2, ...)` |
| `synthesis` | 用已完成 outputs 拼 prompt 再 agent | 最终 synthesis agent |

#### `agent` step

```json
{
  "id": "api_review",
  "type": "agent",
  "label": "api reviewer",
  "agent_type": "review",
  "model": null,
  "allowed_tools": null,
  "prompt": "Review runtime API compatibility...",
  "output_schema": null
}
```

#### `fanout` step

```json
{
  "id": "parallel_checks",
  "type": "fanout",
  "concurrency": 4,
  "items": ["engine", "tools", "workbench"],
  "agent": {
    "label_template": "inspect {{item}}",
    "agent_type": "explore",
    "prompt_template": "Inspect {{item}} and report integration risks.",
    "output_schema": null
  }
}
```

#### `pipeline` step

```json
{
  "id": "deep_dive",
  "type": "pipeline",
  "items": ["src/deepseek_tui/engine", "src/deepseek_tui/tools"],
  "stages": [
    {
      "label_template": "scan {{item}}",
      "agent_type": "explore",
      "prompt_template": "Map modules under {{item}}."
    },
    {
      "label_template": "review {{item}}",
      "agent_type": "review",
      "prompt_template": "Prior findings:\n{{previous}}\n\nReview {{item}}."
    }
  ]
}
```

#### `synthesis` step

```json
{
  "id": "final",
  "type": "synthesis",
  "label": "final summary",
  "agent_type": "review",
  "prompt_template": "Synthesize:\n{{outputs.parallel_checks}}\n{{outputs.api_review}}\n\nReturn a clear recommendation.",
  "output_schema": {
    "type": "object",
    "properties": {
      "ok": { "type": "boolean" },
      "verdict": { "type": "string" },
      "findings": { "type": "array", "items": { "type": "string" } }
    },
    "required": ["ok", "verdict"]
  }
}
```

### 4.3 模板变量（v1）

由 `workflow/template.py` 在运行时解析，**不**交给模型拼 IR。默认 **preview 注入**，见 §1.5.3-F。

| 变量 | 含义 |
|------|------|
| `{{item}}` | fanout / pipeline 当前 item |
| `{{previous}}` | pipeline 当前 item 上一 stage 的 `StepOutput.preview` |
| `{{outputs.<step_id>}}` | 该 step 的 **preview**（截断后） |
| `{{outputs.<step_id>.full}}` | 该 step 的完整 `text`（带上限） |
| `{{outputs}}` | 所有已完成 step 的 **一行 preview** 索引，非全文 |

### 4.4 校验规则（`workflow/validate.py`）

- Pydantic / JSON Schema 结构校验
- `phase.id`、`step.id` 全局唯一
- `fanout.items` 非空、长度上限（建议 ≤ 16）
- `concurrency <= policy.max_agents`
- `synthesis` / `prompt_template` 引用的 `outputs.*` 必须指向已定义且**拓扑在前**的 step id
- 至少一个 step 会触发 agent（防止空跑）
- 校验失败 → `ToolError`，不进入 runtime

### 4.5 工具入参（对外）

v1 **仅推荐**：

```json
{
  "spec": { "...": "完整 Workflow IR 对象" }
}
```

**不要** markdown fence；**不要**把 IR 塞进代码字符串。

Phase 7 可选：

```json
{
  "script": "export const meta = { ... } ..."
}
```

由 `adapters/pi_js.py` 转为同一 IR 再执行（非 v1）。

---

## 5. 运行时逻辑

### 5.1 核心数据结构

```python
# workflow/models.py（示意）

class WorkflowAgentRun:
    step_id: str
    label: str
    phase_id: str
    status: Literal["queued", "running", "done", "error", "skipped"]
    agent_id: str | None
    result_preview: str | None
    error: str | None

class WorkflowSnapshot:
    name: str
    description: str
    phases: list[str]              # 顺序
    current_phase: str | None
    agents: list[WorkflowAgentRun]
    logs: list[str]
    done_count: int
    total_count: int
    duration_ms: int | None
    result: Any | None
```

### 5.2 AgentRunner 协议（L1 唯一执行依赖）

```python
@dataclass
class StepOutput:
    text: str
    structured: Any | None
    preview: str

class AgentRunner(Protocol):
    async def run(
        self,
        *,
        prompt: str,
        label: str,
        agent_type: str = "general",
        model: str | None = None,
        allowed_tools: list[str] | None = None,
        output_schema: dict | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> StepOutput | None:   # None = 失败
        ...
```

- 失败返回 `None`，写 workflow log，不抛到主回合（`on_error: continue`）
- `fail_fast`：首个失败即中止整段 workflow，并触发 §1.5.2-D teardown

### 5.3 `run_workflow` 执行流程

```
1. validate(spec)
2. snapshot = empty(meta)
3. ctx = WorkflowRunContext(outputs={}, spent_tokens=0, spawned_agent_ids=[])
4. for phase in spec.phases:
     on_phase(phase.title)
     for step in phase.steps:
       check cancel_event / wall_clock / budget
       dispatch(step):
         agent    → runner.run(...)
         fanout   → semaphore.gather(items)
         pipeline → per item: for stage in stages: runner.run(...)
         synthesis→ render template(outputs.*) → runner.run(..., output_schema)
       store outputs[step.id] = StepOutput
       append spawned_agent_ids on each spawn
       update snapshot agents[]
       on_progress(tool_call_id, snapshot, completed=False)
5. result = outputs[last_synthesis_step].structured or .text
     (若无 synthesis：{ "outputs": { id: preview } }；见 §1.5.3-G)
6. assert json_serializable(result)
7. on_progress(..., completed=True); return WorkflowRunResult(...)
```

**重要**：全程在**同一次** `WorkflowTool.execute` 内 await 完成；**不**使用 `_handle_subagent_turn_handoff`。

### 5.4 DeepSeekAgentRunner（L3）

```
policy → per-spawn SubAgentRuntime(auto_approve, allowlist)   # §1.5.1-B
SpawnRequest(..., output_schema=...)  → manager.spawn()      # §1.5.1-A
ctx.spawned_agent_ids.append(agent_id)
wait(agent_ids) → manager.wait(...)
AgentRunOutput → StepOutput(text, structured, preview=truncate(text))
```

映射：

| IR 字段 | DeepSeek |
|---------|----------|
| `label` / `label_template` | `nickname` 或 `assignment.role` |
| `agent_type` | `SubAgentType.parse()` |
| `model` | `SpawnRequest.model`（**真传**） |
| `allowed_tools` | `SpawnRequest.allowed_tools`；`analysis_only` 时由 policy **覆盖**为只读集 |
| `output_schema` | `SpawnRequest.output_schema` + `build_subagent_registry(extra_tools=[StructuredOutputTool(...)])` + loop 早停 → `StepOutput.structured` |

**不要**：在 workflow 内再调 `delegate_to_agent` / `agent_spawn` 工具。  
**不要**：写 `ToolContext.metadata["workflow_auto_approve"]`（无效，见 §1.5.1-B）。

### 5.5 并发与上限

- fanout / pipeline-跨-item：`asyncio.Semaphore(policy.concurrency)`
- 总活跃子 agent ≤ `policy.max_agents`（与 manager 默认 10 一致）
- **不复用** `multi_tool_use.parallel`（引擎层只读工具批）

### 5.6 取消与超时

| 机制 | 行为 |
|------|------|
| Esc / 父回合取消 | `Engine` 注入 `engine_cancel_event`；与 `parent_cancel` 联动 |
| workflow 内部 | `WorkflowRunContext` 维护 `spawned_agent_ids`；cancel 时对每个 running id 调 **`manager.cancel()`**（§1.5.2-D） |
| `wall_clock_seconds` | `asyncio.wait_for` 包裹整段 `run_workflow`；超时走同一 cancel teardown |
| `gather` | 周期检查 cancel；取消后 snapshot → `skipped` |
| 工具返回 | `success=False`，content 标明 `Workflow cancelled` / `timed out` |

---

## 6. 必须补的能力

### 6.1 结构化输出（P0 — 见 §1.5.1-A，先于 workflow 联调）

| 改动文件 | 改动 |
|----------|------|
| `tools/subagent/manager.py` | `SpawnRequest.output_schema`；`SubAgent.structured_result`；`run_subagent_loop` → `AgentRunOutput`；structured 早停 |
| `tools/builder.py` | `build_subagent_registry(..., extra_tools=...)` |
| `engine/executors.py` | `real_subagent_executor` 返回 `AgentRunOutput` |
| `tools/structured_output_tool.py` | 新工具；`metadata["value"]` + `metadata["terminate_subagent"]=True` |

主 Engine **不必**实现 Pi 的 `ToolResult.terminate`；子 loop 内 break 即可。

**验收**：单测 spawn 带 schema 的 agent，断言 `structured` 为 dict 且非空文本 JSON。

### 6.2 进度事件（P1，Phase 6）

```python
@dataclass(frozen=True)
class WorkflowProgressEvent:
    tool_call_id: str
    thread_id: str | None
    workflow_name: str
    snapshot: WorkflowSnapshot
    completed: bool = False
```

| 层级 | 做法 |
|------|------|
| Engine | `workflow_emit(ev)` 注入时带上当前 `tool_call_id` |
| ThreadManager | SSE `workflow.progress`，**按 `tool_call_id` upsert** 同一 turn item |
| Workbench | `ChatBlock` `kind: 'workflow'`，key = `toolCallId` |

Phase 5 过渡：`StatusEvent` 一行摘要；终态仍以 `ToolResult.metadata.workflow` 为准。

### 6.3 审批策略（P0 — 见 §1.5.1-B）

| `policy.approval_mode` | `SubAgentRuntime.auto_approve` | 工具集 |
|------------------------|-------------------------------|--------|
| `analysis_only` | `True` | **强制只读 allowlist**（覆盖 IR 写工具） |
| `trusted_workflow`（默认） | `True` | IR / agent 类型默认 |
| `strict` | `False` | IR；写/执行 → 子 loop Error |

- `workflow` 工具：**`REQUIRES_APPROVAL` 一次**（整段编排）。
- 实现：`SpawnRequest.auto_approve` 或 spawn 时 `replace(loop_runtime, auto_approve=...)`（§1.5.1-B）。

### 6.4 Engine 注入（不改 ToolSpec 签名）

在 `Engine._execute_single_tool`（或等价路径）对 `workflow` 工具：

```python
context.metadata["engine_cancel_event"] = self.handle.cancel_event
context.metadata["workflow_emit"] = lambda ev: self.handle.try_emit(ev)
```

对标现有 `rlm_progress_cb` 模式：`engine.py` 约 2094 行附近。

---

## 7. 主模型指南（promptGuidelines 等价物）

**v1 主路径**：写入 `WorkflowTool.description` + `input_schema` 字段说明（§1.5.2-E）。  
**v1.1 可选**：`prepare_turn_for_model` 在 active tools 含 `workflow` 时追加 `workflow/prompt_guidelines.md` 片段（`build_system_prompt` 当前无 active_tools 参数，勿阻塞 Phase 3）。

要点：

1. 仅当用户明确要求 workflow / 多 agent fan-out / 编排审查时使用。
2. 必须传 `spec` 对象（Workflow IR），不要 Python/JS 代码字符串。
3. 每个 agent 类 step 必须有唯一 `label` 或 `label_template`。
4. 并行探索用 `fanout`，不要手写 10 个独立 spawn。
5. 多路合并必须有 `synthesis` step，引用 `{{outputs.<step_id>}}`。
6. 失败 step 可能为 `null`，合成前必须判断。
7. 不要在 workflow 外再批量 `agent_spawn` 重复劳动。
8. 子 agent **没有**主会话里的隐式仓库上下文；prompt 里写清路径与任务。

---

## 8. 模块与文件清单

```
src/deepseek_tui/workflow/
  __init__.py
  models.py           # WorkflowSpec, Step 变体, WorkflowSnapshot, Policy
  validate.py         # 校验 + step 依赖图
  template.py         # 模板渲染
  runtime.py          # run_workflow()
  agent_runner.py     # DeepSeekAgentRunner
  adapters/
    __init__.py
    pi_js.py          # Phase 7 可选

src/deepseek_tui/tools/
  workflow_tool.py
  structured_output_tool.py
  subagent/output.py        # AgentRunOutput（可选位置）

src/deepseek_tui/tools/subagent/
  manager.py                # P0: SpawnRequest, AgentRunOutput, loop 早停

src/deepseek_tui/tools/builder.py   # P0: build_subagent_registry(extra_tools=...)

src/deepseek_tui/engine/
  events.py                 # + WorkflowProgressEvent(tool_call_id, ...)
  engine.py                 # workflow_emit / engine_cancel_event 注入
  executors.py              # P0: real_subagent_executor 返回类型

src/deepseek_tui/tools/
  builder.py                # register WorkflowTool

src/deepseek_tui/workflow/
  prompt_guidelines.md      # v1.1 可选注入

src/deepseek_tui/app_server/
  thread_manager.py     # workflow.progress SSE
  engine_bridge.py      # 事件序列化

packages/workbench/src/renderer/src/
  agent/types.ts              # ChatBlock workflow + payload
  components/chat/WorkflowBlock.tsx
  agent/deepseek-runtime.ts   # onWorkflowProgress
  store/chat-store-runtime-helpers.ts  # 应用 snapshot

tests/workflow/
  test_validate.py
  test_template.py
  test_runtime_fake_runner.py
  test_runtime_integration.py

docs/
  DYNAMIC_WORKFLOW.md     # 本文档
```

---

## 9. 分阶段实施计划

### Phase 0 — SubAgent API 前置（P0，1–2 天）

**必须先于 Phase 3/4 完成**（§1.5.1）。

**任务**

- [ ] `AgentRunOutput` + `SpawnRequest.output_schema` + `SpawnRequest.auto_approve`（或等价 per-spawn runtime）
- [ ] `build_subagent_registry(extra_tools=...)`
- [ ] `StructuredOutputTool` + `run_subagent_loop` 早停
- [ ] `real_subagent_executor` / `SubAgentResult` 携带 `structured`
- [ ] 单测：schema agent 返回 dict；`strict` vs `trusted` auto_approve 行为

**验收**

- 不依赖 workflow 即可 spawn 带 schema 子 agent 并得到 `structured` 字段

---

### Phase 1 — 模型与校验（0.5–1 天）

**任务**

- [ ] `workflow/models.py`：Pydantic 模型覆盖 §4
- [ ] `workflow/validate.py`：结构 + id 唯一 + outputs 依赖
- [ ] `tests/workflow/test_validate.py`

**验收**

- 合法示例 JSON 通过；缺字段 / 重复 id / 非法 outputs 引用拒绝

---

### Phase 2 — 运行时 + Fake Runner（1–2 天）

**任务**

- [ ] `workflow/template.py`
- [ ] `workflow/runtime.py`：`agent` / `fanout` / `pipeline` / `synthesis`
- [ ] `WorkflowSnapshot` 更新回调
- [ ] `tests/workflow/test_runtime_fake_runner.py`（内存 FakeAgentRunner）

**验收**

- fanout 结果顺序与 items 一致；pipeline `{{previous}}` 传递正确；失败 step → null + continue

---

### Phase 3 — DeepSeek Runner + WorkflowTool（1–2 天）

**前置**：Phase 0 完成。

**任务**

- [ ] `workflow/agent_runner.py`：`spawn` + `wait` + policy runtime + `spawned_agent_ids`
- [ ] `tools/workflow_tool.py`（description 含 §7 指南）
- [ ] `tools/builder.py` 注册（`features.subagents`）
- [ ] Engine 注入 `engine_cancel_event` / `workflow_emit(tool_call_id, ...)`
- [ ] `tests/workflow/test_runtime_integration.py`

**验收**

- 主回合一次 `workflow` 调用跑 2 个子 agent；返回 `ToolResult` + `metadata.workflow`
- **不**触发 subagent handoff 续回合

---

### Phase 4 — workflow 结构化联调（0.5–1 天）

**任务**

- [ ] synthesis / agent step `output_schema` → `StepOutput.structured`
- [ ] workflow `result` = 最后 synthesis 的 structured 或 text（§1.5.3-G）
- [ ] `template.py` preview / `.full` 截断

**验收**

- 端到端 IR 示例（§12）返回 `{ ok, verdict, ... }` 对象，非 markdown JSON  fenced 文本

---

### Phase 5 — 取消 + 审批联调（0.5–1 天）

**任务**

- [ ] `wall_clock_seconds` + `spawned_agent_ids` teardown（§1.5.2-D）
- [ ] 三档 `approval_mode` 集成测试
- [ ] cancel 时 snapshot `skipped`

**验收**

- Esc 中止 workflow 后所有 running 子 agent `cancelled`；`trusted_workflow` 子 agent 不逐个弹审批

---

### Phase 6 — 进度 UI（2 天）

**任务**

- [ ] `WorkflowProgressEvent` + `thread_manager` SSE
- [ ] `engine_bridge` 序列化
- [ ] Workbench `WorkflowBlock` + store 接线
- [ ] Phase 5 过渡：`StatusEvent` 可先并行存在

**验收**

- 执行中 UI 树更新；结束后 tool 卡片展示完整 snapshot

---

### Phase 7 — Pi JS 适配器（可选）

**任务**

- [ ] `adapters/pi_js.py`：JS meta + body → IR（acorn 或 Node 子进程）
- [ ] `workflow_tool` 接受 `script` 字段

**验收**

- 示例 Pi 脚本与等价 IR 产生相同 step 数与结构

---

### Phase 8 — 延后

- workflow 持久化 / 恢复
- `fail_fast` 以外的高级重试
- worktree 隔离
- token_budget 接真实 usage

---

## 10. 测试策略

| 类型 | 内容 |
|------|------|
| 单元 | validate、template、runtime + fake runner |
| 集成 | WorkflowTool + mock SubAgentManager |
| 契约 | SSE `workflow.progress` payload 形状（可放 `tests/contract`） |
| 手工 | Workbench 跑 §4 示例 `repo_review`；Esc 取消；strict 模式拒绝写操作 |

---

## 11. 待拍板决策（实施前确认）

| # | 决策 | 建议默认 | v2 状态 |
|---|------|----------|---------|
| 1 | v1 工具入参是否**仅** `spec` 对象 | **是** | 已定 |
| 2 | 默认 `approval_mode` | `trusted_workflow` | 已定；接入 `SubAgentRuntime`（§1.5.1-B） |
| 3 | 默认 `on_error` | `continue` | 已定 |
| 4 | 进度 UI：Phase 5 先 StatusEvent | **是** | 已定 |
| 5 | 顶层 `result_schema` | **v1 不做** | 已定（§1.5.3-G） |
| 6 | Phase 0 是否阻塞 workflow | **是** | 已定（§1.5.1 P0） |

---

## 12. 参考示例（端到端）

主用户消息：

> 用 workflow 多视角审查本仓库的 engine、tools、workbench 集成风险，并给出最终建议。

模型应调用：

```json
{
  "name": "workflow",
  "arguments": {
    "spec": {
      "version": 1,
      "meta": {
        "name": "repo_review",
        "description": "multi-agent review"
      },
      "policy": {
        "approval_mode": "trusted_workflow",
        "on_error": "continue",
        "max_agents": 10,
        "concurrency": 4,
        "wall_clock_seconds": 600
      },
      "phases": [
        {
          "id": "inspect",
          "title": "Inspect repository",
          "steps": [
            {
              "id": "api_review",
              "type": "agent",
              "label": "api reviewer",
              "agent_type": "review",
              "prompt": "Review runtime API compatibility for workflow integration."
            },
            {
              "id": "parallel_checks",
              "type": "fanout",
              "concurrency": 3,
              "items": ["engine", "tools", "workbench"],
              "agent": {
                "label_template": "inspect {{item}}",
                "agent_type": "explore",
                "prompt_template": "Inspect {{item}} and report integration risks."
              }
            }
          ]
        },
        {
          "id": "synthesis",
          "title": "Synthesis",
          "steps": [
            {
              "id": "final",
              "type": "synthesis",
              "label": "final summary",
              "agent_type": "review",
              "prompt_template": "Synthesize:\n{{outputs.api_review}}\n{{outputs.parallel_checks}}\n\nReturn ok, verdict, findings.",
              "output_schema": {
                "type": "object",
                "properties": {
                  "ok": { "type": "boolean" },
                  "verdict": { "type": "string" },
                  "findings": { "type": "array", "items": { "type": "string" } }
                },
                "required": ["ok", "verdict"]
              }
            }
          ]
        }
      ]
    }
  }
}
```

---

## 13. 相关文档

- [WORKBENCH_ARCHITECTURE.md](./WORKBENCH_ARCHITECTURE.md) — SSE / ThreadManager
- [SANDBOX_ARCHITECTURE.md](./SANDBOX_ARCHITECTURE.md) — 子 agent 执行沙箱（OS 级，非 workflow IR）
- [HANDOVER.md](./HANDOVER.md) — 子 agent 集成决策
- 外部参考：`pi-dynamic-workflows` README — 语义对照，非依赖

---

*文档版本：v2 | 维护：实现 dynamic workflow 时以本文档为准，重大变更请更新修订记录。*
