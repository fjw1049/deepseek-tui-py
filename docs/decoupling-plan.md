# 解耦计划：自顶向下拆解 engine.py 和 runtime.py

## Context

`build_remain` 分支完成了"自底向上"的脚手架搭建（host 层 assembler/services/surfaces/lifecycle 等），但核心巨型文件 `engine.py`（2797行）和 `runtime.py`（1127行）未同步拆解，导致代码量不降反增。本计划执行"自顶向下"拆解，将已有 host 基础设施真正用起来。

---

## 原则

- 每个新模块对应一个**已识别的逻辑分组**，不创造新抽象
- 拆解后 Engine 类保留协调角色（thin orchestrator），各子系统通过组合注入
- 逐步可验证：每步完成后 `pytest` 全绿

---

## Phase 1: 拆解 engine.py（P0）

### Step 1.1 — 提取 `engine/tool_dispatch.py`

**移出方法：**
- `_execute_tool_calls` (1698–1879)
- `_execute_tools_parallel` (1881–2032)
- `_execute_single_tool` (2157–2180)
- `_execute_single_tool_impl` (2182–2307)
- `_execute_mcp_tool` (2309–2315)
- `_execute_parallel_tools` (2678–2727)
- `_emit_tool_failure` (1668–1688)
- `_build_tool_use_message` (1690–1696)

**新结构：** `ToolDispatcher` 类，持有 `registry`, `tool_context`, `mcp_manager`, `hook_executor`, `lifecycle_registry` 引用。Engine 持有 `self._dispatcher: ToolDispatcher`。

**预计行数：** ~500 行从 engine.py 移出

### Step 1.2 — 提取 `engine/approval.py`

**移出方法：**
- `_handle_approval_flow` (2317–2436)
- `_is_sandbox_denied_tool_result` (2439–2447)
- `_maybe_elevate_and_retry_tool` (2449–2546)

**新结构：** `ApprovalGate` 类，持有 `exec_policy`, `approval_handler`, `approval_cache`, `handle` 引用。

**预计行数：** ~230 行

### Step 1.3 — 提取 `engine/subagent_coord.py`

**移出方法：**
- `_enqueue_subagent_completion` (1340–1351)
- `_drain_subagent_completions` (1353–1363)
- `_mark_subagent_tool_result_consumed` (1365–1411)
- `_handle_subagent_turn_handoff` (1413–1464)

**新结构：** `SubAgentCoordinator` 类，持有 `_subagent_completions` queue, `_consumed_subagent_completions` set, `_activity_coordinator`。

**预计行数：** ~130 行

### Step 1.4 — 提取 `engine/checkpointing.py`

**移出方法：**
- `_save_crash_checkpoint` (2548–2573)
- `_auto_persist_session` (2588–2617)
- `_maybe_layered_context_checkpoint` (2575–2586)
- `_record_compaction_summary` (2621–2635)
- `_emergency_compact` (2637–2649)
- `_maybe_advance_cycle` (2651–2674)

**新结构：** `SessionCheckpointer` 类，持有 compaction_config, seam_manager, cycle_config 等状态。

**预计行数：** ~150 行

### Step 1.5 — 提取 `engine/evidence.py`

**移出方法：**
- `_memory_md_enabled` (585–592)
- `_messages_for_capture` (595–598)
- `_turn_had_tool_calls` (601–604)
- `_build_turn_evidence` (606–629)
- `_sync_tool_turn_evidence` (631–695)
- `_build_flush_evidence` (697–707)

**新结构：** `EvidenceBuilder` 类或模块级函数集。

**预计行数：** ~130 行

### Step 1.6 — 提取 `engine/snapshots.py`

**移出方法：**
- `_take_pre_tool_snapshot` (2038–2070)
- `undo_last_tool` (2072–2095)

**新结构：** `ToolSnapshotManager` 类。

**预计行数：** ~60 行

### Step 1.7 — 内联小文件

- `engine/subagent_intent.py` (26行) → 合并入 `engine/prompts.py`

---

**Phase 1 完成后 engine.py 预计：** 2797 - 500 - 230 - 130 - 150 - 130 - 60 ≈ **~1600 行**（主循环 + 初始化 + 上下文管理），可接受。

---

## Phase 2: 拆解 runtime.py（P1）

### Step 2.1 — 提取 `app_server/handlers/thread_handler.py`

**移出：** `handle_thread` 及 ThreadStore 逻辑 (~60行)

### Step 2.2 — 提取 `app_server/handlers/automation_handler.py`

**移出：** `list_automations`, `create_automation`, `get_automation`, `update_automation`, `delete_automation`, `run_automation`, `pause_automation`, `resume_automation`, `fire_trigger`, `list_automation_runs` (~140行)

### Step 2.3 — 提取 `app_server/handlers/mcp_handler.py`

**移出：** `list_mcp_servers`, `list_mcp_tools`, `mcp_startup`, `schedule_mcp_preload`, `mcp_preload_status` (~120行)

### Step 2.4 — 提取 `app_server/handlers/tool_handler.py`

**移出：** `handle_tool` (~120行)

**Phase 2 完成后 runtime.py 预计：** 1127 - 60 - 140 - 120 - 120 ≈ **~690 行**

---

## Phase 3: 拆解 legacy_commands.py（P1）

### Step 3.1 — 按命令组拆分

```
cli/commands/
├── __init__.py        (register_commands 汇总)
├── auth.py            (auth subgroup, ~100行)
├── config_cmd.py      (config subgroup, ~100行)
├── thread.py          (thread subgroup, ~120行)
├── mcp.py             (mcp subgroup, ~150行)
├── model.py           (model subgroup, ~40行)
├── serve.py           (serve/app-server, ~80行)
└── misc.py            (version/doctor/init/login/logout/exec 等, ~200行)
```

删除 `legacy_commands.py`。

---

## Phase 4: 清理琐碎文件（P2）

- `host/engine_lifecycle.py` (20行) → 合并入 `host/engine_attach.py`
- `host/toolpacks.py` (16行) → 合并入 `host/assembler.py`
- 确认已删除文件 (`capabilities/runtime_surfaces.py`, `tests/post_turn/test_scheduler.py`) 无残留引用

---

## 执行顺序

1. Phase 1 逐步执行 (Step 1.1→1.2→...→1.7)，每步后跑 pytest
2. Phase 2 全部执行后跑 pytest
3. Phase 3 一次性拆分后跑 pytest
4. Phase 4 收尾清理

## 验证

每个 step 完成后：
```bash
python -m pytest tests/ -x -q
```

全部完成后额外验证：
```bash
# 确认无循环导入
python -c "from deepseek_tui.engine.engine import Engine"
# 确认 CLI 正常
python -m deepseek_tui --help
# 确认 app-server 启动
python -m deepseek_tui app-server --help
```
