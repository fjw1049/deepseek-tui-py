# DeepSeek-TUI Python

基于 [DeepSeek-TUI](https://github.com/deepseek-ai/DeepSeek-TUI)（Rust）的 Python 行为复刻版 —— 一个功能完整的终端 AI Agent。

---

## 特性一览

| 领域 | 能力 |
|------|------|
| **对话引擎** | 流式输出、多轮推理、工具调用、容量守卫、自动压缩（Cycle/Seam） |
| **工具系统** | 70+ 内置工具 —— 文件、Shell、Git、GitHub、Web、任务、子代理、RLM、MCP |
| **Task / Subagent / RLM** | Rust 对齐：RLM client 注入、Flash 子模型、task 安全默认值、subagent mailbox、gate 持久化 |
| **TUI 界面** | 基于 Textual：Markdown 渲染、Diff 查看、命令面板、@file mention、子代理卡片 |
| **会话管理** | SQLite 持久化、多会话、fork/resume/checkpoint、自动恢复 |
| **安全管道** | ExecPolicy（4 级）+ CommandSafety + macOS sandbox-exec + 网络域名策略 |
| **计费可视** | 实时 prompt cache 命中率、$/¥ 双币累计、模型折扣自动识别 |
| **扩展集成** | MCP 客户端/服务器、LSP post-edit 诊断、Hooks 事件系统、Skills 技能市场 |
| **App Server** | FastAPI HTTP/SSE + stdio JSON-RPC，支持远程调用和多线程编排 |

---

## 快速开始

### 环境要求

- Python 3.10+
- macOS / Linux

### 安装

```bash
git clone https://github.com/fjw1049/deepseek-tui-py.git
cd deepseek-tui-py

# 推荐 uv（快速）
uv venv .venv --python 3.12
uv pip install -e ".[dev]"

# 或 pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

#### 精确版本复现（CI / 协作）

`requirements.lock` 是用本仓库 `.venv` 的 `uv pip freeze` 输出的精确快照，与 1323 个 parity 测试一一对应：

```bash
uv venv .venv --python 3.12
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  uv pip install -r requirements.lock
uv pip install -e .

# 验证
pytest tests -q   # 应该 1323 passed
```

依赖文件分工：

| 文件 | 用途 |
|------|------|
| `requirements.txt` | 仅 runtime，floor 版本 |
| `requirements-dev.txt` | runtime + dev（pytest/mypy/ruff） |
| `requirements.lock` | 全部精确版本（推荐 CI 使用） |

升级依赖后：`uv pip freeze | grep -v '^-e' > requirements.lock`

---

### 配置 API Key

所有运行时数据默认存储在项目根目录的 `./.deepseek/`（已加入 `.gitignore`），每个 clone 互相独立。

```bash
# 方式 1：环境变量（推荐，跨项目复用）
export DEEPSEEK_API_KEY=sk-your-key-here

# 方式 2：项目本地配置
mkdir -p .deepseek && cp config.example.toml .deepseek/config.toml

# 方式 3：本地 keyring
deepseek-tui login --provider deepseek --api-key sk-your-key-here
```

> **跨项目共享配置**：设置 `DEEPSEEK_HOME=~/.deepseek-shared` 可覆盖项目本地路径。

---

### 运行

**一键启动**（推荐）：

```bash
bash scripts/start-service.sh              # 增量 sync + 启动 TUI
bash scripts/start-service.sh --fresh      # 清空 .venv 重建
bash scripts/start-service.sh -- --help    # 透传参数给 deepseek-tui
```

**手动控制**：

```bash
uv sync && source .venv/bin/activate
deepseek-tui                               # 交互式 TUI
```

**常用命令**：

```bash
deepseek-tui                        # 交互式 TUI（默认）
deepseek-tui doctor                 # 健康检查
deepseek-tui -p "你好"              # 单次对话（stdout）
deepseek-tui serve --http --port 7878   # Workbench Runtime API (parity /v1)
deepseek-tui serve --port 8787          # Legacy App Server envelope
deepseek-tui serve --stdio          # stdio JSON-RPC（给上游 agent）
deepseek-tui mcp-server             # 作为 MCP Server 暴露工具
deepseek-tui resume <session-id>    # 恢复会话
deepseek-tui fork <session-id>      # 分叉会话
deepseek-tui auth status            # 查看登录态
```

---

## 测试

默认 CI / 本地快速验证（不含网络、不含 live marker）：

```bash
.venv/bin/python -m pytest tests -q
```

### RLM / Subagent / Task（build_0522）

| 套件 | 文件 | 说明 |
|------|------|------|
| Parity | `tests/test_rlm_subagent_task_parity.py` | 单元级 Rust 对齐（client 注入、auto_approve、mailbox 等） |
| Integration | `tests/test_rlm_subagent_task_integration.py` | Manager / Engine 接线（mock client） |
| Live 分模块 | `tests/test_live_rlm_subagent_task.py` | 真实 API：RLM、subagent executor、task executor、gate |
| Live 全链路 | `tests/test_live_full_workflow.py` | **一条自然语言 query**，模型主动调用 `task_create` → `agent_spawn` + `agent_result` → `rlm` |

Live 测试依赖项目 `.deepseek/config.toml` 中的 API Key，需显式启用 `-m live`：

```bash
# 分模块 live（约 1–2 分钟）
.venv/bin/python -m pytest tests/test_live_rlm_subagent_task.py -m live -v

# 全链路：自然 query 驱动 task + subagent + rlm（约 1.5 分钟）
.venv/bin/python -m pytest tests/test_live_full_workflow.py -m live -v

# 一次跑齐
.venv/bin/python -m pytest tests/test_live_full_workflow.py tests/test_live_rlm_subagent_task.py -m live -v
```

其他 live 套件（Hooks / MCP）见 `tests/test_live_today_integration.py`、`tests/test_live_api.py`。

---

## 项目结构

```
src/deepseek_tui/
├── __init__.py          # 包版本声明
├── __main__.py          # 入口：调用 cli/app()
├── logging_setup.py     # 按小时轮转日志（~/.deepseek/logs/）+ trace 关联
├── trace.py             # per-turn / per-tool-call trace ID 上下文变量
├── utils.py             # 共享工具函数（原子 JSON 写入等）
│
├── config/              # 配置系统 + Provider 注册表
│   ├── loader.py            # 多层配置加载（TOML/YAML/env）
│   ├── models.py            # Config Pydantic 数据模型 + ConfigError 异常族
│   ├── paths.py             # 路径常量（~/.deepseek/ 用户级 / 项目级）
│   ├── env_mapping.py       # DEEPSEEK_* 环境变量 → 配置字段映射
│   └── provider_registry.py # Provider 枚举、模型别名、上下文窗口、压缩阈值
│
├── secrets/             # 密钥管理（keyring → env → None 优先级）
│   ├── __init__.py          # SecretsError/InsecurePermissionsError + 公共 re-export
│   ├── facade.py            # 高层 Secrets 门面（keyring + env fallback）
│   ├── store.py             # KeyringStore 抽象 + Default/InMemory/File 实现
│   ├── manager.py           # 密钥 CRUD 管理
│   ├── file_store.py        # 文件系统密钥存储（headless 模式）
│   └── env_map.py           # provider → 环境变量名映射
│
├── protocol/            # 消息协议（IPC 线格式，镜像 Rust protocol crate）
│   ├── __init__.py          # ErrorKind/ErrorEnvelope + 公共 re-export
│   ├── messages.py          # Role 枚举、TextBlock、Message 等会话消息类型
│   ├── requests.py          # MessageRequest（发送给 LLM 的请求体）
│   ├── responses.py         # LLM 响应数据模型
│   ├── events.py            # 21 种 IPC EventFrame 变体（turn_complete, response_delta…）
│   ├── approval.py          # AskForApproval / ReviewDecision / NetworkPolicyAmendment
│   ├── ipc.py               # Envelope<T> 泛型包装（request_id / thread_id）
│   ├── prompt.py            # PromptRequest / PromptResponse RPC 对
│   ├── threads.py           # Thread 元数据 + 线程生命周期请求/响应类型
│   ├── tool_payload.py      # ToolPayload / ToolOutput 判别联合（function/custom/shell/mcp）
│   └── mcp_lifecycle.py     # MCP 服务器启动生命周期信号
│
├── client/              # LLM 客户端（流式 SSE + 重试）
│   ├── base.py              # 抽象 LLMClient 基类 + RetryConfig（指数退避）
│   ├── deepseek.py          # DeepSeek 原生 API 客户端 + OpenAICompatClient
│   ├── streaming.py         # SSE 流解析 + delta 聚合
│   ├── chat_messages.py     # 会话消息序列化（Message → API wire format）
│   └── pricing.py           # Token 计费 / 成本估算
│
├── engine/              # 核心引擎（turn loop + 上下文管理 + 工具调度）
│   ├── engine.py            # Engine 主体：会话状态机 + 生命周期
│   ├── turn_loop.py         # Turn loop：LLM 调用 → 工具执行 → 循环
│   ├── handle.py            # EngineHandle + Ops + ApprovalHandler（Engine 通信层）
│   ├── events.py            # EngineEvent 类型定义
│   ├── streaming.py         # 引擎侧流式响应处理
│   ├── context.py           # 上下文预算 + token 估算 + 消息截断 + 窗口计算
│   ├── capacity.py          # 容量感知守卫：决定何时介入（刷新/回放）
│   ├── capacity_flow.py     # 三个检查点入口，路由容量观测到守卫动作（port of Rust）
│   ├── compaction.py        # 消息压缩 + LLM 摘要（长上下文降级）
│   ├── dispatch.py          # 工具调度 + audit 日志 + 路由 tool_call → 执行器
│   ├── executors.py         # Task / SubAgent 真实执行器（Engine turn loop）
│   ├── tool_catalog.py      # 延迟加载工具目录 + 搜索 + 缺失工具建议
│   ├── tool_parser.py       # 解析文本格式 tool_call + 流式 JSON 片段重组
│   ├── arg_repair.py        # LLM 输出的工具参数自动修复（JSON 容错）
│   ├── cycle_manager.py     # Cycle 归档 + briefing（多轮压缩）
│   ├── seam_manager.py      # Seam 层级摘要（append-only, prefix cache 友好）
│   ├── working_set.py       # 活跃文件追踪集合
│   ├── project_context.py   # 项目级上下文注入（CLAUDE.md / .deepseek/）
│   └── prompts.py           # 引擎内 prompt 组装辅助
│
├── tools/               # 工具实现（70+ 内置工具）
│   ├── base.py              # ToolSpec 抽象基类 / ToolCapability / ToolResult / ToolError
│   ├── registry.py          # 工具注册表（name → ToolSpec 映射 + 分类）
│   ├── runtime.py           # ToolRuntime：工具生命周期管理 + 并发执行上下文
│   ├── context.py           # ToolContext：每次工具调用的运行时上下文
│   ├── builder.py           # ToolSpec 声明式构建器
│   ├── encoding.py          # 工具名编解码（满足 API [A-Za-z0-9_-] 约束）
│   ├── schema_sanitize.py   # JSON Schema 清洗（移除不兼容字段）
│   ├── _validators.py       # 共享参数校验器
│   ├── file_tools.py        # 文件读写/编辑/搜索工具
│   ├── shell_tools.py       # Shell 命令执行工具（Bash/Zsh）
│   ├── git_tools.py         # Git 操作工具（status/diff/commit/log…）
│   ├── github_tools.py      # GitHub API 工具（PR/Issue/Review）
│   ├── search_tools.py      # 代码搜索工具（Glob/Grep/ripgrep）
│   ├── web_tools.py         # Web 工具（fetch/search）
│   ├── knowledge_tools.py   # 知识库 / 记忆工具
│   ├── task_tools.py        # 任务管理工具（Task CRUD + shell/gate）
│   ├── task_manager.py      # TaskManager 状态机
│   ├── todo_tools.py        # Todo 列表持久化工具
│   ├── mcp_tools.py         # MCP 工具桥接（转发至 McpManager）
│   ├── subagent_tools.py    # 子代理工具（Agent spawn/send/wait/cancel）
│   ├── automation_tools.py  # 自动化任务工具（cron/schedule CRUD）
│   ├── automation_manager.py # 自动化任务生命周期管理
│   ├── automation_scheduler.py # 定时调度器
│   ├── validation_tools.py  # ValidateData / TestRunner / RevertTurn
│   ├── utility_tools.py     # ApplyPatch + 文件操作工具集合
│   ├── patch_engine.py      # Unified-diff 补丁引擎（fuzzy hunk 匹配, port of Rust）
│   ├── parallel_tool.py     # multi_tool_use.parallel 并行工具分发
│   ├── user_input_tool.py   # RequestUserInput 哨兵（暂停执行等待用户输入）
│   ├── rlm/                 # RLM 递归语言模型子代理
│   │   ├── repl.py              # 进程内 Python REPL（chunk_context / chunk_coverage）
│   │   ├── prompt.py            # RLM 系统提示词（严格契约 + chunk 辅助函数说明）
│   │   ├── tool.py              # rlm 工具（Engine.create 注入 client，子模型固定 Flash）
│   │   └── turn.py              # RLM turn 执行循环 + 子 LLM token 累计
│   └── subagent/            # 子代理基础设施
│       ├── mailbox.py           # 结构化事件流（tool_call / token_usage / lifecycle）
│       └── manager.py           # 子代理管理器（spawn / cancel 级联 / fork_context）
│
├── execpolicy/          # 执行策略（命令安全 + 工具审批）
│   ├── policy.py            # Policy 引擎：首 token 路由 → 规则匹配 → Decision
│   ├── engine.py            # ExecPolicyEngine：tool call 对策略规则求值
│   ├── rule.py              # PatternToken / PrefixPattern / PrefixRule 数据模型
│   ├── rules.py             # 内置规则集定义
│   ├── parser.py            # Mini-Starlark 子集解析器（prefix_rule(...)）
│   ├── matcher.py           # 命令归一化 + 通配符→正则 + heredoc 剥离
│   ├── decision.py          # Decision 枚举（Allow / Prompt / Forbidden）
│   ├── command_safety.py    # 危险命令模式检测 + SafetyLevel 分级
│   ├── models.py            # RiskLevel / ToolCategory / PolicyRule / ApprovalRequest
│   ├── approval_cache.py    # 审批缓存（指纹键控 + 会话持久化）
│   ├── amend.py             # 策略文件原子追加（文件锁 advisory）
│   ├── sandbox.py           # macOS sandbox-exec 沙箱执行器（Seatbelt profile）
│   └── errors.py            # ExecPolicyError / AmendError
│
├── network/             # 网络策略（出站 HTTP 域名级 allow/deny）
│   └── policy.py            # NetworkPolicy：deny-wins / 会话缓存 / URL 主机名解析
│
├── state/               # SQLite 持久化
│   ├── database.py          # aiosqlite 连接包装 + schema migration
│   ├── schema.py            # DDL（sessions / threads / schema_migrations）
│   └── session_manager.py   # SessionManager（会话 CRUD + 恢复）
│
├── tui/                 # Textual TUI 界面
│   ├── app.py               # 主应用（Textual App 子类）
│   ├── approval_handler.py  # TUI 侧审批交互处理
│   ├── backtrack.py         # /undo 回溯逻辑
│   ├── clipboard.py         # 剪贴板集成
│   ├── frame_rate_limiter.py # 渲染帧率限制器
│   ├── notifications.py     # 桌面通知集成
│   ├── osc8.py              # OSC 8 超链接转义序列
│   ├── plan_prompt.py       # Plan 模式提示组装
│   ├── commands/            # 斜杠命令系统
│   │   └── handlers.py         # /help, /clear, /compact, /undo 等命令处理
│   ├── screens/             # 全屏 Screen
│   │   └── onboarding.py       # 首次启动引导界面
│   └── widgets/             # TUI 组件
│       ├── composer.py          # 输入编辑器（多行 + 文件 mention）
│       ├── transcript.py        # 对话记录渲染
│       ├── sidebar.py           # 会话列表侧栏
│       ├── info_sidebar.py      # 上下文信息面板
│       ├── status_bar.py        # 底部状态栏（token/cost/model）
│       ├── tool_cell.py         # 工具调用渲染单元
│       ├── diff_viewer.py       # Diff 查看器
│       ├── help_panel.py        # 帮助面板
│       ├── pickers.py           # 模型/Profile 选择器
│       ├── command_palette.py   # 命令面板（Ctrl+K）
│       ├── slash_menu.py        # 斜杠命令补全菜单
│       ├── context_inspector.py # 上下文检查器
│       ├── agent_card.py        # 子代理状态卡片
│       ├── file_mention.py      # @file mention 自动补全
│       ├── approval.py          # 审批确认对话框
│       └── pager.py             # 长文本分页查看器
│
├── mcp/                 # MCP 客户端（Model Context Protocol）
│   ├── client.py            # JSON-RPC 2.0 MCP 客户端（stdio / SSE/HTTP）
│   ├── manager.py           # McpManager：多服务器连接 + 工具名路由
│   ├── config.py            # McpServerConfig + ToolFilter 配置模型
│   ├── loader.py            # 从 JSON 文件加载 MCP 服务器配置
│   ├── encoding.py          # mcp__<server>__<tool> 限定名编解码（SHA-256 截断）
│   ├── server.py            # 本项目作为 MCP Server 的暴露层
│   └── transport.py         # StdioTransport / SseTransport 实现
│
├── lsp/                 # LSP 集成（post-edit 诊断收集）
│   ├── client.py            # LspClient + JSON-RPC transport
│   ├── manager.py           # LspManager：按语言懒启动 + 诊断收集
│   ├── registry.py          # Language 枚举 + 扩展名→LSP 命令映射
│   ├── diagnostics.py       # Diagnostic 模型 + Severity + 格式化渲染
│   └── hooks.py             # 从工具输入中提取编辑路径以触发诊断
│
├── hooks/               # Hooks 事件系统
│   ├── dispatcher.py        # HookDispatcher：广播 HookEvent 到注册 Sink
│   ├── events.py            # HookEvent 定义（ResponseStart/Delta/End, ToolLifecycle…）
│   └── sinks.py             # 三种 Sink：Stdout JSON lines / JSONL 文件 / Webhook POST
│
├── skills/              # 技能系统
│   ├── __init__.py          # SkillRegistry + Skill 数据类（发现 SKILL.md 目录）
│   ├── install.py           # 技能安装（GitHub / 本地 tarball + 安全加固）
│   └── system.py            # 内置系统技能初始化
│
├── app_server/          # FastAPI HTTP 服务 + stdio JSON-RPC
│   ├── server.py            # uvicorn HTTP / stdio JSON-RPC 入口
│   ├── routes.py            # 全部 HTTP 端点（healthz / thread CRUD / turn / compact / SSE）
│   ├── runtime.py           # AppRuntime：中央编排器（线程存储/工具/MCP/Hooks）
│   ├── runtime_threads.py   # 持久化 RuntimeThreadStore + 线程/轮次数据模型
│   ├── thread_manager.py    # RuntimeThreadManager：引擎生命周期 + LRU 驱逐 + 恢复
│   ├── engine_bridge.py     # EngineEvent → SSE dict 转换桥
│   ├── broadcast.py         # AsyncBroadcast 多消费者频道（per-subscriber Queue）
│   └── sse.py               # SSE 帧格式化工具
│
├── cli/                 # Typer CLI
│   └── app.py              # Typer 应用定义 + 子命令注册
│
└── prompts/             # 分层 Prompt 模板系统
    ├── __init__.py          # 模板加载 + 组合（base → personality → mode → approval）
    ├── base.md / base.txt   # 基础系统提示
    ├── normal.txt           # 正常模式增量
    ├── agent.txt            # Agent 模式增量
    ├── plan.txt             # Plan 模式增量
    ├── yolo.txt             # YOLO 模式增量
    ├── compact.md           # 压缩摘要提示
    ├── cycle_handoff.md     # Cycle 交接提示
    ├── subagent_output_format.md # 子代理输出格式约束
    ├── personalities/       # 人格模板目录
    ├── modes/               # 模式定义目录
    └── approvals/           # 审批策略模板目录
```

---

## 工具系统

共 **70+ 工具**，按能力域分组：

### 文件操作

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件内容（支持行范围） |
| `write_file` | 创建/覆写文件 |
| `edit_file` | 精准行编辑（search/replace） |
| `list_dir` | 列出目录内容 |
| `apply_patch` | Unified-diff 补丁应用（fuzzy matching） |

### 搜索

| 工具 | 说明 |
|------|------|
| `grep_files` | 正则内容搜索（ripgrep） |
| `file_search` | 文件名模糊搜索 |
| `project_map` | 项目结构概览 |

### Shell

| 工具 | 说明 |
|------|------|
| `exec_shell` | 执行 Shell 命令 |
| `exec_shell_wait` | 等待后台命令完成 |
| `exec_shell_cancel` | 取消运行中命令 |
| `exec_shell_interact` | 向运行中命令发送输入 |

### Git

| 工具 | 说明 |
|------|------|
| `git_status` / `git_diff` / `git_log` / `git_show` / `git_blame` | 完整 Git 只读操作集 |

### Web & GitHub

| 工具 | 说明 |
|------|------|
| `web_search` | 网络搜索 |
| `fetch_url` | 抓取 URL 内容 |
| `github_issue_context` / `github_pr_context` | 拉取 Issue/PR 详情 |
| `github_comment` / `github_close` | Issue/PR 交互 |
| `pr_attempt_*` | PR 预检/提交/回顾 |

### 任务 & 子代理 & RLM

| 工具 | 说明 |
|------|------|
| `task_create` / `task_list` / `task_read` / `task_cancel` |  durable 后台任务（`auto_approve` 默认 **false**） |
| `task_shell_start` / `task_shell_wait` / `task_gate_run` | 任务内 Shell / 验证 gate（gate 经 `record_tool_metadata` 持久化） |
| `agent_spawn` / `agent_send` / `agent_wait` / `agent_cancel` | 子代理生命周期（`fork_context`、parent cancel 级联、mailbox 事件） |
| `agent_list` / `agent_result` / `agent_resume` / `close_agent` | 子代理状态管理（`close_agent` 为 deprecated alias → `agent_cancel`） |
| `delegate_to_agent` | 一键委派子代理 |
| `rlm` | 长上下文 map-reduce（`file_path` 优先；子 LLM 固定 `deepseek-v4-flash`；REPL 内 `chunk_context()` / `chunk_coverage()`） |

任务工具统一支持 `task_id` / `id` 参数，且在 task executor 内可通过 `active_task_id` 省略。

### 知识 & 记忆

| 工具 | 说明 |
|------|------|
| `remember` / `note` | 持久化知识条目 |
| `recall_archive` | 回溯归档记忆 |
| `update_plan` | 更新执行计划 |
| `review` | 代码/方案审查 |
| `skill_load` | 动态加载技能 |
| `rlm` | RLM 递归推理（见上表；`rlm_query` 为历史别名） |

### 自动化

| 工具 | 说明 |
|------|------|
| `automation_create` / `list` / `read` / `update` / `delete` | 定时任务 CRUD |
| `automation_run` / `pause` / `resume` | 任务执行控制 |

### MCP 桥接

| 工具 | 说明 |
|------|------|
| `mcp__<server>__<tool>` | 动态代理外部 MCP 工具 |
| `list_mcp_resources` / `read_mcp_resource` | MCP 资源发现 |
| `list_mcp_resource_templates` / `mcp_get_prompt` | MCP 模板/Prompt |

### 其他

| 工具 | 说明 |
|------|------|
| `diagnostics` | LSP 诊断获取 |
| `todo_list` / `todo_add` / `todo_write` / `todo_update` | Todo 管理 |
| `validate_data` / `run_tests` / `revert_turn` | 验证与回退 |
| `request_user_input` | 向用户提问 |
| `multi_tool_use.parallel` | 并行工具批量调用 |

---

## 配置

配置文件位于 `.deepseek/config.toml`：

```toml
provider = "deepseek"
model = "deepseek-v4-pro"

[providers.deepseek]
base_url = "https://api.deepseek.com"
api_key = "sk-your-key-here"
timeout = 120

[ui]
color_scheme = "default"
show_thinking = true

[state]
database_path = ".deepseek/state.db"
autosave = true
```

---

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                    CLI / TUI / App Server                │
├─────────────────────────────────────────────────────────┤
│                         Engine                          │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │Turn Loop│  │ Context  │  │ Capacity │  │ Seam/  │  │
│  │         │←→│ Manager  │←→│  Guard   │←→│ Cycle  │  │
│  └────┬────┘  └──────────┘  └──────────┘  └────────┘  │
│       │                                                 │
│  ┌────▼─────────────────────────────────────────────┐   │
│  │              Tool Dispatch + Executors            │   │
│  └──┬──────┬──────┬──────┬──────┬──────┬──────┬─┘   │
├─────┼──────┼──────┼──────┼──────┼──────┼──────┼─────┤
│  Shell  File   Git   Web  Agent  RLM   MCP          │
│                                              ↕        │
│                                         External      │
│                                         MCP Servers   │
├─────────────────────────────────────────────────────────┤
│  ExecPolicy │ Network Policy │ Sandbox │ LSP │ Hooks  │
├─────────────────────────────────────────────────────────┤
│  Client (SSE Stream) │ State (SQLite) │ Secrets       │
└─────────────────────────────────────────────────────────┘
```

---

## 从旧版 `~/.deepseek/` 迁移

```bash
cp -r ~/.deepseek/config.toml ./.deepseek/
cp -r ~/.deepseek/sessions   ./.deepseek/
cp -r ~/.deepseek/skills     ./.deepseek/
```

---

## 许可证

MIT License
