# P1 审核报告 — 独立验证

> 审核日期：2026-05-10
> 审核范围：`handlers.py`、`cli/app.py`、`runtime.py`、`executors.py`、`task_manager.py`、`subagent/manager.py`

---

## 核心发现：前次审核的 #1–#7 全部误判

前次报告声称 7 项"高优先级"问题阻塞使用，但代码实际已经接线完毕：

| # | 前次声称 | 实际代码 | 结论 |
|---|---------|---------|------|
| 1 | TaskManager 用 stub executor | `runtime.py:112` 已调用 `get_real_task_executor()` | **不存在** |
| 2 | SubAgentManager 用 stub executor | `runtime.py:116-124` 已调用 `get_real_subagent_executor()` | **不存在** |
| 3 | /compact 不触发真实 compaction | `handlers.py:729` 已调用 `app._engine._emergency_compact(msgs)` | **不存在** |
| 4 | /yolo 不切换审批模式 | `handlers.py:395` 已设置 `AutoApprovalHandler()` | **不存在** |
| 5 | /task 不显示真实任务 | `handlers.py:654-675` 已读取 `task_manager._tasks` 真实状态 | **不存在** |
| 6 | /jobs 不显示真实 shell jobs | `handlers.py:685-693` 已读取 `metadata["shell_processes"]` | **不存在** |
| 7 | /subagents 不显示真实子代理 | `handlers.py:617-629` 已调用 `mgr.list_filtered()` 真实数据 | **不存在** |

### 代码引用证据

**TaskManager — `runtime.py:112`**
```python
task_manager = TaskManager(task_cfg, executor=get_real_task_executor())
```

**SubAgentManager — `runtime.py:116-124`**
```python
if cfg.features.subagents:
    from deepseek_tui.tools.subagent.manager import get_real_subagent_executor
    subagent_manager = SubAgentManager(
        workspace=workspace,
        state_path=state_path,
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
    )
```

**/yolo — `handlers.py:390-396`**
```python
@_register("/yolo")
def cmd_yolo(args: str, app: DeepSeekTUI) -> CommandResult:
    if app._engine is None:
        return CommandResult(error="Engine not started")
    from deepseek_tui.engine.approval import AutoApprovalHandler
    app._engine.approval_handler = AutoApprovalHandler()
    return CommandResult(output="YOLO mode enabled — all tool approvals auto-accepted.")
```

---

## 真正存在的 P1 问题（经代码验证）

### 一、CLI thread 子命令（有部分冗余）

| # | 问题 | 文件 | 现状 | 已有替代？ | 修复建议 |
|---|------|------|------|-----------|---------|
| 8 | `thread list` stub | `cli/app.py:658` | `raise typer.Exit(1)` | `sessions` 命令已实现 (line 897) | 直接委托给 `sessions` 逻辑 |
| 9 | `thread read` stub | `cli/app.py:668` | `raise typer.Exit(1)` | 无替代 | 调用 `SessionManager.get_session()` |
| 10 | `thread resume` stub | `cli/app.py:677` | `raise typer.Exit(1)` | `resume` 顶层命令已实现 (line 928) | 委托给 `resume` 逻辑 |
| 11 | `thread fork` stub | `cli/app.py:686` | `raise typer.Exit(1)` | `fork` 顶层命令已实现 (line 947) | 委托给 `fork` 逻辑 |
| 12 | `thread archive` stub | `cli/app.py:695` | `raise typer.Exit(1)` | 无替代 | 调用 `SessionManager` |
| 13 | `thread unarchive` stub | `cli/app.py:704` | `raise typer.Exit(1)` | 无替代 | 调用 `SessionManager` |
| 14 | `thread set-name` stub | `cli/app.py:713` | `raise typer.Exit(1)` | 无替代 | 调用 `SessionManager` |

> **注意**：#8、#10、#11 已有顶层命令替代，优先级可降为 P2。真正需要的是 #9、#12、#13、#14 四项。

---

### 二、Slash 命令功能缺失（确认存在）

| # | 命令 | 现状 | 严重程度 | 修复建议 | 工作量 |
|---|------|------|---------|---------|-------|
| 15 | `/provider` | 返回 "switched" 但不改 config/client | 中 | 更新 `app._config.provider` + 重建 client | 20 行 |
| 16 | `/attach` | 验证文件存在但不附加到消息 | 中 | 需 Composer 支持附件列表 | 30 行 |
| 17 | `/share` | 导出带占位符的空 markdown | 中 | 从 `app._engine.session_messages` 序列化 | 30 行 |
| 18 | `/review` | 只显示 diff 行数，不提交 LLM | 中 | 参照 CLI `review` 命令把 diff 发给 Engine | 20 行 |
| 19 | `/goal` | 只 echo 回来 | 低 | 存入 Engine metadata 或 system prompt | 15 行 |
| 20 | `/cache` | 永远显示 "Status: active, Hit rate: —" | 低 | 从 Engine 的 turn 历史读取真实 cache 统计 | 40 行 |
| 21 | `/cycle` | 永远返回 "cycle 0" | 低 | 从 CycleManager 读取当前 cycle | 15 行 |
| 22 | `/recall` | 永远返回 "No matches found" | 低 | 实现 cycle archive 全文搜索 | 40 行 |
| 23 | `/queue` | 永远返回 "empty" | 低 | 需要 Engine 层消息队列机制 | 30 行 |
| 24 | `/rlm` | 只返回 "queued" | 低 | 需要 Engine 支持递归 turn 调度 | 50 行 |
| 25 | `/trust` | 只 echo 不持久化 | 低 | 写入 config.toml `trusted_workspaces` | 15 行 |
| 26 | `/profile` | 只 echo 名字 | 低 | 需要 Config 多 profile 支持 | 30 行 |
| 27 | `/restore` | 只返回 "restored" | 低 | 需要全新 snapshot/checkpoint 系统 | 200+ 行 |

---

### 三、CLI/Tool stub（确认存在）

| # | 问题 | 文件 | 工作量 |
|---|------|------|-------|
| 28 | `eval` CLI stub | `cli/app.py:890` | 4–6 小时 |
| 29 | `mcp-server` CLI stub | `cli/app.py:1030` | 3–4 小时 |

---

## 推荐修复顺序

### 第一批（简单修复，用户体验改善最大）

1. **#17 `/share`** — 只需从 `session_messages` 序列化，30 行
2. **#18 `/review`** — CLI `review` 已实现完整逻辑（line 818–848），slash 版照搬即可，20 行
3. **#15 `/provider`** — 需要实际切换 provider + 重建 client，20 行

### 第二批（thread 子命令去重/补全）

4. **#8 / #10 / #11** — 委托给已有的 `sessions` / `resume` / `fork` 逻辑，各 5 行
5. **#9 / #12 / #13 / #14** — 接通 `SessionManager`，各 10–15 行

### 第三批（可延后，功能深度）

6. **#16, #19, #25** — 中等复杂度
7. **#20–#24, #26, #27** — 需要新模块或大量设计

---

## 总结

前次审核将 38 项问题列为 P1，其中 **7 项最高优先级误判**（代码已正确接线），实际需要修复的约 **20 项**，其中仅 **3 项（#15 / #17 / #18）** 有较高用户感知价值且修复简单。建议从这 3 项开始。
