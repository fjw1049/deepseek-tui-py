# DeepSeek-TUI Python 重写执行清单

> 执行规则：严格按阶段推进；每完成一项就勾选；阶段一全部完成后，进入阶段二。

> ⚠️ **2026-05-06 状态校准**：本文件之前标注的"阶段五、六全部完成 / 核心架构完整 / 97 测试通过 = 生产就绪"是**误判**。经 `docs/AUDIT/` 下五阶段逐文件对比（Rust ~161K 行 vs Python 7.6K 行），实际 parity 约 **5%**：工具 32/74（其中 ~22 为 stub/in-memory）、49 个 slash 命令 / 28 个 HTTP 路由 / ~30K 行 top-level sub-managers / 17 个 prompt 模板几乎全部未实现。
>
> 真实路线图见 `docs/AUDIT/SUMMARY.md` §七（Stage 0→7，约 31–46 周）。本文件下面的勾选项记录的是**脚手架是否搭起**，不代表行为等价。

## 当前进度

- 当前阶段：**Stage 0（工程基础校准）进行中**
- 当前状态：脚手架齐 + `make check` 三项绿（ruff / mypy / pytest 97 passed）。真实行为复刻度低（见 `docs/AUDIT/`）。
- 下一动作：Stage 0 剩余项 → Stage 1（协议 / 密钥优先级 / 状态 schema / tool name codec / registry 排序）

---

## 阶段一：基础设施

### 1. 项目脚手架
- [x] 创建 `pyproject.toml`
- [x] 创建 `src/deepseek_tui/` 包结构
- [x] 创建 `__main__.py` 和 CLI 入口
- [x] 创建 `config.example.toml`
- [x] 创建基础测试目录 `tests/`
- [x] 创建项目说明 `README.md`
- [x] 增加 `ruff` 配置文件或补充统一格式化脚本
- [x] 增加 `mypy` 执行脚本
- [x] 增加 `pytest` 执行脚本
- [x] 增加 `pre-commit` 配置

### 2. 配置系统
- [x] 实现 `config/models.py`
- [x] 实现 `config/loader.py`
- [x] 实现 `config/env_mapping.py`
- [x] 支持 profile 合并
- [x] 支持环境变量覆盖
- [x] 增加 CLI 参数覆盖链
- [x] 增加 provider 专用字段扩展
- [x] 增加 `config/paths.py`，支持默认 config、项目 overlay、`.env`、managed config、requirements 路径
- [x] 增加 `config/provider_registry.py`，支持 provider defaults、模型别名、context window 基础判断
- [x] 支持项目 `.deepseek/config.toml` overlay
- [x] 支持 `.env` 启动加载
- [x] 支持 managed config 与 requirements 校验
- [x] 扩展 retry/features/snapshots/context/capacity/subagents/tui 配置模型
- [x] 增加配置错误模型与更清晰的异常信息
- [x] 编写配置测试

### 3. 密钥管理
- [x] 实现 `secrets/manager.py`
- [x] 支持环境变量优先级
- [x] 支持配置文件回退
- [x] 支持 keyring 回退
- [x] 增加写入/删除/列出密钥能力
- [x] 增加多 provider 测试
- [x] 编写密钥测试

### 4. 持久化
- [x] 设计基础 SQLite schema
- [x] 实现 `state/database.py`
- [x] 实现 `state/sessions.py`
- [x] 实现 `state/checkpoints.py`
- [x] 实现 `state/offline_queue.py`
- [x] 实现 `state/threads.py`
- [x] 实现 `state/messages.py`
- [x] 实现 `state/jobs.py`
- [x] 扩展 SQLite schema：threads/messages/thread_dynamic_tools/jobs
- [x] 增加迁移版本表
- [x] 增加会话删除与级联测试
- [x] 增加 checkpoint 恢复接口
- [x] 编写状态层测试

### 阶段一完成条件
- [x] 能通过统一测试命令
- [x] 能通过静态检查命令
- [x] 基础目录结构与计划一致到可继续扩展的程度

---

## 阶段二：核心引擎

### 5. 协议类型
- [x] 创建 `protocol/__init__.py`
- [x] 实现 `protocol/messages.py`
- [x] 实现 `protocol/requests.py`
- [x] 实现 `protocol/responses.py`
- [x] 实现 `protocol/errors.py`
- [x] 为消息、工具调用、usage、stream event 编写测试

### 6. LLM 客户端
- [x] 创建 `client/__init__.py`
- [x] 实现 `client/base.py`
- [x] 实现 `client/deepseek.py`
- [x] 实现 `client/openai_compat.py`
- [x] 实现 `client/streaming.py`
- [x] 实现 `client/retry.py`
- [x] 实现 `client/pricing.py`
- [x] 实现 `client/chat_messages.py`
- [x] 打通 SSE 事件解析
- [x] 打通重试与透明重连
- [x] 修复 DeepSeek/OpenAI Chat Completions function tool schema
- [x] 支持 `stream_options.include_usage`
- [x] 支持 tool_choice/temperature/top_p/reasoning_effort/extra_body 请求字段
- [x] 支持 DeepSeek V4 thinking message serializer 与 orphaned tool call 清理
- [x] 完成 DeepSeek live API tool payload 验证
- [x] 编写 mock HTTP 测试

### 7. 工具系统
- [x] 创建 `tools/__init__.py`
- [x] 实现 `tools/base.py`
- [x] 实现 `tools/context.py`
- [x] 实现 `tools/registry.py`
- [x] 实现 `tools/encoding.py`
- [x] 实现 `tools/builder.py`
- [x] 实现 `tools/file_tools.py`
- [x] 先落地 4 个文件工具：`read_file` `write_file` `edit_file` `list_dir`
- [x] 工具 API 导出改为 OpenAI-compatible function schema
- [x] 默认 registry 按 mode/features 装配工具
- [x] 默认 workspace 边界保护，`trust_mode=True` 才允许越界
- [x] 编写工具系统基础测试

### 8. Engine 引擎
- [x] 创建 `engine/__init__.py`
- [x] 实现 `engine/ops.py`
- [x] 实现 `engine/approval.py`
- [x] 实现 `engine/events.py`
- [x] 实现 `engine/handle.py`
- [x] 实现 `engine/prompts.py`
- [x] 实现 `engine/streaming.py`
- [x] 实现 `engine/turn_loop.py`
- [x] 实现 `engine/engine.py`
- [x] 打通最小闭环：用户消息 → 请求 → 流式事件 → 事件分发
- [x] 工具执行前接入 `ExecPolicyEngine`
- [x] 增加 approval required/resolved/sandbox denied engine events
- [x] thinking block 不再在 assistant message buffer 中丢失
- [x] 编写 mock LLM 的 engine 测试

### 阶段二完成条件
- [x] 具备最小可运行对话闭环
- [x] 支持流式文本事件
- [x] 支持最小工具调用链路

---

## 阶段三：工具生态

### 9. 全量工具实现

#### 文件系统
- [x] `read_file`
- [x] `write_file`
- [x] `edit_file`
- [x] `list_dir`

#### 搜索
- [x] `grep_files`
- [x] `file_search`

#### Shell
- [x] `exec_shell`
- [x] `exec_shell_cancel`
- [x] `exec_shell_wait`
- [x] `exec_shell_interact`
- [x] shell 结果封装

#### Git
- [x] `git_status`
- [x] `git_diff`
- [x] `git_log`
- [x] `git_show`
- [x] `git_blame`

#### Web
- [x] `web_search`
- [x] `fetch_url`
- [ ] `web_run`（当前源码中仍是 stub，本轮已从默认 registry 移除）
- [ ] `finance`（当前源码中仍是 stub，本轮已从默认 registry 移除）

#### GitHub
- [x] `github_issue_context`
- [x] `github_pr_context`
- [x] `github_comment`
- [x] `github_close`

#### 任务管理
- [x] `task_create`（内存兼容实现）
- [x] `task_list`（内存兼容实现）
- [x] `task_read`（内存兼容实现）
- [x] `task_cancel`（内存兼容实现）
- [ ] `task_gate_run` durable evidence 执行链（当前仍是内存 stub）
- [x] `pr_attempt_create`（内存兼容实现）
- [x] `pr_attempt_list`（内存兼容实现）
- [x] `pr_attempt_read`（内存兼容实现）
- [x] `pr_attempt_update`（内存兼容实现）
- [x] `pr_attempt_complete`（内存兼容实现）
- [x] `pr_attempt_cancel`（内存兼容实现）
- [ ] `task_shell_start`
- [ ] `task_shell_wait`
- [ ] `pr_attempt_record`
- [ ] `pr_attempt_preflight`

#### Sub-Agent
- [x] `agent_spawn`（内存兼容实现）
- [x] `agent_result`（内存兼容实现）
- [x] `agent_assign`（内存兼容实现）
- [x] `agent_wait`（内存兼容实现）
- [x] `agent_cancel`（内存兼容实现）
- [x] `agent_list`（内存兼容实现）
- [ ] 真实子代理 loop、并发上限、结果 mailbox

#### 自动化
- [x] `automation_create`（内存兼容实现）
- [x] `automation_list`（内存兼容实现）
- [x] `automation_read`（内存兼容实现）
- [x] `automation_update`（内存兼容实现）
- [x] `automation_pause`（内存兼容实现）
- [x] `automation_resume`（内存兼容实现）
- [x] `automation_delete`（内存兼容实现）
- [x] `automation_run`（内存兼容实现）
- [ ] 真实 cron/heartbeat 调度与 durable task 入队

#### Todo
- [x] `todo_write`
- [x] `todo_add`
- [x] `todo_update`
- [x] `todo_list`

#### 其他工具
- [x] `apply_patch`
- [x] `diagnostics`
- [x] `project_map`
- [x] `list_mcp_resources`
- [x] `list_mcp_resource_templates`
- [x] `read_mcp_resource`
- [x] `mcp_get_prompt`
- [ ] `run_tests`
- [ ] `note`
- [ ] `rlm_query`
- [ ] `remember`
- [ ] `revert_turn`
- [ ] `validate_data`

### 阶段三完成条件
- [ ] 74 个工具全部有定义与注册
- [x] 默认 registry 仅注册真实可用或安全兼容工具，stub 工具不默认暴露
- [x] 核心工具具备测试覆盖
- [x] 工具导出顺序稳定

---

## 阶段四：MCP 与审批

### 10. MCP 集成
- [x] 创建 `mcp/__init__.py`
- [x] 实现 `mcp/config.py`
- [x] 实现 `mcp/client.py`
- [x] 实现 `mcp/encoding.py`
- [x] 实现 `mcp/loader.py`
- [x] 实现 `mcp/manager.py`
- [ ] 可选实现 `mcp/server.py`
- [x] 完成 stdio JSON-RPC 初始化握手
- [x] 完成工具发现、过滤、调用
- [x] 支持 `servers` / `mcpServers` config 读取
- [x] 支持 MCP resources/prompts helper 方法
- [ ] HTTP MCP transport（当前显式返回未实现）
- [x] 编写 MCP mock server 测试

### 11. 审批策略
- [x] 创建 `execpolicy/__init__.py`
- [x] 实现 `execpolicy/models.py`
- [x] 实现 `execpolicy/engine.py`
- [x] 实现 `execpolicy/sandbox.py`
- [x] 打通风险分级
- [x] 打通审批结果缓存
- [x] 打通 engine 工具执行前审批 gate
- [x] 审批拒绝时阻止工具执行并返回 tool error
- [x] 工作区路径边界测试
- [x] 编写审批测试

---

## 阶段五：TUI 界面

### 12. Textual App
- [x] 创建 `tui/__init__.py`
- [x] 实现 `tui/app.py`
- [x] 创建 `tui/screens/chat.py`
- [x] 创建 `tui/screens/config_ui.py`
- [x] 实现 `tui/widgets/composer.py`
- [x] 实现 `tui/widgets/transcript.py`
- [x] 实现 `tui/widgets/approval.py`
- [x] 实现 `tui/widgets/status_bar.py`
- [x] 实现 `tui/widgets/slash_menu.py`
- [x] 实现 `tui/widgets/tool_cell.py`
- [x] 实现 `tui/streaming.py`
- [x] 实现 `tui/history.py`
- [x] 打通 engine 事件到 UI 渲染
- [x] 完成基础交互测试

---

## 阶段六：高级特性

### 13. LSP 集成
- [x] 创建 `lsp/__init__.py`
- [x] 实现 `lsp/manager.py`
- [x] 实现 `lsp/client.py`
- [x] 实现 `lsp/diagnostics.py`
- [x] 打通懒启动与诊断注入
- [x] 编写 LSP 测试

### 14. Hooks 系统
- [x] 创建 `hooks/__init__.py`
- [x] 实现 `hooks/events.py`
- [x] 实现 `hooks/dispatcher.py`
- [x] 实现 `hooks/sinks.py`
- [x] 编写 hooks 测试

### 15. App Server
- [x] 创建 `app_server/__init__.py`
- [x] 实现 `app_server/server.py`
- [x] 实现 `app_server/routes.py`
- [x] 实现 `app_server/sse.py`
- [x] 编写 REST + SSE 测试

---

## 阶段七：集成与优化

### 16. 端到端测试
- [ ] 完整对话流程测试
- [ ] 工具执行集成测试
- [ ] MCP 集成测试
- [ ] 审批流程集成测试

### 17. 性能优化
- [ ] 流式延迟基准测试
- [ ] 工具并发测试
- [ ] 内存占用评估
- [ ] 前缀缓存稳定性验证

### 18. 文档与交付
- [ ] README 补全
- [ ] API 文档
- [ ] 配置文档
- [ ] 工具文档
- [ ] CI/CD 配置

---

## 本轮执行记录

### 已完成
- [x] 建立项目根目录与 `src/` 结构
- [x] 写入 `pyproject.toml`
- [x] 写入 `config.example.toml`
- [x] 实现 CLI 最小入口
- [x] 实现配置系统基础加载链
- [x] 实现密钥解析基础逻辑
- [x] 实现 SQLite 基础持久化
- [x] 补充配置/密钥/状态层测试
- [x] 在项目内创建虚拟环境并通过测试
- [x] 完成阶段一全部事项并通过 `make check`
- [x] 建立 `protocol/`、`client/`、`engine/` 目录骨架
- [x] 实现 protocol 基础模型与测试
- [x] 实现 client 抽象层、SSE 解析、DeepSeek 适配与测试
- [x] 实现 engine 最小闭环与测试
- [x] 实现 tools 基础抽象、注册表、文件工具与测试
- [x] 打通 engine → ToolRegistry → tool result → follow-up request 最小链路
- [x] 实现 `search_tools.py` 与搜索工具测试
- [x] 实现 `shell_tools.py`（含 `exec_shell_interact`）与 shell 工具测试
- [x] 完成 shell 结果封装并校验结构化元数据
- [x] 补充 ToolRegistry 对搜索与 shell 工具的集成测试
- [x] 实现 `git_tools.py` 与 git 工具测试
- [x] 实现 `fetch_url` 与隔离 HTTP 测试
- [x] 实现 `web_search` 与隔离 HTTP 解析测试
- [x] 实现 GitHub 上下文工具与 gh CLI 隔离测试
- [x] 实现 GitHub 写工具与 gh CLI 隔离测试
- [x] 再次通过 `make check`

### 紧接着执行
1. 进入阶段五：TUI 界面
2. 实现 `tui/app.py`、`tui/screens/chat.py`
3. 实现核心 widgets：composer、transcript、status_bar
4. 打通 engine 事件到 UI 渲染
