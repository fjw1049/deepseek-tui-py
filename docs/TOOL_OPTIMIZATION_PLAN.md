# 工具系统优化方案 — TOOL_OPTIMIZATION_PLAN

> 来源：2026-07-25 工具系统全面审核（两个维度：内置工具盘点 + 外部工具来源/治理），对照 Claude Code / Kimi Code CLI 的工具设计。
> 状态：Phase 0 进行中。

## ⚠️ 与项目奇偶约束的关系（先读）

本项目是对 Rust 版 DeepSeek-TUI（74 个工具）的**行为复刻**（见 `docs/HANDOVER.md`）。因此：

- **Phase 0**（按环境条件注册、plan 模式收窄、冲突告警）属于健壮性修复，与复刻语义不冲突，可直接做。
- **Phase 1**（工具合并 58 → ~30）**会改变对模型暴露的工具表面**，与"百分百行为复刻"存在张力。执行前需拍板：要么接受对 Rust 版的偏离（在 parity 测试中标注为有意分歧），要么只做 schema 收敛不做工具合并。

## 审核发现摘要

### 工具来源（5 个）
1. 内置工具：`tools/registry.py:508 build_default_registry`，默认 50 个，开 `features.automations` 后 58 个
2. 引擎伪工具（不进 registry）：`code_execution`、`tool_search_tool_regex/bm25`（`engine/tools.py:165-249`）；子代理动态注入 `structured_output`
3. MCP 外部工具：`mcp_<server>_<tool>`，由 `McpManager` 发现拼入 catalog
4. 插件：不能直接提供原生工具，唯一通道是声明 MCP server（trusted 才装配）
5. Skills/Hooks/LSP：均非工具

### 主要问题
- plan 模式仍注册 `github_comment`/`github_close`、`task_create`、`agent_spawn` 等副作用工具（`registry.py:600-694`），安全全靠审批门兜底
- `github_*` 无 feature flag，无 `gh` CLI 环境必失败（`registry.py:624-630`）
- `web_search`/`fetch_url` 注册不校验 API key（`registry.py:608-615`）
- MCP 工具名清洗冲突静默覆盖 `_tool_map`（`mcp/manager.py:932-934`）；catalog 合并不去重（`engine/tools.py:139-141`）
- `prompts/base.md:119` 提及默认未注册的 `automation_*`
- schema 双别名泛滥：`todos|items`、`task_id|id`、`prompt|message|objective`、`agent_wait` 四别名
- `retrieve_tool_result` 是设计 smell：截断应内聚到各工具
- 死代码：`register_exclusive()`（`registry.py:257`）、`ToolSpec.defer_loading()`（`registry.py:90`）、`mcp__` 双下划线分支（`mcp/client.py:51-55`）
- `tools/validation.py` 名不副实（run_tests 工具 + 子代理输出 + 校验辅助三合一）
- 审批双层：`tools/approval.py` vs `policy/approval.py`
- `config.example.toml` 严重滞后；`tools/approval.py:15` 引用不存在的 `docs/APPROVAL_CODE_AUDIT.md`；`docs/deadcode_audit.md` 行号已过时

### 保留不动的设计（做得好的）
- tool_search + deferral 渐进加载
- 审批指纹缓存（`policy/approval.py:78-180`）、网络域名策略、Seatbelt 沙箱
- 插件 permissions 不能降低 MCP 工具审批等级（`tools/approval.py:106-110`）
- 后台任务无交互时显式 Deny（`engine/dispatch.py:387-395`）

---

## Phase 0 · 安全与正确性修复 ✅ 已完成（2026-07-25）

| # | 改动 | 位置 | 状态 |
|---|---|---|---|
| 1 | `github_*` 按 `gh` CLI 存在才注册（`shutil.which` 探测，缺失时 info 日志） | `tools/registry.py:624-630` | ✅ |
| 2 | ~~`web_search`/`fetch_url` 注册时校验 API key~~ **放弃**：AnySearch 设计为免 key 调用（`tools/web.py:305-315` 仅在有 key 时加 Authorization 头），门控会误删可用路径 | — | ❌ 放弃 |
| 3 | plan 模式排除副作用工具：github_comment/close、task_create/cancel/resume/gate_run/shell_start、agent_spawn/resume/send_input、workflow、note（plan 注册表 45→33） | `tools/registry.py` | ✅ |
| 4 | MCP 命名冲突 warning + catalog 按 qualified name 去重（native 优先） | `mcp/manager.py:929-947`、`engine/tools.py:139-158` | ✅ |
| 5 | `base.md` 移除 `automation_*` 提及 | `prompts/base.md:119` | ✅ |

验证：plan 模式副作用工具零泄漏断言通过；相关测试 245 passed；3 个失败（test_live_rlm_subagent_task、test_live_today_integration、test_p0_audit_fixes）与 3 个 parity 失败（test_mcp_hooks_p1）经 stash 对照确认均为**存量失败**，与本次改动无关；`tests/test_live_full_workflow.py` 引用不存在的 `wire_registry_client`，存量 collection 错误。

备注：`prompts/base.md.bak` 是遗留备份文件，内容已过时，建议另行删除（本次未动）。

## Phase 1 · 工具合并 ✅ 已完成（2026-07-25）——接受与 Rust 版的偏离（用户拍板 2026-07-25）

默认注册表 50 → 40（plan 模式 26）。

| 现状 | 结果 | 说明 |
|---|---|---|
| `git_status/diff/log/show/blame` | ✅ `git`（command 枚举：status/diff/log/show/blame） | 5→1 |
| `note` + `update_plan` | ❌ **放弃合并**：note 是代理持久记忆（追加 notes 文件），update_plan 是用户可见 UI 状态（.deepseek/plan.md + sidebar 同步），语义不同，合并会让模型困惑 | 保持两个工具 |
| `agent_spawn/result/cancel/resume/list/send_input/wait` | ✅ `agent`（action 枚举：spawn/result/cancel/list/send_input/wait）+ `agent_resume`（修正 resume_agent 命名例外） | 7→2；plan 模式 `AgentTool(allowed_actions=["result","cancel","list","wait"])` 且不注册 agent_resume；新增 `ToolSpec.approval_requirement_for_input()` 钩子保持 result/list/wait 免审批 |
| `checklist_list` + `checklist_write` | ✅ `checklist`（省略 todos 即读取，提供即全量替换） | 2→1；plan 模式可用（内存状态，不触工作区） |
| `retrieve_tool_result` | ⬜ 待 Phase 2.2（输出截断下沉）后删除 | — |
| 双别名 schema | ✅ 全部收敛：schema 只留规范名，执行层兼容旧别名 + debug 日志（task 的 `id`、agent 的 `message/objective/type/id/ids/mode`、checklist 的 `items`） | — |

验证：新增 `tests/test_tool_catalog_snapshot.py`（agent/plan 两个 golden 快照 + plan 无副作用工具断言）；全量 1047 passed，13 个失败均为存量（7 个 live API 401 + 6 个既有问题），零新增失败。

遗留：`packages/workbench`（Electron/TS 渲染层）仍按旧工具名渲染，需单独立项跟进。

进度：git 五工具→`git` ✅；checklist 二合一 ✅；**agent 七工具→`agent`+`agent_resume` ✅（2026-07-25）**——`AgentTool(action 枚举)` 注册时传 `allowed_actions`（agent 模式全量 6 个，plan 模式 `["result","cancel","list","wait"]`，enum 按构造参数生成，plan 不注册 `agent_resume`）；schema 去别名（`agent_id`/`agent_ids`/`wait_mode`/`prompt`/`agent_type`），执行层兼容旧别名并 debug 日志；`ToolSpec.approval_requirement_for_input` 新钩子保证 result/list/wait 不触发审批（保持合并前行为）。默认注册表 45→40。测试：1044 passed + 13 个存量失败（live API 401 等，与本次无关）；parity 19 passed + 3 个存量 test_mcp_hooks_p1 失败。

## Phase 2 · 工具内聚性 ✅ 已完成（2026-07-25）

1. ✅ 路由纪律写进描述：`exec_shell`（"搜内容用 grep_files、找文件用 file_search、读用 read_file、改用 edit_file；shell 留给构建/测试/git/进程管理"）、`read_file`/`edit_file`/`write_file`（先读后改、新旧文件分工）、`grep_files`/`file_search`（优先于 shell grep/find）
2. ✅ 输出截断下沉 + 退役 `retrieve_tool_result`（40→39）：spillover 机制本就已落盘大输出，footer 改引导 `read_file`/`grep_files`；`resolve_path` 对 `allow_read_roots=True` 放行 spillover 目录（lazy import 避免循环依赖），写模式仍锁工作区
3. ✅ 敏感文件过滤进实现层：新建 `tools/sensitive.py`（保守清单：`.env`/`.env.*`（放行 example/sample/template）、`id_rsa` 等私钥（`.pub` 放行）、`*.pem`/`*.key`、`credentials`/`.netrc`/`.npmrc`/`.pypirc`）；`read_file` 拒读、`grep_files`/`file_search` 遍历跳过；`list_dir`/写工具不过滤
4. ✅ 全局入参校验：`registry.execute` 在调用前对照 `input_schema()` 做 jsonschema 校验（Draft202012Validator 按工具名缓存；错误信息带 json_path 供模型自我修正；schema 非法时 fail-open + warning）。关键设计：校验层剥离 `additionalProperties: false`（递归拷贝，不改对外 wire schema），保住执行层旧别名兼容

验证：新增 `tests/test_spillover_footer.py`（3）、`tests/test_sensitive_files.py`（8）、`tests/test_registry_input_validation.py`（10）；全量 1068 passed，13 个失败均为既有清单，零新增。

## Phase 3 · 治理与文档 ✅ 已完成（2026-07-26）

- ✅ 拆 `tools/validation.py` 三合一：`RunTestsTool` → `tools/run_tests.py`；`StructuredOutputTool` → `tools/subagent/structured_output.py`；validation.py 回归本名（257→66 行，只剩参数校验辅助）
- ✅ 合并审批双层：`policy/approval.py` 物理并入 `tools/approval.py`（533→约 900 行，8 个 section），删除委托回环；16 个文件 25 处 import 全部改指 `tools.approval`；指纹缓存（`ApprovalCache`/`build_approval_key`）原样保留；`engine.dispatch` 模块级 import 下沉为函数级消除真循环
- ✅ 删死代码：`register_exclusive`（连同其专属测试）、`ToolSpec.defer_loading()`（wire 字段保留字面量 False）、`mcp__` 双下划线解析分支（连同 parity 专属用例）。备注：`engine/dispatch.py:143` 的 `mcp__` startswith 检查与解析分支无耦合（且被 `mcp_` 检查完全覆盖），保留
- ✅ `config.example.toml` 补全：`approval_policy`（7 个合法值注释）、`sandbox_mode`（4 个合法值）、`allow_shell`、`skills_dir`、`mcp_config_path`、`[features]` 6 开关、`[hooks]` 段——全部字段对照 `config/models.py` 行号核实，loader 实测可解析
- ✅ 文档修正：plugins.py manifest 清单补 `.codebuddy-plugin`、skills.py 目录优先级补 `.deepseek/skills`、`tools/approval.py` 失效引用改指本文档、`docs/deadcode_audit.md` 顶部加过时警告

验证：全量 1067 passed / 13 失败（全为既有清单）+ parity 18 passed / 3 失败（既有）；35 个护栏测试（快照/校验/敏感文件/spillover/checklist/focus）全绿。

---

## 最终状态（2026-07-26）

- 默认注册表：**50 → 39 工具**（agent 模式）；plan 模式 23 个，写文件/shell/git 写/task 突变/workflow/automation/run_tests/note/agent spawn 类全部排除（保留 task_shell_wait 与 agent 的 result/cancel/list/wait 作为既有任务的查看/控制通道——这是有意决策，不是"零副作用"）
- schema：全部单名参数，旧别名仅执行层兼容（不进 schema）+ debug 日志
- 安全：gh CLI + 登录态门控、敏感文件源头过滤、spillover 目录只读放行、全局 jsonschema 入参校验、单一权威审批模块、审批指纹按 action/target 分离
- 护栏测试：`test_tool_catalog_snapshot.py`、`test_registry_input_validation.py`、`test_sensitive_files.py`、`test_spillover_footer.py`、`test_checklist_tool_aliasing.py`、`test_agent_merge_approval.py`
- 遗留（2026-07-26 已全部处理）：✅ `packages/workbench` TS 渲染层跟进新工具名（12 文件，`agent` 按 action 区分渲染，旧名保留历史回放 fallback；vitest 363 通过 / 2 个预存失败）；✅ `prompts/base.md.bak` 已删除；✅ `test_live_full_workflow.py` 修复（删除 RLM 移除后残留的 `wire_registry_client` 调用，恢复可收集）
- 仍待另行处理：存量测试失败（7 个 live API 401、rlm test_10、today test_01/06、live_presentation、live_full_workflow（同为 401 环境）、p0_audit_fixes、mailbox_sse、seatbelt、usage_ledger、parity test_mcp_hooks_p1 ×3）——均为环境/预存问题，与本优化无关

---

## 复审修复轮（2026-07-26，外部 code review 裁决后）

外部复审（Cursor）对 Phase 0–3 提出 11 条缺陷，逐条对代码裁决：**9 条完全属实、1 条部分属实（`*.key` 过滤偏宽，方向正确暂不动）、1 条观点分歧（删 `register_exclusive`——维持删除，插件 overlay 从未使用原生工具注册）**。属实项已全部修复：

| # | 缺陷 | 修复 |
|---|---|---|
| 1 | 审批指纹串权：`agent` 所有 action 共用 `tool:agent`，session 批准 spawn 后 send_input/cancel 全放行 | `build_approval_key` 新增 agent 分支，指纹纳入 action + agent_id/process_id（`tools/approval.py`） |
| 2 | `classify_tool_category` 用 `startswith("agent_")` 不匹配 `"agent"`，审批 UI 分类 unknown | 改为 `== "agent" or startswith("agent_")` |
| 3 | `checklist` 读路径也走写审批（固定 WRITES_FILES） | `ChecklistTool.approval_requirement_for_input`：无 todos/items → AUTO |
| 4 | 子代理审批未传 input_data，agent 只读 action 误判 REQUIRED | `subagent/loop.py` 传入 tool_input |
| 5 | plan「零副作用」有洞：`run_tests`、`automation_*` 仍注册；snapshot denylist 漏写 | registry 排除两者；snapshot 测试 denylist 补 `run_tests`，新增 automations 开启时的 plan 断言 |
| 6 | `plan.md` 文案误导（提 spawn/shell） | 重写为与实际工具面一致 |
| 8 | gh 只查 PATH 未查登录 | `_gh_cli_ready()`：`gh auth status` 探测（lru_cache 每进程一次） |
| P2 | MCP server↔server 同名仍重复进 catalog（只告警没去重） | `mcp/manager.py` 同名条目原位替换，catalog 不再重复 |
| P3 | snapshot 无 gh 机器整段 skip | 改为按 `_gh_cli_ready()` 动态裁剪期望列表，非 github 漂移在任何机器都会被测到 |

新增 `tests/test_agent_merge_approval.py`（4 个用例：指纹按 action/target 分离、分类、checklist 读路径 AUTO）。教训记录：`approval_requirement_for_input` 这类 per-input 钩子必须在**所有**审批路径（主引擎、子代理、指纹、分类、展示）同时接线，合并 action 型工具时逐路径核对。

验证：全量 1072 passed / 14 failed（13 个既有 + `test_live_full_workflow.py` 修复 collection 后首次运行，同为 401 环境问题）；parity 18 passed / 3 既有。零真实回归。

### 复审第二轮（2026-07-26，复审方结论"可以合"后的收尾项）

| 项 | 处理 |
|---|---|
| 并行调度用静态能力，agent list / checklist 读被假串行 | ✅ 新增 `ToolSpec.is_read_only_for_input()`（基类回落静态值），`AgentTool`（READ_AGENT_ACTIONS）与 `ChecklistTool`（无 todos 即读）接线；`plan_requires_approval` 增加 input_data 参数；`tooling.py` 批调度传入 arguments。顺带拆掉 `AgentTool.capabilities()` 并集含 READ_ONLY 导致静态 `is_read_only()` 恒 True 的语义坑 |
| `classify_tool_category("checklist")`/`("git")` 仍 unknown | ✅ 归入 `"safe"`（与 note/update_plan 同类） |
| spawn 的 session 指纹不含 prompt | ❌ 不修：合并前 `tool:agent_spawn` 同语义，非新回归；收紧需 prompt 摘要设计，留待需要时单独立项 |
| 测试缺口（subagent loop 传参路径） | ✅ `test_agent_merge_approval.py` 补 8 个用例：per-input read-only、plan_requires_approval 接 input、分类、以及 `_execute_subagent_tool` 的 list 不弹审批 / spawn 无 bridge 被拒两条端到端路径 |

验证：全量 1078 passed / 14 failed（同前，全环境/存量），零回归。
