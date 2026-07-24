# 工具集 Claude 对齐 — Session 交接（2026-07-24）

> 目的：把本项目的 LLM 工具集（tools）向 Claude Code 的工具语义和提示词逻辑对齐，使按 Claude 风格编写的提示词可以直接生效。
> 状态：**第 1–4 阶段 + 2 个杂项已全部完成并提交到 `build_0725` 分支**。剩余第 5 阶段（改名）未做，见下文"待办"。

## 背景与总体结论

审查发现的问题不是工具太少，而是**太多、且核心编辑工具的语义与 Claude 相反**。整个对齐的净效果：

- 默认注册工具：~62 → 53
- agent 模式每步实际激活（发给模型）的工具：~55 → **27**
- 核心工具语义与 Claude Code 一致，提示词体系（`src/deepseek_tui/prompts/base.md` + `modes/*.md`）已同步改写

## 已完成的工作（按阶段）

### 阶段 1：edit_file 语义对齐（最高优先级）

`src/deepseek_tui/tools/file.py` `EditFileTool`：

- 参数主名改为 `old_string` / `new_string`，新增 `replace_all`（boolean, default false）；execute 仍兼容旧别名 `search` / `replace`
- **行为反转**：old_string 出现多次且未设 `replace_all` → 报错（提示补充上下文或设 `replace_all=true`），不再静默全文替换；0 次 → 保持原 not-found 报错
- description 写明"编辑前需先 read_file 该文件"。**注意：仓库没有读取追踪机制，这只是文本约束，无引擎强制**

### 阶段 2：删除 7 个冗余工具

| 删除 | 连带清理 |
|---|---|
| `apply_patch` | patch.py 约 700 行 diff/fuzz 引擎、`features.apply_patch` 配置开关（config/models.py） |
| `multi_tool_use.parallel` | 引擎 fan-out 拦截（orchestrator/tooling.py、dispatch.py 的 parse_parallel_tool_calls） |
| 废弃别名 `spawn_agent` / `send_input` | encoding.py 的 `DeprecatingAliasTool` 整套机制 |
| `delegate_to_agent` | task_create description 同步改为只提 agent_spawn + agent_wait |
| `checklist_add` / `checklist_update` | todo.py 两个类；checklist 家族只剩 write + list |

约 25 个文件的引用同步清理（审批策略、TUI、server、子代理白名单、prompts）。patch.py 中保留 `diagnostics` 和 `project_map`。

### 阶段 3：read_file / grep_files / write_file 语义细节

- **read_file**：输出带 `行号\t内容` 前缀（cat -n 风格，从 offset 起算）；默认上限 2000 行，截断时提示 `... (showing lines X-Y of Z; use offset to continue)`；单行超 2000 字符截断标记
- **grep_files**：新增 `output_mode`（content / files_with_matches / count_matches）、`head_limit`（默认 200）、`-A`/`-B`/`-C` 上下文行；content 模式输出 `路径:行号:内容`；description 按 Claude Grep 风格重写
- **write_file**：description 加"覆盖已存在文件前必须先 read_file"（文本约束，无强制）

### 阶段 4：23 个非核心工具转 defer_loading

agent/plan 模式下不再每步发给模型，可用 `tool_search_tool_regex/bm25` 发现或直接调用自动激活：

git_status, git_diff, git_log, git_show, git_blame, github_issue_context, github_pr_context, github_comment, github_close, validate_data, run_tests, diagnostics, project_map, code_execution, task_gate_run, task_shell_start, task_shell_wait, workflow, workflow_list, list_mcp_resources, list_mcp_resource_templates, read_mcp_resource, mcp_get_prompt

实现要点：`engine/tools.py` 的 `_ALWAYS_ACTIVE_TOOLS` 删减；`ensure_advanced_tooling` 新增 `mode` 参数；workflow 模式下 `workflow` 强制激活的特例保留；yolo 模式不受影响；MCP catalog 全部 defer。

### 杂项 1：后台任务管理合并（对齐 TaskOutput/TaskStop 模型）

- `agent_result` / `agent_cancel` 新增 `process_id` 参数，可直接管理 `exec_shell(background=true)` 的后台进程（block/timeout_ms 对两者生效）——**显式参数而非 id 自动识别**（两个 id 命名空间靠前缀识别太脆）
- 删除 `exec_shell_wait` / `exec_shell_cancel`；底层逻辑提取为 shell.py 公开函数 `wait_background_process` / `peek_background_process` / `cancel_background_process`（`task_shell_wait` 复用，行为不变）
- `exec_shell_interact` 保留（PTY 交互无 Claude 对应物）
- 分层：subagent/tools.py 在 execute 内惰性 import tools.shell，依赖单向

### 杂项 2：update_plan vs checklist_write 分工

- `checklist_write`：多步工作的**唯一常规进度跟踪器**（全量替换、最多一个 in_progress）
- `update_plan`：收窄为面向用户的计划呈现——仅 plan 模式 / 用户明确要求 / 引擎强制（`force_update_plan_first`，未动）时使用；禁止双重维护
- base.md Decomposition Philosophy、modes/agent.md、yolo.md 已理顺

## 当前激活工具清单（agent 模式，27 个）

```
agent_cancel, agent_list, agent_result, agent_send_input, agent_spawn, agent_wait,
checklist_list, checklist_write, edit_file, exec_shell, exec_shell_interact,
fetch_url, file_search, grep_files, list_dir, load_skill, read_file,
request_user_input, resume_agent, task_create, task_list, task_read,
tool_search_tool_bm25, tool_search_tool_regex, update_plan, web_search, write_file
```

## 验证基线（回家后以此为准）

```bash
# 全量测试（test_live_full_workflow.py 模块在 HEAD 上就无法 import，预存损坏，排除）
.venv/bin/python -m pytest tests -q --ignore=tests/test_live_full_workflow.py
# 最后验证结果：1048 passed, 18 skipped, 8 failed
```

**8 个失败全部是预存失败**（改动前基线用 git stash 复现确认），属网络/环境类：
subagent_mailbox_sse、mcp_hooks_p1×3、live_today_integration、p0 compact、seatbelt_sandbox、workbench_usage_ledger。
（另有 flaky 的 test_fetch_url 时过时不过。）

新增测试：`tests/test_background_job_tools.py`（6 个）+ test_file_tools.py 4 个 read_file 用例 + test_search_tool.py 7 个 grep 用例。

## 待办（回家后继续）

### 第 5 阶段：工具改名为 Claude 风格（未做，工作量最大）

只有打算**整段搬运 Claude 提示词文本**时才值得做。目标映射：

```
read_file→Read  write_file→Write  edit_file→Edit  exec_shell→Bash
file_search→Glob  grep_files→Grep  agent_spawn→Task  agent_result→TaskOutput
agent_cancel→TaskStop  agent_list→TaskList  checklist_write→TodoWrite
fetch_url→WebFetch  web_search→WebSearch  load_skill→Skill
request_user_input→AskUserQuestion
```

注意：原 `DeprecatingAliasTool` 别名机制已在阶段 2 删除，如需旧名过渡要另写别名方案；`to_api_tool_name`（tools/encoding.py）的转义逻辑对大写命名无影响（`[A-Za-z0-9_-]` 均合法）。

### 小遗留项

1. **sandbox 提权重试**：经 `agent_result` 返回的 shell 结果若带 `sandbox_denied` 元数据，不再触发 L3 一键提权重试（原 exec_shell_wait 在 orchestrator/tooling.py 的判定元组里）。等待路径不执行新命令、风险低；在意的话把 agent_result 加回该元组。
2. **packages/workbench/（TS 前端）**：仍按名字渲染 exec_shell_wait/exec_shell_cancel/apply_patch 等历史工具——属历史 transcript 渲染兼容，有意保留，勿删。
3. **docs/ 历史文档**（HANDOVER.md、DYNAMIC_WORKFLOW.md 等）：仍记述被删工具，属历史记录，未动。
4. **引擎层 read-before-write/read-before-edit 强制**：目前只是 description 文本约束，如要真强制需新造读取追踪机制（Claude 有此机制）。

## 关键文件索引

- 工具注册：`src/deepseek_tui/tools/registry.py`（`build_default_registry`）
- defer 机制：`src/deepseek_tui/engine/tools.py`（`_ALWAYS_ACTIVE_TOOLS`、`should_default_defer_tool`、`ensure_advanced_tooling`、`active_tools_for_step`）
- 核心工具：`tools/file.py`（read/write/edit）、`tools/search.py`（grep/file_search）、`tools/shell.py`、`tools/subagent/tools.py`、`tools/todo.py`、`tools/knowledge.py`
- 提示词：`src/deepseek_tui/prompts/base.md`（Toolbox 快查 :114-126、Tool Selection Guide、Decomposition Philosophy）+ `prompts/modes/*.md`
- 注意 `prompts/base.md.bak` 与 base.md 同步维护（两者都改了）

## Session 操作记录

- 工作分支：`build_0724` → 新分支 `build_0725`（本次全部改动 + 本文档，单次提交）
- 未做 git push；8 个预存测试失败与本次无关

## 复审与修复（2026-07-24 晚，home）

对 5888b1e 做了四轮独立审查（含与 Cursor 分析的交叉裁决），确认**对现有功能零回归**，但发现 deferral 接线漏洞并已全部修复（未提交，工作树改动）：

1. **无 MCP / 空 MCP / 冷启动时 deferral 不生效**（`core.py` `_get_tools_with_mcp`）：三条 native-only 分支补上 `apply_native_tool_deferral`。修复前无 MCP 时 56 个工具全发，特性静默失效。
2. **`agent_result(process_id, block=true)` 大输出假超时**（`shell.py`）：timed 分支从 `process.wait()`（不排空管道，子进程写满 pipe buffer 后死锁到超时）改为缓存的 `communicate()` collector task + `shield` 超时；`cancel` 复用同一 collector。
3. **TurnLoop 未透传 mode**（`turn.py:156`）：`run()` 新增 `mode` 参数，`core.py` 调用点传 `self.mode`；code_execution 在 agent/plan 模式下正确 defer。
4. 小修：grep 相邻 match 不再误标 context（`search.py` 按全文件 match 集合判定）；`agent_result`/`agent_cancel` 同传 agent_id+process_id 报冲突；审批预览兼容 `old_string`/`new_string`；`agent_result` description 与 base.md(.bak) 明确收集后台进程用 `block: true`。

验证：agent 模式无 MCP 下 active 工具 = **27**，与上文清单逐名一致。新增回归测试 11 个（test_background_job_tools +4、test_search_tool +1、test_mcp_engine_integration +4、engine/test_core_fixes +2）。全量：`1050 passed, 19 skipped, 16 failed`——16 个失败与修复前完全相同（8 预存 + 7 live API 无 key + 1 p0 陈旧测试），零新增。
