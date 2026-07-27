# 对标 Claude Code 的工具面优化方案

> 日期：2026-07-27
> 状态：**已实现**（2026-07-27，A1–A5 + Phase B 全部落地，见文末「实现记录」）
> 前置：`docs/TOOL_CONSOLIDATION_KIMI_CLAUDE_2026-07-27.md`（调研结论）、`docs/TOOL_OPTIMIZATION_PLAN.md`（Phase 0–2 已完成）
> 本文档在审核结论基础上，对当前实现做了四路代码级核实（task 系统 / automation+workflow / subagent+registry+approval / Claude+Kimi 参考仓库源码），给出可落地的分阶段方案。

---

## 0. 核实结论（与审核文档的差异）

审核文档的方向性论断全部成立，源码核实补充/修正三点：

1. **Claude 的 TodoV2 门控工具是 4 个**（`TaskCreate/TaskGet/TaskList/TaskUpdate`，`claude-code-main/src/tools.ts:247-249`），审核漏写 `TaskGet`。常驻只有 `TaskOutput`/`TaskStop`。
2. **Kimi 代码实际导出 27 个工具模块**（`kimi-code-main/packages/agent-core/src/tools/builtin/index.ts`），"22"是 `docs/zh/reference/tools.md` 的文档口径（多出 goal×4 + select-tools）。
3. **本项目审批双层已合并**：`policy/approval.py` 不存在，`tools/approval.py` 是唯一审批层（审核文档中"双层"的描述已过时）。

### 关键认知：问题的真实形状

默认注册 39 个，但 **defer 机制已经把每步常驻压到 19 个**（`engine/tools.py:47-76` `_ALWAYS_ACTIVE_TOOLS`；git、github×4、mcp×4、task×5、workflow×2、current_time、note、run_tests、project_map 共 20 个默认 deferred，靠 tool_search 激活）。

**19 ≤ Claude 常驻 25**。所以本次优化的收益不是"模型看到的太多"，而是：

- **注册表卫生**：39 个注册项的维护成本、tool_search 噪声、schema 总token。
- **行为迁移**：模型在 Claude/Kimi 上训出的工具使用先验（后台三件套、Cron 三名、Agent resume 参数）能直接迁移。
- **删冗余实现**：`task_shell_start` 就是 `exec_shell(background)` 的转发（`tools/task/tools.py:514-517`），这类纯包装留着是双倍维护。

---

## 1. 目标工具面

### 1.1 映射总表（现状 39 → 目标 21，开 automations 24）

| 家族 | 现状 | 目标 | 手段 |
|---|---|---|---|
| 文件 | `read_file` `write_file` `edit_file` `grep_files` `file_search` `list_dir` | 前 5 个不动；**删 `list_dir`** | `file_search`（Glob）+ `exec_shell ls` 覆盖；Claude/Kimi 均无此物 |
| Shell | `exec_shell` `exec_shell_interact` | **`exec_shell` 单一** | interact 折为 `exec_shell(process_id, input)` 分支；`background` 参数别名 `run_in_background` 对齐 |
| Web | `web_search` `fetch_url` | 不动 | 两边一致 |
| 待办 | `checklist` | 不动 | = Claude `TodoWrite` / Kimi `TodoList` |
| 子代理 | `agent`(6 action) + `agent_resume` | **`agent` 单工具**，resume 折为参数 | Kimi 形态 `Agent(resume=id)`；list/result/cancel 三个 action 移给后台三件套（见 §2） |
| 后台/任务 | `task_create/cancel/resume/list/read/gate_run/shell_start/shell_wait`（8） | **`task_create` `task_list` `task_output` `task_stop`（4）** | 见 §2，这是本次的核心刀 |
| 定时 | `automation_*`（8，feature 门控） | **`cron_create` `cron_list` `cron_delete`（3）** | 见 §3 |
| MCP 桥 | 4 个 | **`list_mcp_resources` `read_mcp_resource`（2）** | 删 templates/get_prompt（均 deferred，模型本来就要 search 才见到） |
| Git/GitHub | `git` + `github_*`×4 | **默认不注册** | `exec_shell` + `gh` 覆盖；实现类保留，挂 compat profile 备用 |
| 杂项 | `project_map` `current_time` `run_tests` | **默认不注册** | Glob/Bash 覆盖；`current_time` 改为环境注入 |
| 计划/记忆 | `note` `update_plan` | 保留，均 deferred | 语义不同（Phase 1 已否决合并），不占常驻面即可 |
| 工作流 | `workflow` + `workflow_list` | **两个都保留**，均 deferred | 合并代价 > 收益，见 §4 |
| 交互 | `request_user_input` `load_skill` | 不动 | = Claude `AskUserQuestion` / `Skill` |

### 1.2 目标常驻面（每步实际下发，约 17 + tool_search×2）

```
read_file write_file edit_file grep_files file_search
exec_shell                      # background/run_in_background + PTY + process_id/input
web_search fetch_url
checklist
agent                           # spawn / wait / send_input + resume 参数
task_create task_list task_output task_stop
request_user_input load_skill
(+ tool_search_tool_regex / tool_search_tool_bm25)
```

deferred：`list_mcp_resources` `read_mcp_resources`→`read_mcp_resource`、`workflow` `workflow_list`、`note` `update_plan`、`cron_*`×3（门控）。

---

## 2. 核心刀：后台三件套统一（task 8 → 4）

### 2.1 已核实的重叠事实

- `task_shell_start` = `ExecShellTool().execute({background: True, pty: True})` 的转发 + 记 timeline（`tools/task/tools.py:514-517`）；`task_shell_wait` = `wait_background_process` + 记 artifact。**能力 100% 重叠，可直接删**。
- `agent(action=result/cancel, process_id=…)` 已经在兼任后台 shell 的 output/stop（`tools/subagent/tools.py:382-421`），和 `task_output/task_stop` 是同一语义。
- `exec_shell` 已有 `background=true` 后台能力（`tools/shell.py:66-84`），但进程句柄是**纯内存**（重启即丢）。

### 2.2 真正不能丢的资产（沉到实现层，不随工具删除）

1. **用户级持久化 + 跨进程重启重排队**：`~/.deepseek/tasks/`，重启时 RUNNING→QUEUED（`tools/task/store.py:154-233`）。
2. **durable transcript resume**：checkpoint→hydrate（`tools/durable_transcript.py`，subagent 共用同一套）。
3. **FIFO 队列 + worker 限流**（`tools/task/manager.py:543-599`）。
4. **gate 记录 / checklist 快照 / timeline / artifacts** 审计轨迹（TASKS 面板数据源）。

### 2.3 目标四工具语义

| 工具 | 语义 | 审批 | 对标 |
|---|---|---|---|
| `task_create` | durable 后台任务（fire-and-forget，用户级队列）；**resume 折为参数** `task_create(resume=<task_id>)` | REQUIRED | Claude `TaskCreate`（门控位） |
| `task_list` | 统一列举：durable 任务 + 运行中子代理 + 后台 shell 进程 | 只读 | `TaskList` |
| `task_output` | 统一读取：任务记录/artifact、子代理结果（`block`/`timeout_ms`）、后台进程输出 | 只读 | `TaskOutput` |
| `task_stop` | 统一停止：取消 durable 任务（含 workflow-detach 的 stop-intent，`tools/task/tools.py:218-231`）、取消子代理、杀后台进程 | REQUIRED | `TaskStop` |

被吸收的：`task_read`→`task_output`；`task_cancel`→`task_stop`；`task_resume`→`task_create(resume=)`；`task_shell_start/wait`→删除（exec_shell + task_output 覆盖）；`task_gate_run`→从工具面删除（gate 分类启发式 `tools/task/helpers.py:75-97` 下沉为 task 执行完成时的内部记录，或直接放弃——**决策点 D3**）。

`agent` 工具同步收敛：`list/result/cancel` 三个 action 删除（由 task 三件套接管），保留 `spawn`（+`run_in_background`）/`wait`/`send_input` + 新增 `resume` 参数。执行层对旧 action 保留别名转发 + debug 日志一个版本周期。

### 2.4 为什么不是方案 α（把 durable 藏进 `agent(run_in_background)`）

α 会让 `agent` 同时承载"父回合附属子代理"和"用户级 fire-and-forget 队列任务"两种生命周期，语义混淆；且 Claude 自己也有独立的 `TaskCreate` 位。保留 `task_create` 单工具（家族从 8 压到 4）是语义清晰与表面对齐的交点。

---

## 3. automation 8 → cron 3

已核实：`automation_pause/resume` 是 `update(status=…)` 的两行薄封装（`tools/automation.py:1204-1212`）；Workbench/REST 层直接调 `AutomationManager`（`server/runtime.py:665-832`），**工具面收敛不影响 Web UI 完整 CRUD**；handler 直接测试覆盖很薄（共 17 个测试），重写成本低。

| 现状 | 去向 |
|---|---|
| `automation_create` | `cron_create`（保留 rrule/cwds/delivery schema；加 `run_now: bool` 吸收 `automation_run`） |
| `automation_list` | `cron_list`；带 `automation_id` 时返回详情 + run 历史（吸收 `automation_read`） |
| `automation_delete` | `cron_delete` |
| `automation_update` | 删除（delete+recreate；注意 delete 会清 run 历史，文档里写明） |
| `automation_pause/resume` | 删除（模型层能力让位给 Workbench UI；若后续证明需要，再加 `cron_update` deferred） |
| `automation_run` | `cron_create(run_now=true)` |

命名用 `cron_*` 与现有 `TOOL_PROFILE_CRON`/`CRON_PROMPT_PREFIX` 词汇一致（`engine/prompts.py:516-520`）。调度器、`AutomationManager`、REST 全部不动。

---

## 4. 明确不做（与审核一致 + 一处修正）

- **不做** mega-`action` 工具（`task(action=…)`、`automation(action=…)`）——Claude/Kimi 均无此形态。
- **不动**文件/Web/checklist/request_user_input/load_skill 的拆分。
- **不做** snake_case → PascalCase 改名（Read/Bash）：零功能收益，全链路 churn，且背离 Rust  parity  heritage。
- **不合并 `workflow_list` 进 `workflow`**（修正审核建议）：`workflow` 是 REQUIRED+EXECUTES_CODE，`workflow_list` 是 AUTO 只读且 plan 模式注册（`registry.py:790-792`）；合并需给已很重的 anyOf 五分支 schema 再加分支 + action 级审批门控，−1 不抵三重代价。两个都 deferred 即可。
- **保留 `wait`/`send_input`**：`send_input` 对应 Claude 的 `SendMessage`（交互式 steering），`wait` 零注册成本，删了反而丢能力。

---

## 5. 分阶段落地

### Phase A — 低风险改名/删除（每项独立可发布）

| # | 项 | 主要触点 | 数量效果 |
|---|---|---|---|
| A1 | `agent_resume` → `agent(resume=)` | `tools/subagent/tools.py:761-800`；审批指纹 `tool:agent_resume`→`agent:resume:<id>`（`tools/approval.py:193-210` 加分支）；plan 模式不暴露 resume | −1 |
| A2 | `exec_shell_interact` → `exec_shell(process_id, input)` | `tools/shell.py:474-539`；schema 加互斥分支 | −1 |
| A3 | MCP 4→2 | `tools/mcp.py`；同步 `engine/dispatch.py:128-145` `_MCP_PARALLEL_SAFE`、`tools/approval.py:767-768` 前缀分类、`tui/tool_classify.py:65-68`、`mcp/execute.py:15-21` 别名 | −2 |
| A4 | 默认不注册 `git`/`github_*`/`project_map`/`list_dir`/`current_time` | `registry.py:641-831` 各删一行注册；实现类保留；`current_time` 确认环境注入已覆盖后删（`tools/time_tools.py:65,149` 的描述引用同步清） | −7 |
| A5 | `automation_*` 8 → `cron_*` 3 | `tools/automation.py` handler 层；硬引用点：`engine/prompts.py:523-535`、`tui/tool_classify.py:75-100`、`packages/workbench/.../app-settings.ts:385-439`、`tests/test_tool_profiles_and_time.py:33-39`、`tests/test_focus_tool_whitelist.py:44` | −5（门控） |

### Phase B — 后台三件套统一（根因刀，单独一个 PR 系列）

1. `task_output`/`task_stop` 实现统一读取/停止三路（durable task / subagent / bg process），复用 `wait_background_process` 与 `SubAgentManager` 现有入口。
2. `task_list` 聚合三源快照。
3. `task_create` 加 `resume` 参数；`task_resume` 执行层别名。
4. 删 `task_shell_start/wait/read/cancel/resume/gate_run` 注册，执行层别名转发 + debug 日志一个周期。
5. `agent` 删 `list/result/cancel` action，schema 收窄；`approval_requirement_for_input`/`is_read_only_for_input` 按新 action 集重算（`tools/subagent/tools.py:724-739` 注释里写明的连坐坑）。
6. 改硬编码 hint：`tools/shell.py:302-312` 超时引导文案、task 嵌套守卫文案。
7. `_ALWAYS_ACTIVE_TOOLS` 与 defer 白名单同步（`engine/tools.py:47-76`）。

### Phase C — 可选（独立评估，不在本期）

- `EnterPlanMode`/`ExitPlanMode`：Claude 有、我们没有（agent 无法自行进出 plan 模式）。属于新 UX 能力而非收敛，单独立项。
- `workflow_list` 折入 `workflow`：仅当 Phase B 的 action 级审批门控范式跑顺后再考虑。

---

## 6. 护栏（每个 Phase 必做）

1. **快照测试**：同步 `tests/test_tool_catalog_snapshot.py` 的 `_AGENT_TOOLS`/`_PLAN_TOOLS` 与无副作用断言。
2. **审批指纹**：凡改名/合并，逐路径核对 `build_approval_key`（`tools/approval.py:193-238`）——action 级、命令位置参数、`file:`/`tool:` 前缀，防止"批准一次只读"泄漏成"放行写操作"或反向重复弹窗。
3. **plan 模式**：只读新工具（`task_list`/`task_output`/`cron_list`）可进 plan；`task_stop` 不进（副作用，拍板：排除）。
4. **执行层别名**：旧工具名在执行层转发 + debug 日志，schema 只暴露新名（沿用 Phase 1 先例）。
5. **prompts/渲染**：`prompts/base.md`、modes、`packages/workbench` 渲染层、`tui/tool_classify.py` 图标表。

---

## 7. 决策点（落地前需拍板）

| # | 问题 | 建议 |
|---|---|---|
| D1 | `git`/`github_*`/`project_map` 是彻底删还是留 compat profile？ | 留实现类 + 默认不注册（一行开关可回）；`list_dir`/`current_time` 直接删 |
| D2 | `cron_*` 不要 `cron_update`（pause/resume/update 让位 UI）？ | 先不要；模型层需求被证实后加 deferred `cron_update` |
| D3 | `task_gate_run` 的失败分类启发式保留吗？ | 保留在实现层：task 执行完成时可自动跑 gate 并归档；不暴露工具 |
| D4 | `exec_shell` 参数改名 `background`→`run_in_background`？ | 双别名并存（schema 只露新名），与 subagent 的 `run_in_background` 对齐 |
| D5 | plan 模式放行 `task_stop` 吗？ | 不放行（副作用）；只放行 `task_list`/`task_output` |

---

## 8. 验收标准（实现对账 ✅ 2026-07-27）

- [x] agent 默认注册 **22**（开 automations **25**）；plan **15**；每步常驻 ≤ **19** —— 比原目标多 1，原因是 `workflow_list` 按 §4 论证保留（justified deviation）
- [x] 无独立 `agent_resume`/`exec_shell_interact`/`task_shell_*`/`task_read`/`task_cancel`/`task_resume`/`task_gate_run`（`workflow_list` 有意保留）
- [x] 后台面仅 `task_create`/`task_list`/`task_output`/`task_stop` 四名；automations 仅 `cron_*` 三名
- [x] MCP 桥 = 2；`git`/`github_*`/`run_tests`/`project_map`/`list_dir`/`current_time` 不在默认注册表
- [x] `test_tool_catalog_snapshot.py` 绿（golden 22/15）；审批指纹/别名/plan 泄漏断言更新并通过；全量 **1145 passed / 21 failed（21 个全为存量，与基线集合一致）**，零新增失败
- [x] durable 三项能力未动实现层（TaskManager 队列/持久化、durable transcript 原样），Phase B 只改工具面与路由

---

## 9. 一句话

常驻面其实已经够小（19 ≤ Claude 25）；这一刀的价值在**注册表卫生与行为可迁移**：后台统一成 `task_create/list/output/stop` 四件、Cron 三个独立名、`agent(resume=)`、单 `exec_shell`、删掉纯包装（`task_shell_*`）和 Bash 可替代项（`git`/`github_*` 等），把 durable/queue/audit 资产沉到实现层而不是删掉。

---

## 10. 实现记录（2026-07-27）

| 阶段 | 内容 | 注册表变化 |
|---|---|---|
| A1 | `agent_resume` → `agent(resume=)`；plan 模式 `allow_resume=False`；指纹 `agent:resume:<id>`；旧名经 `normalize_legacy_tool_call` 转发 | −1 |
| A2 | `exec_shell_interact` → `exec_shell(process_id, input, close_stdin)`；审批级别天然继承（两者同为 EXECUTES_CODE 默认 REQUIRED） | −1 |
| A3 | MCP 桥删 `list_mcp_resource_templates`/`mcp_get_prompt`（McpManager 底层方法保留，`plugins/runtime.py` 有调用方） | −2 |
| A4 | `git`/`github_*`/`project_map`/`run_tests` 默认不注册（实现类保留，一行可回）；`list_dir`/`current_time` 彻底删除（时间注入确认：`engine/prompts.py` 的 `render_environment_block()` 每轮注入 `today: YYYY-MM-DD`，精确时间用 `exec_shell date`） | −9 |
| A5 | `automation_*` 8 → `cron_create`（+`run_now`）/`cron_list`（带 id 出详情+历史）/`cron_delete`；update/pause/resume 让位 Workbench UI；plan 仍整族排除 | 门控 −5 |
| Phase B | `task_*` 8 → `task_create`（+`resume`）/`task_list`（三源聚合）/`task_output`（task/agent/process 三分支）/`task_stop`（保留 workflow-detach stop-intent）；`agent` 删 list/result/cancel action（直接调用得 steering error）；指纹 `task_stop:{kind}:{id}`，旧名 `task_cancel` 共享；`_mark_subagent_tool_result_consumed` 接 `task_output/task_stop(agent_id)` 分支 | −4 |

**决策点落地**：D1 留实现类（`list_dir`/`current_time` 除外，已删）；D2 无 `cron_update`；D3 gate 启发式与 `TaskGateRecord` 留存实现层、未挂钩子、旧名不转发；D4 未做（`background` 参数保留原名，`run_in_background` 仅 subagent 侧；evaluated as 纯改名收益低，未动）；D5 plan 只放行 `task_list`/`task_output`。

**新增测试**：`tests/test_task_unified_tools.py`（14）、`tests/test_cron_tools.py`（8）、`tests/test_agent_merge_approval.py`（8）、`tests/test_legacy_tool_name_forwarding.py`（A1–B 共 19+ 转发用例）、interact 分支用例 5 个。

**遗留事项**（后续独立评估，不阻塞）：
1. gate 失败分类启发式挂到 task 执行完成钩子（D3 的完整形态）。
2. `_AUTOMATION_COMPOSER_NATIVE` profile 硬过滤无 shell，但 composer 提示词建议 `exec_shell date`——要么把 `exec_shell` 加进 profile，要么改文案。
3. `task_list` 的 agent 快照固定 `include_archived=False`，旧 `agent(action=list, include_archived=true)` 语义无等价物（转发丢弃，dispatch 有注释）。
4. 旧工具名在 tui/tool_classify、workbench 渲染层的分类条目按惯例保留（历史 transcript 重放需要）；兼容期结束后可单独清理。
5. `subagent/loop.py` 子代理内部工具分发未接旧名归一化（与 Phase 1 行为一致）。
6. 基线 21 个存量测试失败（live API 401、parity mcp_hooks、seatbelt、usage_ledger 日期敏感等）不在本次范围。
