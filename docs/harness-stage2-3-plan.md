# Harness 阶段二、三实施方案

给接手实现的 session。依据：《harness 笔记 01》《笔记 02》《我对这套 harness 的优化理念和方案》（都在 `~/Desktop/未命名文件夹/`）和阶段一审计 `evals/reports/2026-10-31-stage1-audit.md`。先读审计，再读本文。

每条结论都标了来源：**[实测]** 来自数据或运行，**[读码]** 来自读代码，**[待验证]** 是动手前要先确认的假设。

## 进度

**阶段二和阶段三的主体已完成并验证，改动在工作区，未提交。** 下文是设计依据；与实际代码不一致的地方以代码为准。

### 结果

A：`baseline-stage1-final`。B：`stage2-combined`。下表用 `regrade --reuse-judge` 把两轮换成同一份检查口径，评审结果沿用，不花模型调用。

| 指标 | A | B | 目标 |
|---|---|---|---|
| 打分通过率 | 54.5%（12/22） | 63.6%（14/22） | 不降 ✓ |
| 如实率 | 59.1% | 68.2% | 上升 ✓ |
| 虚报率 | 18.2% | 13.6% | 下降 ✓ |
| 答复丢失 | 0 | 0 | 0 ✓ |
| harness 消耗轮次 | 0.364 | 0.136 | 下降 ✓ |
| 缓存命中 | 约 97% | 约 97% | 不大降 ✓ |

B 之后的改动只做了小范围验证，**没有全量复跑**：

- `office-check`：`documents`、`presentation`、`spreadsheet`、`document_merge`、`goal_execution` 5/5 通过。当时评测用了一次性 HOME，后来发现这会让 Chrome 卡住，已改为只隐藏用户级 skill 目录。这 5 个用例不靠产品浏览器，但环境和最终代码不完全相同。
- `prompt-slim-check`：9 个用例 6 个通过；`documents` 通过但慢（1917 秒）；`logs` 失败是检查写死 `*.md`，已修；`web_app` 失败是 HOME 问题；`long_context` 见下。
- `long_context`：完整提示词 5/5，第一版精简 2/4，恢复 `Verification` 段后 4/4。
- `final-web-app`：最终代码下 519 秒完成，浏览器 45 次调用失败 3 次，新评审满分。

**注意**：没有 A/A，每个用例基本只跑一次，B 当天接口偏慢。配对 14 个用例的轮次 +19%、输入 token +26%，增减都有，未见系统性原因，“轮次下降”的目标未达成。提示词瘦身后每轮输入约少 6k token，这部分未进入上表。

### 各项状态

| 项 | 状态 |
|---|---|
| 2.5 旁白 | 完成，代码已删，`[ui.process_narration]` 旧配置仍可加载。`ensure_opening` 开场白保留 |
| 2.2、2.4、2.1（含 Goal）、P0 截断、无人值守 | 完成。另修：导航超时不再记为未决操作，否则无人值守时页面被锁死 |
| 2.3 | 完成。按创建时间判断所有权；第二步只报告不恢复。184 条回放：139 条放行，最多 45 条要审批 |
| `continue_nudged` 删除的风险 | 出现 1 次（36 个回合中 1 个）。恢复了提示词里“重读最后一段”的规则，它在 8 周前被替换，未加门控 |
| 3.1b | 只做“同一视图的旧观测折叠”，UI 会话减约 36%，缓存未受影响 |
| 3.1a | 未做。最大请求约 45 万字符，缺专门的长上下文用例 |
| 3.2、3.3、工具契约、项目指令 | 完成。3.3 没做排队，现状已有等待和交接 |
| 办公依赖（第 7 节 #6） | 完成 |
| 3.4 | `base.md` 33.9KB → 18.7KB，目标 ≤12KB 未达到；`browser.md` 未动，要靠 UI 用例验证，预算不够。`LONG_SESSION_DRIFT` 已删 |
| 评审增强 | `claims_without_run`、`page_loads`、运行记录进评审材料、`regrade --reuse-judge` 完成 |

### 已知未解决

- `public_research`、`software_research` 仍是 0.5 分：关键事实没写来源。提示词加一句来源要求无效，已撤回。
- `resume_edit` 0.5 分：资料缺失处留了【待填写】，这个要求本身可讨论。
- 评审材料和 `expense_tool` 等检查都改过，**新运行不能直接和 A、B 比**。要比较就先对基线跑一次不带 `--reuse-judge` 的 `regrade`，只花评审调用。
- 另一次 `test_product_session` 偶发失败原因未明。已加端口竞争的重试，未确认是否为同一原因。

### 回退

`.claude/worktrees/stage2-patches/` 有合回前的 `main-before-merge.tgz`、`main-diff-before-merge.patch`、逐项 patch、`base.before-3.4.md` 和回放脚本。合回之后的改动没有单独的 patch。

### 测试基线

全量 3885 通过、0 失败。live 测试在 key 无效时跳过，用有效 key 时 16 个全过。

## 1. 开工前

### 1.1 当前状态

- **阶段一改动全部在工作区，未提交**，分支 `build_1024`，基于 `4c25f913`。不要 reset 或 stash。
- **正式基线**：`evals/artifacts/baseline-stage1-final`，通过 12/22，dirty `4701c727`，grader `56eef6d8`，dataset `23428cc6`。不需要 regrade。这是 A/B 的 A。
- **不能当对照的运行**：`baseline-2026-10-31-flash`（4096 上限，通过 11/22，保留作修复前证据）、`baseline-2026-10-31-flash-capfix`（熔断误伤）、`baseline-stage1-flash`（电脑睡眠）。
- **花费**：校准和试跑 ¥0.08，第一轮 ¥4.59，capfix 加重新打分 ¥2.22，睡眠中断那轮 ¥1.46，正式基线 ¥5.20。余额 ¥10.93，**一次完整运行约 ¥5**。
- **长任务要防睡眠**：用 `caffeinate -ims` 包住 `evals run`，并且不要合盖。

### 1.2 怎么跑评测

模型路由：`deepseek` / `deepseek-flash`（DeepSeek-V4.1-Flash，与 soak 同一模型）。key 由用户提供，**不要写进仓库或 `~/.deepseek/config.toml`**。写到 session scratchpad 的临时配置（权限 600），用完删除：

```toml
provider = "deepseek"
approval_policy = "auto"
sandbox_mode = "danger-full-access"

[providers.deepseek]
protocol = "openai"
base_url = "https://api.deepseek.com"
api_key = "<用户提供>"
model = "deepseek-flash"
```

```bash
export DEEPSEEK_CONFIG_PATH=<临时配置> PYTHONPATH=src:.
caffeinate -ims .venv/bin/python -m evals run --mode live --suite daily_tasks \
  --provider deepseek --model deepseek-flash \
  --concurrency 4 --timeout 1200 --max-live-requests 50 --max-input-tokens 150000000 \
  --label <名字> --output evals/artifacts/<名字>
.venv/bin/python -m evals compare-runs evals/artifacts/<A> evals/artifacts/<B>
```

本机开着 7890 代理时 DeepSeek 可达；Volcengine 需要 `NO_PROXY` 绕过。查余额：`curl -H "Authorization: Bearer $KEY" https://api.deepseek.com/user/balance`。`deepseek-flash` 不在 `client/pricing.py` 里，所以 `known_cost_usd` 恒为 0，**0 不代表免费**，成本以余额差为准。

### 1.3 工作规则

1. **一次只做一项**，改动、测试、评测都完成再开下一项。每项一个提交（用户要求时才提交）。
2. **每项必须有对照**：改之前的运行是 A，改之后是 B，用 `compare-runs` 看。`source_changed_during_run` 为真的运行作废。**评测运行期间不要改 `src`、`evals`**：产品进程按需懒加载源码，改了会污染结果。
3. **先量噪声**：条件允许时跑一次 A/A。余额不够时用 `capfix` 与正式基线的 8 个可比用例作粗略参考（1 个翻转）。差异小于噪声时，不能算改进或退步。
4. **回滚条件**：通过率下降且超过噪声，或答复丢失不为 0，或如实率下降，就回退该项并记录原因。
5. **干预日志是主要证据**：`session.interventions.*`、`session.harness_rounds`。删一个机制前，先看它触发了多少次、那些试验的判定如何。
6. 笔记第三节的判定规则同样约束新代码：判断归属、只有不可逆才阻断、每个拒绝配可走的路、只追加不替换、每个机制有日志和下线条件。

## 2. 顺序与理由

**先重新理解 soak**：10-29 的 soak 用 `deepseek-v4-1-flash`，这个名字匹配不上 `max_output_tokens_for_model` 的 `"v4-flash"`，每次请求的输出上限是 4096。soak 里每轮平均输出的最大值恰好是 4096.0，59 个回合（42 个会话）平均每轮超过 3000。**[实测]** 这个 bug 已在 `config/providers.py` 修复。笔记里“办公和界面任务卡住、超时”的部分现象可能来自它，不完全是架构问题。笔记中依赖这些现象的结论要用修复后的基线重看。

| 顺序 | 项 | 理由 |
|---|---|---|
| 0 | P0 截断静默失败、A/A 噪声 | 前者让“完成”不可信；后者不知道就无法判断任何改动 |
| 1 | 2.5 旁白 | 已有配置开关，零风险，先练一遍流程 |
| 2 | 无人值守模式 | 基线 `software_research` 直接卡死，soak 7 个会话同样，提前到这里 |
| 3 | 2.2 工具列表不变 | 改动小，且是 2.1 的前置 |
| 4 | 2.4 浏览器协议 | 独立，失败率 20% 是现成指标 |
| 5 | 3.2 环境能力清单 | 提前：基线中办公任务手写 OOXML，单回合超过 15 分钟 |
| 6 | 3.1a 改窗口实验 | 只改配置，不写代码，回答“有效上下文”的问题 |
| 7 | 2.1 完成契约 | 收益最大、范围最广，放在有噪声数据之后 |
| 8 | 2.3 安全策略 | 风险最高，需要用户先定默认值（第 7 节） |
| 9 | 3.1b 上下文治理 | 依赖 6 的结论 |
| 10 | 3.3、3.4 | 3.4 放最后，有评测才敢删提示词 |

## 3. 阶段二

### P0 截断静默失败（笔记没有，基线发现）

- **现象 [实测]**：第一轮基线 `web_app`、`ui_reorder_list`、`csv_cli`、`document_merge` 回合状态都是 completed，工作区却没有产物。模型每轮写长文件时被输出上限截断，工具调用残缺被丢弃，它反复重试，最后一句“现在写页面本体。”就结束了，状态仍是 completed。
- **根因 [读码]**：`TurnResult.truncated` 只有 `tools/subagent/loop.py:1014` 在读，主循环 `engine/orchestrator/core.py` 完全没看。残缺的工具调用不执行，模型也不知道发生了什么。
- **做法**：`result.truncated` 且没有完整工具调用时，这不是模型的结束，记一条 `gate` 干预，追加一条提醒说明“输出在上限处被截断，上一个工具调用没有执行，请拆小再写”，最多 2 次。仍然截断就结束，`task_outcome` 记 `partial`，答复里写明。子代理循环已有逻辑，参照它。
- **测试**：脚本化 `StreamDone(truncated=True)`；断言不会以 completed 无声结束。
- **附带**：`turn.py:62` 的“模型连接不稳定，正在重试…”文案在流式重放时也会出现，排查时容易误导，建议 log 里区分原因。

### 2.5 旁白只给 UI

- **已具备**：写入侧已隔离，transcript 记录的是请求边界的消息，旁白不可能进模型历史。**[读码]**
- **做法**：`config/models.py` 的 `ProcessNarrationConfig.enabled` 默认值改 `False`，跑 A/B。没有退步后删除 narration 调用和 `compute_narration_display` 等，再评估 `ensure_opening` 的空话模板（`manager.py` 回合桥接内）。
- **衔接笔记 02 增补**：删旁白后界面少了过程文字，给 `exec_shell` 加面向用户的 `description` 参数，由主模型顺带写出。
- **验收**：通过率不降，每回合少 1 类模型调用。`usage.sources` 里能看到 narration 的调用归零。

### 2.2 回合内工具列表不变

- **删除**：`tools/task_delivery.py` 的 `focused`、`extra_tools`、`FOCUS_TOOLS`、`RequestTaskToolsTool`；`surfaces.py` 的 `Surface.focus`、`is_focus_call`；`tools/registry.py:729-732` 注册；`tooling.py:163` 的 exclusive 集合、`:791-800` 的 focus 判断；`tools/browser.py:39-40` 描述；`prompts/browser.md:233-241`。
- **不要动**：`_focus_tool_whitelist`（skill/MCP/插件的显式聚焦）是用户主动触发的另一个机制，保留。
- **注意**：`delivery.tools()` 还负责 `finalizing` 收窄，这部分等 2.1 删。`tests/test_tool_catalog_snapshot.py` 是快照测试，改工具集要同步更新。
- **验收**：`session.interventions.tool_list` 里 `focus` 归零；工具不在目录的失败（soak 约 10 次）归零；自写 Playwright（soak 7 个会话）下降。

### 2.4 降低浏览器协议成本

- **现状 [读码]**：`browser/service.py:1707-1720` 已有 `require_observation` 分支，并能把当前观测填回 action，`missing_observation_id` 拒绝在 `:1530`。`observation_id` 可选的改动面比笔记想的小。
- **做法**：省略时默认用最新观测，观测已过期时仍返回明确错误；放开工作区内 `file://` 和 `about:blank`（先查 URL 策略所在位置，本次未定位 **[待验证]**）；`observe` 默认精简；`browser.md` 只留操作安全规则。
- **基准**：`evals/browser_bench/bench.py` 有 offline 和 live，能同时比成功率和观测体积，用它和 `daily_tasks` 的 ui 用例一起看。
- **验收**：`browser_use` 失败率从 20.6% 下降，平均结果体积从 4.6KB 下降。

### 2.1 统一完成契约

**目标**：模型永远用普通正文结束；harness 只汇总确定知道的事实，附在答复后，不进模型历史。

**新模块** `engine/completion.py`（目标约 80 行）：

```python
@dataclass
class TurnFacts:
    failures: dict[tuple[str, str], str]   # (工具, 目标) -> 错误；同 key 成功后清除
    edited_after_verify: list[str]         # 最后一次验证命令之后才改的文件
    pending: list[str]                     # 浏览器、CUA 的未决状态
    limitations...                         # 不解析模型文字，这项不做
```

- “未再验证的文件”只在**本回合跑过验证、之后又改了文件**时才报。文档类任务从没跑过命令，报它只是噪声。**[设计决定]**
- 未决状态来源 **[读码]**：`browser.state(thread)` 的 `unresolved`、`dialog`、`file_chooser`；`run.pending_action`、`run.pending_input`、`run.assistance`；`cua_session.unresolved`、`outside_change`、`reset_reason`。这些判断现在写在 `FinishTaskTool.execute` 里，搬过去。
- 存在危险未决状态时，用一个新的 `ReminderSpec` 提醒**最多一次**，然后照常结束。
- 没有事实可报时不加尾注。
- `task_outcome` 由 harness 推导：`partial`（有未决或未解决失败）、`completed_with_evidence`（验证之后没有再改动）、`completed_unverified`。

**尾注怎么交付**：不能直接拼进 `assistant_message`，否则模型下一轮会读到自己“说过”的尾注。放进 `TurnCompleteEvent` 的新字段，由 `manager.py` 回合收尾时写到最终答复 item（`metadata` 标记），前端照常显示。`evals/session_metrics.turn_answers` 要去掉尾注，否则评审会把它当成模型的声明。

**删除清单 [读码]**：

| 位置 | 内容 |
|---|---|
| `tools/task_delivery.py` | 整个文件 |
| `engine/orchestrator/core.py` | `incomplete_delivery`、循环条件里的 `delivery.outcome`/`stop_reminded`（`while` 条件）、`continue_nudged`/`stop_reminded` 分支、`FINALIZATION_*` 超时和 token 限制、`delivery.tools()` 调用、回合末 `task_delivery_end`；共 57 处引用 |
| `engine/orchestrator/tooling.py` | `:163-177`、`:438-450` evidence 记账、`:529-530`、`:568-571`、`:789-800`、`:1319-1339` |
| `tools/subagent/loop.py` | **第二份实现**，容易漏：`:26`、`:277-281`、`:313-319`、`:609-629`、`:754-757`、`:868-878`、`:892-941`、`:1162-1167`、`:1291-1312` |
| `cua/tools.py` | `:318-341`、`:399-410`。`cua_verification_target` 和未决状态移到 `CuaSession`，`cua_observe` 还要用 |
| 工具结果 | `Evidence reference:` 文本和 `evidence_ref`、`task_evidence`（`browser/context.py:323`、`tools/browser_skill.py:160`）。实际改动面比本表大，子代理和 CUA 的处理以实现 patch 为准 |
| `engine/ui_progress.py:63,71`、`tools/browser.py:39-40`、`prompts/browser.md`、`prompts/computer_use.md:11` | 提到 finish_task 的文字 |
| `tools/registry.py:729,859-864` | 注册和子代理排除 |

**Goal**：`goal/service.py:validate_completion` 保留到 `open_items` 检查（预算、状态、未完成清单都是确定事实），删 evidence 和 audit 校验；`UpdateGoal` 参数收缩为 `status`、`reason`、`requirements`；`work_revision`、`observe_workspace`、`tooling.py` 的 workspace digest 一并删除。`record_tool_result` **不能整个删**：它的计数器驱动续跑和停滞判定，实现改成精简的 `record_work`。`goal/persist.py` 必须能继续读带 `completion_evidence`、`completion_audit` 的旧状态。`work_pending` 检查保留。

**checklist 门控**：`_CHECKLIST_GATE_MAX_FIRES` 改为 1。

**B1 残留一起修 [实测]**：`model_request_failed` 和 `round_trip_limit` 两条路径现在仍用固定文案替换。改成有模型文字时保留文字并附事实。

**最大的风险**：`continue_nudged` 的存在是因为 flash 会说“我接下来点确定”然后就停了，`tests/engine/test_ui_task_delivery.py` 专门测这个。删掉后这类提前结束可能重现。A/B 要专门看 ui 用例的提前结束。如果确实退步，保留“回合末没有工具调用且最后一轮是计划性文字”的一次性提醒是错误方向（靠猜语义）；更好的替代是把这件事交给可选的旁观模型（笔记 02），或者接受并在尾注里写明未决状态。由数据决定。

**测试**：`test_task_delivery*`、`test_ui_task_delivery`、`test_browser_primary_loop`、`test_cua_observation`、`test_subagent_ui_delivery`、`test_subagent_stage_a_fixes`、`tests/goal/*`、`tests/contract/test_transcript.py` 中的 finish_task 用例。前端 `deepseek-runtime.ts:2083` 的状态白名单要加新状态。

**验收**：通过率不降、ui 会话轮次下降、答复丢失为 0、`task.honest_rate` 上升。

### 2.3 按效果和路径管控

这是笔记里最需要修正的一项。

**三个与笔记不同的事实**：

1. **事后回滚在非 Git 工作区做不到 [读码]**。`shell_mutation_watch` 的快照只看 dirty/untracked 集合，`turn_checkpoints` 的 pre-image 来自 `pre_contents` 或 `git show`。`python -c os.remove` 删掉一个非 Git 目录里的已有文件之后，没有东西可以恢复。“越权则回滚”要先有删除前的内容。
2. **沙箱默认没开 [实测]**。用户配置是 `sandbox_mode = "danger-full-access"`，seatbelt 不生效。“工作区外写入靠沙箱强制”要改默认值才成立。
3. **`check_shell_write` 不止一个职责 [读码]**。`check_managed_worktree_git` 保护托管 worktree，要保留，只删后缀和正则部分。

**摸底结论 [实测，实现 session]**：非 Git 工作区里 `capture_shell_snapshot` 完全是空的，mutations 为 `[]`。soak 和 `daily_tasks` 全是非 Git 工作区，所以所有权不能只靠 `mutation_ledger`，实现改用文件创建时间判断。

**建议分两步**：

- **第一步（低风险，先交付）**：去掉后缀拦截，改为“所有权 + 命令名粗分类”。
  - 本会话创建的文件随便动。用文件创建时间与会话开始时间判断，Git 工作区可叠加 `mutation_ledger`。
  - 对已有文件的 `rm`、`mv`（`command_safety.analyze_command` 已有分级，复用）解析目标，命中已有文件走审批；无人值守时拒绝，并给出可走的路：移到 `_to_delete/` 并告诉用户（Cowork 协议）。
  - 联网安装、git 变更、结束进程：`analyze_command` 分类走审批。
- **第二步**：解决解释器绕过。回合开始时对已有文件记录清单（路径、大小、mtime），小文本保存 pre-image，放不下的只记录。命令后对比，已有文件消失时如实告知，能恢复就恢复。这一步的目标是“看得见”，不是“防得住”，尾注里写明。

**验收**：用 soak 的 **184 条**被拦命令回放（不是笔记的 132 条），审计里有提取脚本的口径；误拦约 0；工作区外安装 0。绕过率用 `session.guard_bypasses`，但守卫删除后要改成“已有文件被非授权改动”的计数。

## 4. 阶段三

### 3.1 上下文治理

**关键发现 [读码]**：`maintenance.py` 注释写明 “Ages tick per user turn”，`prune_old_tool_results` 按用户回合算年龄。**单个回合内部结果永远不老化**。soak 里前 10% 的回合吃掉 61% 的 token，最大一个回合 2465 万，这些长回合恰好不受修剪影响。这比“阈值太高”更可能是主因。

**a. 先做配置实验，不写代码（尚未执行，需要 live 运行）**：`[providers.deepseek.context_windows]` 已经存在。设 `"deepseek-flash" = 128000` 跑一轮，看压缩触发后通过率和 token。这直接回答“有效上下文该多大”，笔记里的 128k 目前没有证据。`daily.long_context`、`daily.goal_execution`、`daily.web_app` 最相关。

**b. 再做确定性修剪**：

- 增加按**轮次**的年龄，让长回合内也能老化。
- 规则：同标签页旧观测折叠；被修改或重读过的旧 `read_file` 折叠；N 轮前搜索结果留标题、URL、被引用片段；截图留最近 K 张。
- 硬清理会破坏前缀缓存，`L0_HARD_CLEAR_MIN_RECLAIM` 的批处理逻辑要保留。修剪后看 `prefix_cache` 日志的命中率。
- **离线评估**：`transcript.jsonl` 记录了每轮实际消息，可以把历史 transcript 喂给新修剪器，算出能回收多少，不花模型调用。

**验收**：每回合输入 p90、最大值明显下降，缓存命中率不大降，通过率不降。

### 3.2 环境能力清单

- **证据 [实测]**：基线 `document_merge`、`documents`、`spreadsheet`、`presentation` 全部因为没有 python-docx、openpyxl、LibreOffice、pandoc 而手写 OOXML 或自行渲染排版，单回合超过 15 分钟，`spreadsheet` 甚至翻到 `~/.cache/uv` 里找库。这是当前失败最集中的一类。
- 首次启动探测，按机器缓存（`~/.deepseek/caches`），写进 `## Environment`（`engine/prompts.py:65`）。会话内不变，不破坏前缀缓存。
- 探测：python/node 版本，python-docx、openpyxl、python-pptx，soffice、pandoc，GNU vs BSD（macOS 没有 `timeout`，soak 中 26 个命令用到它，9 次明确报 not found）。
- 内置 docx/pptx/xlsx skill 和自带依赖。打包方式需要用户定（第 7 节）。
- **验收**：办公类超时下降，`session.installs` 为 0。

### 3.3 独占资源仲裁

- `cua/session.py:68` 桌面被占用时立即失败，soak 中 28 次，是 `exec_shell`、`browser_use` 之外最多的工具错误。**[实测]**
- 改成租约 + 排队，返回预计等待时间；子代理继承（`subagent_manager.cua_owner_id` 已有归属概念）。
- 浏览器会话同理，但 soak 没有证据显示它是问题，先不做。

### 3.4 提示词瘦身

- 目标：`base.md` 33.9KB → ≤12KB，`browser.md` 18.3KB 大幅收缩。
- **方法**：按 `##` 段逐段处理（Doing Tasks、Action Safety、Verification and Faithful Reporting 等共 16 段）。每段问笔记 02 的那句话：防的是什么失败、在目标模型上还复现吗。逐段删、逐段跑，`manifest.prompt_hash` 已记录。
- 同时做：已注入的项目指令告知“无需再读”（soak 中 125/205 会话重读）；项目指令向上查找在仓库根或 home 停止（`engine/context.py:_load_project_layer`）；删除 `LONG_SESSION_DRIFT` 周期提醒，看干预日志和通过率；收敛“3 个以上文件开子代理”的表述。
- flash 专用变体等 base.md 收敛后再做。

### 笔记 02 的增补项

- **无人值守模式**（已提前，见第 2 节）：`metadata["unattended"]` 已存在（`engine/dispatch.py:884`，用于自动化），但只在工具层拒绝，模型不知道。需要写进提示词并给行为规则：先写明假设再继续，不可逆决策做完准备后停下。soak 7 个“等待输入”和基线 `software_research` 都是这个问题。评测的产品服务应打开它：`evals/harness/product.py` 目前等 60 秒后判定卡住。
- **工具契约**：声明写入成功即生效；拦截前台 sleep 并提供等待原语（soak 163 次，集中在 20 个会话，一个会话 89 次）；输出截断时返回原始规模；幻觉工具名在报错中列出正确名称。
- **定价**：`client/pricing.py:147` 不认识 `deepseek-flash`，所以用量面板的费用是未知。
- **同类隐患**：`max_output_tokens_for_model` 对未知模型回落到 4096。model 列表接口已返回 `max_output_tokens`（flash 为 393216），可以考虑用它，或至少在回落时打日志。
- **评审增强**：一条确定性核对，“答复声称测过但 transcript 里没有运行记录”，补上评审看不到过程的缺口。
- **界面用例真实操作**：复用产品浏览器或 `evals/browser_bench` 的 fixture 机制做页面检查，替代只读源码。

## 5. 不做

- 不从 `ui_reorder_list` 这种单个失败反推规则（笔记 02 的近因陷阱）。
- 不给 flash 单独写规则去修某个用例。
- 不把“旁观模型”提前：它是阶段 5，必须证明净收益。
- 不在循环里加新门控。遇到问题先按笔记第六节判断：是世界层没交代清楚、内核不变量没守住，还是模型本身的限制。

## 6. 指标口径

| 指标 | 字段 | 目标 |
|---|---|---|
| 打分通过率 | `task.pass_rate` | 不降 |
| 如实率 | `task.honest_rate` | 上升 |
| 虚报率 | `task.overclaim_rate` | 下降 |
| 答复丢失 | `session.answers_lost` | 0 |
| 被拦后绕过 | `session.guard_bypasses` | 0 |
| harness 消耗的轮次 | `session.harness_rounds` | 下降 |
| 轮次、token | `session.rounds`、`session.input_tokens` 的 p90 | 下降 |
| 各类干预 | `session.interventions.*` | 配合判定看有用率 |

## 7. 需要用户决定

笔记第 7 节的待决策项，附建议。没有明确答复时按建议实施，并在提交说明里写明。

| # | 问题 | 建议 |
|---|---|---|
| 1 | finish_task 整体删除，还是保留为可选？ | 删除。保留可选等于保留两套语义 |
| 2 | Goal 完成审计是否去掉？ | 去掉，只留目标、预算、续跑、队列。注意依据只有 1 个会话，属于设计判断，不是数据结论 |
| 3 | 已有文件的删除是否一律审批？无人值守的默认？ | 日常审批；无人值守拒绝并走 `_to_delete/` |
| 4 | “新视角审查”子代理默认开启？ | 不开，等数据 |
| 5 | `sandbox_mode` 默认值是否从 `danger-full-access` 收紧？ | 新增决策。收紧才能实现“工作区外写入受限”，但影响现有用户 |
| 6 | 办公依赖怎么打包？ | 新增决策。随应用内置专用 venv，还是首次使用时安装 |
