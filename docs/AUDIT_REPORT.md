# DeepSeek-TUI Python 移植代码审核报告（修订版）

**审核日期**: 2026-05-13
**项目**: deepseek-tui-py-main
**方法**: 阅读源码逐行核实；行号、方法名、Schema 字段都以仓库当前 HEAD 为准
**修订说明**: 本文件取代旧版审核报告。旧版混淆"设计 stub"与"实现 Bug"、把已存在但换名的方法记为"缺失"、把 OR 验证模式记为"Schema 漏洞"、并幻觉了一批不存在的类名（Cron*Tool / ScheduleWakeupTool / TodoDeleteTool）。本版只保留经代码核实的结论。

---

## 一、复核摘要

| 系统 | 真实问题数 | 旧版误报数 | 主要发现 |
|------|------------|------------|----------|
| 工具注册 | 3 项待决策 | 7 项幻觉类名 | 真正未注册的是 `Automation*Tool` 8 个 + `WebRunTool` + `FinanceTool`（其中 Finance 是 stub） |
| Task | 1 个真缺失 + 3 个待决策 | 3 个 Bug 误判（皆为有意 stub / 设计分工） | TaskGate / PrAttemptRecord / Preflight 都是按"记录器 + 外部执行"设计，不是 Bug |
| Subagent | 2 个真缺失 + 2 个可选优化 | 2 个反向错误 | `cleanup` 实名 `shutdown` 已存在；`assign` 实际有 `_require_agent` 校验；7 种 agent 类型已定义 |
| Todo | 1 个真缺失 | 3 个 Schema 误判 | Schema 用"两字段 OR"运行时校验，不是缺漏；唯一真问题是单 in-progress 约束未做 |
| Skill | 2 个真 P0 + 3 个 P1 + 多个 P2 | 2 个 P0 被夸大 | Gzip bomb 和网络白名单确为 P0；路径遍历 / symlink 风险被旧版高估 |

---

## 二、工具注册

### 2.1 真实情况

`builder.py` 的注册分支按 feature flag 组织。逐项核实：

- **Todo 工具**已注册：`TodoListTool / TodoWriteTool / TodoAddTool / TodoUpdateTool` 各注册 `canonical=True/False` 两次（builder.py:95-109）。旧版"TodoWrite/Add/Update 未注册"是错的。
- **`TodoDeleteTool` 不存在**于 todo_tools.py，旧版凭空虚构。
- **`CronCreateTool / CronDeleteTool / CronListTool / ScheduleWakeupTool` 不存在**于 automation_tools.py，旧版凭空虚构（疑似把 Claude Code 的工具名套了过来）。

### 2.2 实际未注册的工具

#### Automation Tools（automation_tools.py，8 个类，均未注册）

`AutomationCreateTool / AutomationListTool / AutomationReadTool / AutomationUpdateTool / AutomationPauseTool / AutomationResumeTool / AutomationDeleteTool / AutomationRunTool`

**状态**：实现存在，但 store 完全在 `ToolContext.metadata` 字典里（automation_tools.py:261-272），进程退出即丢；trigger / action 只是字符串，没有调度执行后端。属于半成品脚手架。

**待决策**：注册（需先决定持久化与触发执行如何接管）/ 删除 / 保留待用。

#### Web Tools

- `WebRunTool`（web_tools.py:93-149）：依赖 Playwright，未注册。可在 `cfg.features.web_search` 分支加注册，或新增 `features.web_run` 独立 flag。
- `FinanceTool`（web_tools.py:152-183）：**stub** —— 直接返回 `"(finance stub for {ticker} ...)"`，metadata `stub: True`。注册它等于把假数据暴露给 LLM，建议**先不注册**，要么实现真实数据源、要么删除。

---

## 三、Task 系统

### 3.1 行数与注册

- `task_tools.py` 671 行 ✅
- `task_manager.py` **888 行**（旧版误写 872）
- `cfg.features.tasks` 分支共注册 11 个工具（builder.py:146-160）：TaskCreate / TaskList / TaskRead / TaskCancel / TaskGateRun / TaskShellStart / TaskShellWait / PrAttemptRecord / PrAttemptList / PrAttemptRead / PrAttemptPreflight ✅

### 3.2 旧版误判（澄清）

| 旧版条目 | 真实情况 |
|----------|----------|
| Bug #1：TaskGateRunTool 不执行命令 | **不是 Bug，是设计分工。** 该工具是**记录器**：接收 exit_code / status / duration_ms 并 append 到 `task.gates`（task_tools.py:241-243）。命令执行由 `TaskShellStartTool / TaskShellWaitTool` 负责。 |
| Bug #2：PrAttemptRecordTool 不调用 git | **不是 Bug，是设计分工。** 该工具记录 `TaskAttemptRecord` 元数据（含 `patch_path` 字段，task_tools.py:451-471）。git 操作由 shell 工具完成。 |
| Bug #3：PrAttemptPreflightTool 不做 `git apply --check` | **是 stub，不是 Bug。** 工具自己的 description 写明 `(stub: returns a diagnostics summary)`（task_tools.py:565）。返回 base_ref / head_ref / existing_attempts 计数。要不要做成真预检查是产品决定，不是缺陷。 |

### 3.3 真实缺失 / 待决策

- **Schema v1（task_manager.py:23 `CURRENT_TASK_SCHEMA_VERSION = 1`）**：是否升 v2 取决于是否要与 Rust 端跨读。无明确兼容需求时不动。
- **`write_task_artifact()` 没有同名方法**：但 TaskShellWaitTool 直接 `task.artifacts.append(TaskArtifactRef(...))`（task_tools.py:376-382）。如果将来要从更多入口写 artifact，可以抽个方法；目前不是缺陷。
- **TaskExecutionEvent 流处理**：Python 用 `TaskTimelineEntry`（task_manager.py:47-51）维护事件序列。语义不同但功能在。是否需要更细粒度的执行事件由 UI 需求决定。
- **改进 ✅**：恢复 QUEUED 任务时检查 workspace 是否存在（task_manager.py:835-848）。

---

## 四、Subagent 系统

### 4.1 行数与注册

- `subagent_tools.py` **580 行**（旧版误写 541）
- `subagent/manager.py` **750 行**（旧版误写 728）
- `cfg.features.subagents` 分支注册 10 个工具（builder.py:162-175）：AgentSpawn / AgentResult / AgentCancel / AgentClose / AgentResume / AgentList / AgentSendInput / AgentAssign / AgentWait / DelegateToAgent ✅

### 4.2 旧版误判（澄清）

| 旧版条目 | 真实情况 |
|----------|----------|
| Bug #1：缺少 `cleanup()` | **方法名错。** 实际叫 `shutdown()`（manager.py:561-574），取消所有子任务并清理。功能完整。建议保留 `shutdown` 名（与 asyncio 习惯一致），不必改成 `cleanup`。 |
| Bug #2：`assign()` 不验证 agent_id | **反向错误。** `assign()`（manager.py:478-499）第 487 行调用 `self._require_agent(agent_id)`（定义在 577-581 行），不存在则抛错。验证存在。 |
| Bug #5：AgentAssignTool 缺验证 | **位置描述误导。** 工具层薄（subagent_tools.py:455-476），但调用 `manager.assign()` 时由 `_require_agent` 兜住。可考虑在工具层提前给出更友好的错误信息，但不是漏洞。 |
| 缺失 #1：6 种 agent 类型未定义 | **反向错误。** manager.py:44-51 定义了 **7 种**：GENERAL / EXPLORE / PLAN / REVIEW / IMPLEMENTER / VERIFIER / CUSTOM。 |

### 4.3 真实问题

| # | 问题 | 位置 | 严重度 | 说明 |
|---|------|------|--------|------|
| S-1 | `spawn()` 无深度上限 | manager.py:422-447 | P2 | `MAX_SPAWN_DEPTH` 常量定义在 35 行，但只在 SubAgentRuntime（714-724）里用；spawn 主路径未消费。子 agent 递归 spawn 时无保护。 |
| S-2 | `wait()` 轮询 50ms | manager.py:559 `await asyncio.sleep(min(0.05, remaining))` | P3 | 等待多个 agent 时 CPU 占用偏高。是否提到 250ms 看实测，不影响正确性。 |
| S-3 | Mailbox 无消息优先级 | mailbox.py:31-50 `MailboxMessage` 字段 | P3 | 当前 FIFO。是否要 priority 取决于消息量与紧急消息场景。 |

---

## 五、Todo 系统

### 5.1 现状

- 4 个工具类：`TodoWriteTool / TodoAddTool / TodoUpdateTool / TodoListTool`（无 TodoDeleteTool）。
- builder.py:95-109 每个类注册两次（canonical 真假各一）→ 8 个工具名称。✅
- 数据 store：`ToolContext.metadata['todos']`（内存）；通过 `_forward_to_task_manager`（todo_tools.py:167-191）转发到 TaskManager 持久化为 `TaskRecord.checklist`。

### 5.2 旧版误判（澄清）

旧版把 "input_schema 顶层未声明 `required: [...]`" 直接当作 Schema 漏洞，但本仓库的 Todo 工具用的是**两字段 OR + 运行时校验**模式（兼容 canonical / legacy 两组字段名）：

| 旧版条目 | 真实情况 |
|----------|----------|
| Bug #1：TodoWriteTool 应 `required: ["items"]` | execute 强制 "提供 todos（canonical）或 items（legacy）"。Schema 顶层若写死 `required: ["items"]` 反而会拒绝合法的 canonical 调用。 |
| Bug #2：TodoAddTool 应 `required: ["content"]` | 同上，`content / text` 二选一。 |
| Bug #3：TodoUpdateTool 应 `required: ["id", "status"]` | `item_id` 已在 required 中（todo_tools.py:417）；`status` 故意可选 —— 更新可能只改 content / activeForm 而不动状态。 |

### 5.3 真实问题

| # | 问题 | 位置 | 严重度 | 说明 |
|---|------|------|--------|------|
| T-1 | 单一 in-progress 约束未实现 | TodoAddTool.execute（todo_tools.py:345-373）、TodoUpdateTool.execute（423-454） | P1 | 业务规则要求同一时刻只有一个 in_progress 项。当前两个 execute 都不数量校验，可同时存在多个 in_progress。`_snapshot`（135-138）只读取 `in_progress_id` 不做约束。 |

---

## 六、Skill 系统

### 6.1 旧版定级修正

旧版把 4 项全部列 P0。逐项核实后只有 2 项是真 P0，另外 2 项被高估：

| # | 问题 | 实际严重度 | 备注 |
|---|------|------------|------|
| K-1 | 无下载/解压大小上限（Gzip bomb） | **真 P0** | install.py:159-160 `resp.read()` 一次性读全响应，无 MAX_SIZE，无解压量上限。可被恶意 tarball 直接 OOM。 |
| K-2 | 无网络白名单 + 仅 main 分支 | **真 P0** | install.py:154-156 硬编码 `github.com/{owner}/{repo}/archive/refs/heads/main.tar.gz`。无主机白名单；master-only 仓库会失败；任何 GitHub 账号 repo 都可装。 |
| K-3 | 路径遍历无显式 guard | **P1**（旧版 P0 高估） | install.py:174-177 未做 `resolve().relative_to(dest)`。Python 3.12+ tarfile filter 有隐式防护，但**不应依赖**。建议显式校验。 |
| K-4 | symlink 未显式处理 | **P2**（旧版 P0 高估） | 提取循环用 `member.isfile() / isdir()` 二分支（install.py:180+），symlink 落到 else 被**默默跳过**——不会被利用，但也不告警。建议显式拒绝并记录。 |

### 6.2 实现 Bug

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| K-5 | 顶层目录前缀检测：`prefix = members[0].name.split("/", 1)[0]`，第一成员是文件时返回整个文件名 | install.py:169 | P1 |
| K-6 | 相对路径计算：`rel = member.name[len(prefix) + 1:]`，prefix 为空时跳首字符 | install.py:174 | P2（GitHub tarball 实际很难触发，但逻辑不健壮） |
| K-7 | 只检查 `dest/SKILL.md`，不支持嵌套布局 | install.py:190 | P1 |

### 6.3 缺失功能（按需求决定是否要做）

| 功能 | 现状 | 建议 |
|------|------|------|
| 递归发现（vendor/skill 嵌套） | 未实现 | 看实际仓库布局是否需要 |
| 多搜索路径 | 2 处 | 与 Rust 8 处的差异是否影响使用是产品决定 |
| 多 URL 回退（main → master） | 未实现 | 与 K-2 一并修 |
| 直接 URL 安装 | 仅 `github:` 前缀 | 看是否需要 |
| 临时目录 + 原子 rename | 未实现 | 提升安装失败时的清理保证；与 K-1 一并修可减少半成品目录 |

---

## 七、修复路径建议（按优先级）

### P0（建议尽快）
1. **K-1 大小上限**：`urlopen` 改流式读取，limit `MAX_DOWNLOAD_BYTES`；解压前累加 `member.size`，超阈值抛错。
2. **K-2 网络白名单 + main/master 回退**：抽 `_resolve_archive_url(source)`，host 白名单（默认 `github.com`），先试 main 再试 master。

### P1（建议本周）
3. **K-3 路径遍历显式 guard**：每个 `target` 做 `target.resolve().relative_to(dest.resolve())`，越界抛错。
4. **K-5 顶层前缀检测**：用 `Path(members[0].name).parts[0]` 并显式判空。
5. **K-7 SKILL.md 多布局**：候选路径 `[dest/SKILL.md, dest/<name>/SKILL.md]` 任一存在即可。
6. **T-1 单 in-progress 约束**：`TodoAddTool / TodoUpdateTool` 在 execute 写回前数 `in_progress` 数量，>1 抛 `ToolError`。

### P2（按需）
7. **S-1 spawn 深度检查**：spawn 时 `if parent.depth >= MAX_SPAWN_DEPTH: raise`，把 depth 字段传下去。
8. **K-4 symlink 显式拒绝**：循环里 `if member.issym() or member.islnk(): warn + skip`。
9. **K-6 路径计算健壮化**：`rel = member.name[len(prefix):].lstrip("/")`。
10. **决策：8 个 Automation*Tool**——注册（需补持久化）/ 删除 / 留作 TODO 标记。
11. **决策：WebRunTool**——加 `features.web_run` flag 默认关；或删除。
12. **决策：FinanceTool**——删除或换真实数据源。**不要直接注册 stub**。

### P3（可选优化）
13. **S-2** wait 轮询节流到 250ms（实测决定）。
14. **S-3** Mailbox priority 字段（看消息量）。
15. **Task** PrAttemptPreflightTool 是否要从 stub 升级为真 `git apply --check`（产品决定）。

---

## 八、文件路径索引（已校正）

| 文件 | 实际行数 |
|------|----------|
| src/deepseek_tui/tools/task_tools.py | 671 |
| src/deepseek_tui/tools/task_manager.py | 888 |
| src/deepseek_tui/tools/subagent_tools.py | 580 |
| src/deepseek_tui/tools/subagent/manager.py | 750 |
| src/deepseek_tui/tools/todo_tools.py | （以仓库 HEAD 为准） |
| src/deepseek_tui/tools/automation_tools.py | （未注册，8 类） |
| src/deepseek_tui/tools/web_tools.py | （`WebRunTool` / `FinanceTool` 未注册） |
| src/deepseek_tui/tools/builder.py | 200（注册入口） |
| src/deepseek_tui/skills/install.py | （安全相关核心） |

---

## 九、与旧版的差异一览

| 旧版断言 | 修订结论 |
|----------|----------|
| 10 个工具未注册 | 实际未注册的是 8 个 `Automation*Tool` + `WebRunTool` + `FinanceTool`，且其中 `FinanceTool` 是 stub。Cron* / Schedule* / TodoDelete 几个类**不存在**。Todo 三个工具**已注册**。 |
| Task Bug #1/#2/#3 | 全部撤回，三者均为有意 stub 或设计分工。 |
| Subagent 缺 cleanup() | 撤回，方法名为 `shutdown()`。 |
| Subagent assign 不验证 | 撤回，有 `_require_agent` 校验。 |
| Subagent 缺 6 种 agent 类型 | 撤回，已定义 7 种。 |
| Todo Schema 三个 Bug | 全部撤回，OR + 运行时校验是合法设计。 |
| Skill 4 个 P0 安全漏洞 | 仅 K-1 / K-2 是真 P0；K-3 降 P1；K-4 降 P2。 |
| 评分 60-75% | 不再使用百分比评分（缺乏可验证基准）；改为按 P0/P1/P2/P3 列具体待办。 |
