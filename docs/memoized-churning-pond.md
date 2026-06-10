# 重构计划：Engine 解耦 + 插件化 + CLI 拆分 + Protocol 精简

## Context

项目是一个 Python TUI coding agent (`deepseek-tui-py`)。核心问题：`engine/engine.py` 3043 行，硬编码了 memory/evolution/LSP/goal/post_turn 等 10+ 独立关切；CLI 1426 行单文件；Protocol 层 80+ 类型过重。

用户明确要求：**memory 系统保留完整功能，通过热插拔实现解耦而非精简**。

---

## 重构目标

1. Engine 从"上帝类"变为"调度循环 + 插件总线"
2. Memory/Evolution/LSP/Goal 变为可热插拔的 EnginePlugin
3. CLI 按命令组拆分为子模块
4. Protocol 的 Params 包装层合并
5. Task/Todo 统一为双模式 TaskSystem
6. SSE 去重

---

## Phase 1：引入 EnginePlugin 协议（基础设施）

### 新增文件：`engine/plugin.py`

```python
class EnginePlugin(Protocol):
    """引擎生命周期插件协议"""
    name: str

    async def on_start(self, engine: "Engine") -> None: ...
    async def on_stop(self) -> None: ...
    async def before_turn(self, ctx: TurnContext) -> None: ...
    async def after_tool(self, tool_name: str, result: ToolResult, ctx: TurnContext) -> ToolResult: ...
    async def after_turn(self, evidence: TurnEvidence) -> None: ...
    async def on_flush(self, evidence: TurnEvidence) -> None: ...
    async def inject_system_prompt(self) -> str | None: ...
```

### 新增文件：`engine/plugin_bus.py`

```python
class PluginBus:
    """管理插件注册与分发"""
    def register(self, plugin: EnginePlugin) -> None: ...
    def unregister(self, name: str) -> None: ...  # 热插拔
    async def broadcast_before_turn(self, ctx: TurnContext) -> None: ...
    async def broadcast_after_tool(self, ...) -> ToolResult: ...
    async def broadcast_after_turn(self, evidence: TurnEvidence) -> None: ...
    async def collect_system_prompt_fragments(self) -> list[str]: ...
```

### 修改文件：`engine/engine.py`

- 删除对 `lsp`、`post_turn`、`evolution`、`goal`、`memory` 的直接 import
- `Engine.__init__` 增加 `plugin_bus: PluginBus` 参数
- `Engine.create()` 中根据 config flags 注册对应插件
- `_run_conversation()` 中的 hook 调用点改为 `await self.plugin_bus.broadcast_xxx()`
- 预计从 3043 行降至 ~1200 行

### 关键调用点迁移

| 原调用位置 (engine.py) | 原逻辑 | 迁移目标 |
|------------------------|--------|----------|
| Line 1202-1220 | `coordinator.recall_for_turn()` | `MemoryPlugin.before_turn()` |
| Line 1298-1299 | `_evolution_pipeline.volatile_lines()` | `EvolutionPlugin.inject_system_prompt()` |
| Line 1450 | `post_turn.after_turn(evidence)` | `PluginBus.broadcast_after_turn()` |
| Line 1661 | `post_turn.flush_before_loss()` | `PluginBus.broadcast_on_flush()` |
| Line 1686 | `_flush_pending_lsp_diagnostics()` | `LspPlugin.before_turn()` |
| Line 1958, 2145 | `_run_post_edit_lsp_hook()` | `LspPlugin.after_tool()` |
| Line 1282 | `goal_controller.on_turn_start()` | `GoalPlugin.before_turn()` |
| Line 1409-1436 | `goal_controller.on_turn_complete()` | `GoalPlugin.after_turn()` |
| Line 1942, 2130 | `post_turn.on_main_tool_called()` | `PluginBus.broadcast_after_tool()` |

---

## Phase 2：实现各领域插件

### 2a. `engine/plugins/memory_plugin.py`

- 包装现有 `memory/coordinator.py` 的完整功能
- `before_turn()`: 执行 `coordinator.recall_for_turn()`，注入召回结果到 context
- `after_turn()`: 执行 `coordinator.capture_after_turn()`
- `on_flush()`: 执行 `coordinator.flush_session()`
- `inject_system_prompt()`: 返回 memory.md 内容（如 enabled）
- **memory/ 目录的 16 个文件全部保留不动**

### 2b. `engine/plugins/evolution_plugin.py`

- 包装现有 `evolution/pipeline.py`
- `inject_system_prompt()`: 返回 `volatile_lines()`
- `after_turn()`: 调用 `pipeline.after_turn(evidence)`
- `after_tool()`: 调用 `pipeline.on_main_tool_called(tool_name)`
- `on_flush()`: 调用 `pipeline.flush_before_loss()`
- **evolution/ 目录全部保留不动**

### 2c. `engine/plugins/lsp_plugin.py`

- 包装现有 `lsp/` 模块
- `before_turn()`: flush pending diagnostics 到 messages
- `after_tool()`: 对编辑类工具运行 LSP 诊断，追加 DiagnosticBlock 到 result

### 2d. `engine/plugins/goal_plugin.py`

- 包装现有 `goal/controller.py`
- `before_turn()`: `goal_controller.on_turn_start()`
- `after_turn()`: `goal_controller.on_turn_complete()`, 若需要 follow-up 则向 handle 发送 `GoalFollowUpOp`
- `inject_system_prompt()`: 返回 goal status context

### 2e. `engine/plugins/session_activity_plugin.py`

- 包装现有 `engine/session_activity.py`
- `after_turn()`: 追踪活动子 agent/task 数量

---

## Phase 3：删除 `post_turn/` 编排层

当前 `post_turn/orchestrator.py` 的作用被 `PluginBus` 完全替代：

- `PostTurnOrchestrator.after_turn()` → `PluginBus.broadcast_after_turn()`
- `PostTurnOrchestrator.flush_before_loss()` → `PluginBus.broadcast_on_flush()`
- `PostTurnOrchestrator.on_main_tool_called()` → `PluginBus.broadcast_after_tool()`

**删除**：
- `post_turn/orchestrator.py`
- `post_turn/pipeline.py` (Protocol 定义迁移到 `engine/plugin.py`)
- `post_turn/scheduler.py`
- `post_turn/gates.py`
- `post_turn/evidence.py` → 迁移到 `engine/plugin.py` 或 `engine/events.py`
- `post_turn/pipelines/memory_pipeline.py` → 逻辑并入 `MemoryPlugin`
- `post_turn/subagent_runner.py` → 逻辑并入 `EvolutionPlugin` 或删除

---

## Phase 4：统一 Task/Todo

### 现状分析

- **todo_tools.py (537行)**：内存中的 checklist，8 个工具名（4 canonical + 4 legacy alias）
- **task_tools.py (1027行)**：持久后台 task，11 个工具
- **两者有桥接**：todo 在 Task context 内会 forward metadata 到 TaskManager

### 计划

保留两层但统一入口：

```
tools/tasks/
├── __init__.py          # 统一导出
├── checklist.py         # 原 todo_tools.py（重命名，删除 legacy 别名）
├── durable.py           # 原 task_tools.py
└── manager.py           # 原 task_manager.py
```

**变更**：
1. 删除 `todo_*` legacy 别名（只保留 `checklist_*` canonical 名）
2. 删除 `DeprecatingAliasTool` 相关代码（`builder.py` lines 198, 205, 207）
3. `builder.py` 中 Todo 注册从 8 项减到 4 项
4. Goal tools 从 builder 中移除（由 GoalPlugin 按需注入）

---

## Phase 5：拆分 CLI

### 目标结构

```
cli/
├── __init__.py
├── app.py               # Typer app + main_callback + _launch_tui + _run_one_shot (~130行)
├── auth.py              # auth_status/set/get/clear/list/migrate + login/logout (lines 328-509)
├── config_cmd.py        # config_get/set/unset/list/path/show + helpers (lines 515-640)
├── model_cmd.py         # model_list/model_resolve (lines 644-705)
├── thread_cmd.py        # thread_list/read/resume/fork/archive/unarchive/set_name (lines 712-863)
├── mcp_cmd.py           # mcp callback + 9 subcommands (lines 1126-1335)
├── serve_cmd.py         # serve/app-server/mcp-server (lines 265-330, 1360-1385)
└── misc.py              # doctor/features/init/exec/review/apply/sessions/resume/fork/setup/sandbox/completions/metrics/update
```

### 注册方式

```python
# cli/app.py
from .auth import auth_app
from .thread_cmd import thread_app
from .mcp_cmd import mcp_app

app.add_typer(auth_app, name="auth", help="Manage API keys.")
app.add_typer(thread_app, name="thread", help="Thread management.")
app.add_typer(mcp_app, name="mcp", help="MCP server management.")

# 独立命令用 lazy import
@app.command()
def doctor(...): from .misc import _doctor_impl; _doctor_impl(...)
```

---

## Phase 6：精简 Protocol

### 6a. 合并 Params + Request

**前**：
```python
class ThreadForkParams(BaseModel): thread_id, at_turn, ...
class ThreadForkRequest(BaseModel): kind="fork", params: ThreadForkParams
```

**后**（方案 B — Discriminated Union）：
```python
class ThreadForkRequest(BaseModel):
    kind: Literal["fork"] = "fork"
    thread_id: str
    at_turn: int | None = None
    ...

ThreadRequest = Annotated[
    ThreadCreateRequest | ThreadStartRequest | ThreadResumeRequest | ...,
    Field(discriminator="kind")
]
```

删除所有 `*Params` 类：`ThreadStartParams`, `ThreadResumeParams`, `ThreadForkParams`, `ThreadListParams`, `ThreadReadParams`, `ThreadSetNameParams` — 6 个类 → 0。字段内联到 Request 中。

### 6b. 合并 SSE

- 删除 `app_server/runtime_api/sse.py` 中的 `sse_frame()` 函数
- 改为从 `app_server/sse.py` import `format_sse`
- 1 处 import 修改

---

## 执行顺序与依赖

```
Phase 1 (EnginePlugin 协议 + PluginBus)     ← 基础设施，必须先做
    │
    ├── Phase 2a-2e (各插件实现)             ← 可并行
    │
    └── Phase 3 (删除 post_turn/)            ← 依赖 Phase 2 完成
    
Phase 4 (Task/Todo 统一)                    ← 独立，可任意时间
Phase 5 (CLI 拆分)                          ← 独立，可任意时间
Phase 6 (Protocol 精简)                     ← 独立，可任意时间
```

---

## 验证计划

每个 Phase 完成后：

1. **类型检查**：`python -m mypy src/deepseek_tui/ --ignore-missing-imports`
2. **单元测试**：`pytest tests/ -x -q`
3. **TUI 启动**：`python -m deepseek_tui` 确认 TUI 正常渲染
4. **One-shot**：`python -m deepseek_tui -p "hello"` 确认 engine 循环正常
5. **插件热插拔验证**（Phase 2 后）：在 config 中关闭 memory/evolution/lsp，确认 engine 正常运行无报错
6. **回归**：对比重构前后相同 prompt 的 tool 调用序列是否一致

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| PluginBus 引入异步竞态 | 插件按注册顺序串行调用（与当前 PostTurnOrchestrator 行为一致） |
| Goal 的 GoalFollowUpOp 需要向 handle 写入 | GoalPlugin 持有 handle 引用，after_turn 中可直接 send_op |
| CLI 拆分后 import 循环 | 全部用 lazy import（函数内 from .xxx import） |
| Protocol 合并破坏 JSON-RPC 兼容 | 确保 Pydantic model_dump() 输出字节相同（用 snapshot test 验证） |

---

## 预期成果

| 指标 | 当前 | 重构后 |
|------|------|--------|
| engine.py 行数 | 3043 | ~1200 |
| cli/app.py 行数 | 1426 | ~130 |
| Engine 直接 import 的模块数 | 20+ | 5 (handle, plugin_bus, turn_loop, events, tool_registry) |
| protocol/ 导出类数 | 80+ | ~55 |
| 注册的工具数 | 50+ (含别名) | ~42 (删除 legacy alias + goal tools 移入插件) |
| post_turn/ 文件数 | 7 | 0 (删除) |
| memory/ 完整度 | 100% | 100% (不变，仅包装为插件) |
