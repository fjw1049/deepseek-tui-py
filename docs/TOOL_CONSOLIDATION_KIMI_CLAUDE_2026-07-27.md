# 工具面再收敛 — Kimi / Claude 对照调研与落地建议

> 日期：2026-07-27  
> 状态：**待实现**（调研完成，供下班后落地）  
> 前置：`docs/TOOL_OPTIMIZATION_PLAN.md`（Phase 0–3 已完成，默认 agent 注册表 39）  
> 相关：`docs/TOOL_ALIGNMENT_SESSION_2026-07-24.md`、`tests/test_tool_catalog_snapshot.py`

## 调研来源

| 对照对象 | 本地路径 | 主要依据 |
|---|---|---|
| Kimi Code | `/Users/user/Desktop/learn/kimi-code-main` | `docs/zh/reference/tools.md`、`packages/agent-core/src/tools/builtin/` |
| Claude Code | `/Users/user/Desktop/learn/claude-code-main` | `src/tools.ts`（`getAllBaseTools`）、`src/constants/tools.ts`（`CORE_TOOLS`）、`packages/builtin-tools/` |
| （无效） | `/Users/user/Desktop/learn/claw-code-main 2` | **空目录**，未采用 |

---

## 1. 现状快照（DeepSeek）

- Agent 模式默认内置：**39**（`gh` 未就绪时少 4 个 `github_*`）
- 开 `features.automations`：**+8** → 约 47
- Plan 模式：**24**（只读偏置）
- 权威清单：`tests/test_tool_catalog_snapshot.py` 的 `_AGENT_TOOLS` / `_PLAN_TOOLS`

「多」有两层：注册表数量 vs 每步常驻（defer 已挡一部分）。再砍应优先砍 **CRUD / 编排家族冗余**，不要动文件读写原语。

---

## 2. 三方对照（有出处）

| | **Kimi** | **Claude Code** | **DeepSeek（当前）** |
|---|---|---|---|
| 公开/默认内置量级 | **约 22**（文档清单） | 常驻核心约 **20–30** | **39**（+ automations 8） |
| 文件工具 | Read/Write/Edit/Grep/Glob **分开** | 同样分开 | 已对齐 |
| Shell | **仅 `Bash`**，后台用 `run_in_background` | **仅 `Bash`**，同样有 `run_in_background` | `exec_shell` + `exec_shell_interact` |
| 子代理 | **一个 `Agent`**，resume 是参数 | **`Agent` + `SendMessage` 续聊** | `agent` action 枚举 + 独立 `agent_resume` |
| 后台任务 | **TaskList / TaskOutput / TaskStop（3）**，管 Bash+Agent+AskUser | **TaskOutput / TaskStop**（+ TodoV2 时另有 TaskCreate/Get/List/Update） | **task_\* 8 个**（durable 后台 agent，更重） |
| 定时 | **CronCreate/List/Delete（3，不合并）** | **同样 3 个，不合并** | **automation_\* 8 个** |
| 网络 | WebSearch + FetchURL **两个** | WebSearch + WebFetch **两个** | 同结构 |
| MCP 桥 | 文档未单列（走 MCP 工具面） | **ListMcpResources + ReadMcpResource（2）** | **4 个** |
| Git/GitHub/测试/目录图 | **无一等公民** → Bash | 同左 | `git` + 最多 4×`github_*` + `run_tests` + `project_map` + `list_dir` |

### 两边共同哲学（重要）

**不是**「CRUD 合成一个 `action=` 巨型工具」，而是：

1. **核心原语少而稳**：文件 5–6 + Bash 1 + Web 2 + Todo 1 + Ask/Skill  
2. **编排用少量专用工具**：Agent（±续聊）+ 后台 2–3 + Cron 3  
3. **能 Bash 就不挂专用工具**（git / gh / 测试）  
4. **审批粒度用「不同工具名」表达**（CronCreate 要批、CronList 自动），而不是全塞进一个 `action=`

> 反模式：把 `task_*` / `automation_*` / `github_*` 收成 mega-`action` 工具——**与 Kimi、Claude 实际做法相反**。

---

## 3. 该收什么 / 不该动什么

### 3.1 高置信（两边都这么干）— 建议做

#### A. Shell 收成 1 个

- Kimi/Claude：只有 `Bash` + `run_in_background`
- 动作：去掉或并入 `exec_shell_interact`；交互用 PTY/模式参数，默认路径对齐单工具

#### B. 后台任务对齐成 3 个

- Kimi：`TaskList` / `TaskOutput` / `TaskStop` 统一管 Bash、Agent、AskUser 后台
- Claude：`TaskOutput` / `TaskStop`（完成靠通知，少轮询）
- 动作：收敛 `task_shell_*`、`task_gate_run`，以及 `agent` 里的 result/cancel/list/wait 到这条线，而不是再堆 8 个 durable API

#### C. Agent resume 不要独立工具

- Kimi：`Agent(resume=id, prompt=...)`
- Claude：续聊用 `SendMessage`，不是 `agent_resume`
- 动作：至少把 `agent_resume` 并回 `agent`（优先 Kimi 模型）；若要续聊语义，再考虑 Claude 的 SendMessage 形态

#### D. Automations → Cron 三件套

- 两边都是 Create / List / Delete，**刻意不合并**
- 动作：`automation_*` 8 → **3**；**不要**做成 `automation(action=…)` 全家桶

#### E. MCP 桥 4→2

- Claude 只有 List + Read
- 动作：去掉/并入 `list_mcp_resource_templates`、`mcp_get_prompt`（prompt 可走 skill / MCP 动态工具）

#### F. 删掉或降级「Bash 能替代」的一等工具

两边都没有：`git`、`github_*`、`run_tests`、`project_map`、`list_dir`（用 Glob/Bash）、`current_time`（环境注入）。

- 动作：默认不注册，或强 defer；需要时靠 shell / MCP / skill

### 3.2 保持分开（两边都没合并）— 不要动

| 工具 | 证据 |
|---|---|
| Read / Write / Edit / Grep / Glob（及对应 `read_file` 等） | Kimi 文档 + Claude `CORE_TOOLS` |
| WebSearch + Fetch | 两边都是两个 |
| Todo / Checklist 单独一个 | Kimi `TodoList`、Claude `TodoWrite`——已经是 1 个 |
| Cron 三个独立名 | 两边一致 |
| AskUser / Skill | 两边独立 |

**不要**为了数字好看把文件或 Web 合成 `fs` / `web`。

### 3.3 你们多出来、两边几乎没有 — 优先砍体感

| DeepSeek | 建议（对标） |
|---|---|
| `note` + `update_plan` | Claude/Kimi 用 Enter/ExitPlanMode + 计划文件；记忆可 defer，别占常驻面 |
| `workflow` + `workflow_list` | Claude 是**单个** `Workflow`（feature 门控） |
| `agent` 的 list/wait/result/cancel | 与 Task\* 重叠 → 收到后台三件套 |
| durable `task_create` 全家 | 若保留「可重启长任务」，对外尽量映射成 `Agent(background)` + `TaskOutput`，而不是 8 个名字 |

---

## 4. 目标形状（对标后）

常驻大致：

```
read_file write_file edit_file grep_files file_search
exec_shell                          # 单一 shell；后台用参数
web_search fetch_url
checklist
agent                               # resume 为参数，无 agent_resume
request_user_input load_skill
task_list task_output task_stop     # 命名可对齐 Kimi；语义=后台三件套
cron_create cron_list cron_delete   # 若开 automations；由 automation_* 收敛
enter_plan_mode exit_plan_mode      # 可选：对齐 plan UX（替代/收窄 update_plan）
list_mcp_resources read_mcp_resource
(+ tool_search 发现其余 deferred 工具)
```

目标量级：**约 18–22 个常驻/默认注册**，贴近 Kimi 文档面；其余全部 defer 或删除。

---

## 5. 落地优先级（推荐排期）

按「数量影响 × 与两边一致性」排序：

| 顺序 | 项 | 预期效果 | 备注 |
|---|---|---|---|
| **1** | 后台三件套对齐（`task_*` + `agent` 控制面 → List/Output/Stop） | 最大 | 根因；注意审批指纹与 plan 模式 |
| **2** | `automation_*` 8 → Cron 3 | −5 | **拆三个工具名**，不 action 合并 |
| **3** | `agent_resume` 并入 `agent(resume=…)` | −1 | 对齐 Kimi |
| **4** | Shell 单一化；砍独立 `exec_shell_interact` | −1 | PTY 作参数/模式 |
| **5** | MCP 桥 4→2 | −2 | 对齐 Claude |
| **6** | 降级 `git` / `github_*` / `run_tests` / `project_map` / `list_dir` / `current_time` | −6~10 | 不注册或强 defer；`list_dir` 可用 Glob/Bash |
| — | `workflow` + `workflow_list` → 单 `workflow` | −1 | 对齐 Claude 单工具 |
| — | `note` / `update_plan` 收窄或 defer | 体感 | 勿与 checklist 合并 |

### 明确不做

- ~~`task(action=…)` 八合一~~
- ~~`automation(action=…)` 八合一~~
- ~~`github(action=…)` 四合一~~
- ~~`web` / `fs` 超级工具~~
- ~~合并 `note` + `update_plan` + `checklist`~~（Phase 1 已否决，语义不同）

---

## 6. 实现时注意点

1. **护栏测试**：任何增删工具必须同步 `tests/test_tool_catalog_snapshot.py` 的 `_AGENT_TOOLS` / `_PLAN_TOOLS`。  
2. **审批**：合并/改名时逐路径核对主引擎、子代理、指纹缓存、`approval_requirement_for_input` / `is_read_only_for_input`（见 `TOOL_OPTIMIZATION_PLAN.md` 复审教训）。  
3. **执行层兼容**：旧工具名可在执行层别名一段时间 + debug 日志；schema 只暴露新名（与 Phase 1 一致）。  
4. **Workbench / prompts**：改名后跟进 `packages/workbench` 渲染与 `prompts/base.md`、modes。  
5. **Plan 模式**：继续排除副作用工具；后台三件套里只读（list/output）可保留，stop 是否放行需显式拍板。  
6. **语义澄清**：DeepSeek 的 `task_create`（durable 可重启 agent）≠ Kimi/Claude 的「后台 Bash/Agent 句柄」。落地时先决定：  
   - **方案 α（推荐对齐）**：对外只暴露后台三件套 + `Agent(run_in_background)`；durable 能力沉到实现层  
   - **方案 β（保留能力）**：保留 create/resume 等，但命名与数量仍压到接近 Claude TodoV2（Create/Get/List/Update）+ Output/Stop，而不是 8 个杂名

---

## 7. 验收标准（建议）

- [ ] Agent 默认注册表 ≤ **22**（不含 MCP 动态工具；automations 开时 ≤ **25**）  
- [ ] 无独立 `agent_resume`、`exec_shell_interact`、`workflow_list`  
- [ ] Automations 仅 `cron_create` / `cron_list` / `cron_delete`（或等价三名）  
- [ ] MCP 桥 ≤ 2  
- [ ] `git` / `github_*` / `run_tests` / `project_map` / `current_time` 默认不在常驻面  
- [ ] `test_tool_catalog_snapshot.py` 绿；相关审批/别名测试更新并通过  
- [ ] Plan 模式无新增副作用泄漏

---

## 8. 一句话

对标 Kimi/Claude：**少原语、后台三件套、Cron 三个独立名、Agent resume 做参数、Bash 替代 git/测试专用工具**；不要用 mega-`action` 工具刷数字。下一刀优先做**后台三件套对齐**。
