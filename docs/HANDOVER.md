# DeepSeek-TUI Python 重构 — 接手指南 / HANDOVER

> 本文档是为**跨平台、跨对话、跨 AI 工具**继续这个项目而写的。读完这一份你就能接手。
>
> 最后更新：P2 审核报告修复 — fake_wrapper + snapshot undo + skill update + MCP server + web_run + composer 增强（2026-05-10）。

---

## 一、项目是什么

**源**：`docs/DeepSeek-TUI-main/`——一个 Rust 写的终端 AI Agent，大约 **161,000 行 Rust**，14 个 crates，包含 TUI、LLM client、engine、74 个工具、MCP/LSP/Hooks/App Server、49 个 slash 命令等。

**目标**：用 **Python** 做**百分百行为复刻**（架构和 UI 允许等价替换，但语义/行为必须一致）。

**仓库**：`git@github.com:fjw1049/deepseek-tui-py.git`

**关键约束**（这些是用户明确拍板的决策，接手时别动）：

| 决策 | 选择 |
|---|---|
| TUI 框架 | Textual 替代 ratatui，按功能行为等价 |
| 沙箱 | macOS 本地 + 命令黑名单 + cwd 边界 + env 清洗；暂不 Docker |
| 子代理并发 | `asyncio.Task` + child cancellation token（2026-05-07 翻案：Rust 用 tokio 协程，LLM 调用 IO bound，GIL 非瓶颈；multiprocessing 要重建 DeepSeekClient/ToolRegistry/ToolContext，工作量涨 2× 且 parity 测试都要改） |
| App Server HTTP | FastAPI |
| prompt | 照搬英文原文 |
| 协议二进制兼容 Rust | **不需要**（独立演进）—— 但 Stage 1.4 还是把 JSON shape 对齐了，因为这对多工具间接入更友好 |
| Rust 原项目 | 保留作 parity 参考基线 |
| 开发平台 | macOS 本地；跳过 Linux Landlock / Windows AppContainer |
| CLI binary | `deepseek-tui`（避免与 Rust `deepseek` 冲突） |

---

## 二、项目当前状态（2026-05-07）

### 已完成

| Stage | Commit | 核心产出 | 测试增量 |
|---|---|---|---:|
| 0 | `b9ab4c9` | git init + venv + ruff + parity 脚手架 | 99 passed |
| 1.1 | `c15acc3` | DeepSeek tool-name codec（可逆编码 + bare hex 容错） | +30 |
| 1.2 | `21d9ebd` | secrets 优先级反转 keyring→env→config + NVIDIA 别名链 + FileKeyringStore | +22 |
| 1.3 | `7a42e8e` | ToolRegistry 16 个方法补齐 + ApprovalRequirement + cache_control | +22 |
| 1.4 | `a7d3b82` | protocol IPC：Envelope/EventFrame×21/ThreadRequest×10/AppRequest×7/ToolPayload/ReviewDecision 等，Rust JSON parity | +72 |
| 1.5 | `8df5331` | provider_registry：ApiProvider×7 / ProviderKind×5 / ProviderCapability / context_window 含 NNNk hint | +77 |
| 2.1 | `dd78a8f` | engine/turn_loop 完整化（1,500 行）+ context checkpoint + tool_setup + capacity 状态机 | +13 |
| 2.2 | `afa2da4` | engine/capacity 容量控制系统（~750 行）+ GuardrailAction + RiskBand + cooldown | +17 |
| 2.3 | `500c4b4` | engine/compaction 消息汇总（~450 行）+ working_set 去重 + 智能 pin + LLM 总结 | +23 |
| 2.4 | `fd8ac3c` | engine/tool_parser 文本工具解析 + 流片段重组（~470 行）+ 5 种格式 + 智能 fallback | +25 |
| 2.5 | `f5fa794` | execpolicy 集成：Policy 绑定 ToolContext + exec_shell Decision 检查（FORBIDDEN/PROMPT） | +0 |
| 2.6 | `b3b0d83` | command_safety 分析：SafetyLevel×4 + COMMAND_ARITY 163 前缀 + 11 级检查管道 + 危险模式检测 | +24 |
| 3.1 | `c8c72e1` | durable Task 系统：TaskManager（~700 行）+ JSON 文件持久化 + 重启恢复（Running→Queued）+ 11 工具接通 | +33 |
| 3.2 | `3cbf9a9` | Sub-agent runtime：SubAgentManager（~600 行）+ Mailbox（9 种消息 + 单调 seq）+ asyncio.Task 调度 + 重启恢复（Running→Interrupted）+ 10 工具接通 | +42 |
| 3.3 | `7456887` | apply_patch 原生实现：patch_engine.py（~400 行）+ MAX_FUZZ=50 模糊匹配 + 累积偏移 + create/delete via /dev/null + 重写 ApplyPatchTool 不再外调 `patch` 命令 | +27 |
| 3.4 | `7456887` | PTY shell：stdlib `pty.openpty()` + `os.fork()` 模式 + exec_shell `pty=true` 参数 + Wait/Interact/Cancel 兼容 PTY 句柄 + 解除 task_shell_start/wait 空壳（artifacts 记录到 TaskRecord） | +6 (PTY) +2 (task shell) |
| 3-int | `dca3816` | **集成**：tasks feature flag + builder 注册 53 工具 + `create_tool_runtime`/`ToolRuntime` 一站式装配 + `Engine.create()` 工厂方法 | +7 |
| 4.1 | `6f7c630` | **App Server**：FastAPI + uvicorn 7 路由（healthz/thread/app/prompt/tool/jobs/mcp/startup）+ AppRuntime 单例共享 + ThreadStore（内存）+ 更新后的 stdio JSON-RPC 走同一 AppRuntime + `deepseek-tui serve` CLI 子命令 | +19 |
| 4.1.x | `23a5712` | **/prompt Rust parity**：handle_prompt emit ResponseStart/Delta/End 3-frame 序列 + /prompt/stream SSE 路由 + SseStream event: data: 双字段框 | +4 |
| 4.2 | `1ccd563` | **Hooks 集成**：HooksConfig + _build_hook_dispatcher + AppRuntime 挂 dispatcher + handle_prompt/stream_prompt/handle_tool/jobs 各自 emit 对应 HookEvent + 修 WebhookHookSink dead code + retry 200ms×N 对齐 Rust | +14 |
| 4.3 | `61a4901` | **MCP SSE/HTTP transport**：McpTransport 抽象（stdio + SSE）+ McpClient 重构走 transport + pending-id map 并发支持 + ToolRuntime 挂 McpManager + Config 自动加载 mcp.json + AppRuntime.mcp_startup 真实 per-server 状态 | +12 |
| 4.4 | `22438d2` | **LSP post-edit hook 接通 engine**：edited_paths_for_tool / parse_patch_paths + Config.lsp + ToolRuntime 挂 LspManager + Engine.pending_lsp_blocks + _run_post_edit_lsp_hook + flush 注入 synthetic user message | +22 |
| 4.1.nn | `234dbe9` | **/prompt/stream 接真实 Engine**：engine_event_to_sse 桥接 12 种 EngineEvent + AppRuntime.stream_prompt 可注入 LLMClient → 驱动 Engine → 产生真实 SSE 事件流；含真实 DeepSeek API 集成测（config.toml api_key 自动 opt-in） | +9 |
| 3.next.1 | `1d97997` | **approval cache 指纹**：ApprovalKey/Cache/Status + build_approval_key（patch: 路径 hash / shell: classify_command / net: host / tool:\*）+ Engine 集成（session grant 绕过 handler）+ classify_command 修正 Rust parity（剥 flags；未匹配返 positional[0]） | +17 |
| 5.prompts | — | **17 个 prompt 模板**：从 Rust `crates/tui/src/prompts/` 复制 17 文件到 `src/deepseek_tui/prompts/` + `__init__.py` 加载器（compose_prompt 4 层组合）+ `engine/prompts.py` 接入真实模板（含 handoff / working_set / context management） | +32 |
| 5.1 | — | **CLI 22 子命令**：typer 重写 `cli/app.py`（~850 行），P0 子命令可直接运行，P1 子命令有参数骨架 + exit(1) 提示 | +31 |
| 5.2 | — | **Slash 命令 dispatcher**：`tui/commands/` 52 注册 + 22 P0 handlers + 更新 slash_menu 从注册表驱动 | +28 |
| 5.3 | — | **Skills 子系统**：`skills/` 包（Skill model + SkillRegistry + discover + install + system bundled skills） | +26 |
| 6.1 | — | **Engine ↔ TUI 接线**：`_launch_tui` 构建真实 Client+Engine，`DeepSeekTUI` on_mount 启动 engine task，`_run_one_shot` 可用 | +16 |
| 6.4 | — | **审批门禁 UI**：`TUIApprovalHandler` 桥接 `ApprovalDialog` modal → asyncio.Future → Engine | +6 |
| 6.5 | — | **Slash 命令活化**：Composer 检测 `/` → SlashMenu，dispatch 应用结果到 transcript | +14 |
| 6.6 | — | **命令面板 + @file + StatusBar**：Ctrl+K CommandPalette，@file FileMention，StatusBar model/mode/tokens | +16 |
| 2-core | — | **Engine Core Modules**：`context.py`（tool result compaction + token estimation + working set）、`dispatch.py`（input parsing + parallel/plan policy + MCP policy）、`tool_execution.py`（audit logging + write lock）、`tool_catalog.py`（deferred loading + tool search + edit distance suggestions + code execution）+ engine.py 集成（special tool routing + compaction on results + audit emit） | +55 |
| bugfix-7 | — | **代码逻辑审核修复 7 项**：①executors.py 改用 Engine.run() 替代错误的 TurnLoop.run() 直调（P0 致命）②CLI resume/fork 传参修复（DeepSeekTUI 新增 resume_session_id/fork_session_id）③exec_shell PROMPT 决策改返回 ToolResult 而非 raise ToolError ④one-shot 模式显示工具调用进度（ToolCallEvent/ToolResultEvent）⑤CLI config set/unset 实现真实文件写入 ⑥httpx 连接池复用（持久 AsyncClient + Engine.shutdown 关闭）⑦TURN_MAX_OUTPUT_TOKENS 统一为 262,144（对齐 Rust context.rs:18） | +0 |
| p0-stream | — | **P0 流式健壮性 + 特殊工具**：①turn_loop transparent stream retry（空流 ≤2 次自动重试）②per-chunk 90s timeout + wall-clock 1800s guard + 10MB content guard ③streaming.py reasoning_content fallback（兼容 NIM `delta.reasoning`）④`is_reasoning_model()` 模型检测 ⑤`MultiToolUseParallelTool`（并发展开只读子调用）⑥`RequestUserInputTool`（验证 + UserInputRequiredEvent + asyncio.Future 阻塞）⑦Engine special routing（parallel/user_input 拦截） | +0 |
| p0-slash | — | **P0 slash 命令功能深度**：①`/save` 实现（session JSON 序列化 + metadata + 时间戳文件名）②`/load` 实现（JSON 反序列化 + Engine.session_messages 恢复 + Transcript 重建）③`/tokens` 实现（从 StatusBar 读取累积 token + 模型/消息数统计）④`/cost` 实现（基于 token 的成本估算 + DeepSeek 定价）— 对齐 Rust `commands/session.rs` + `commands/debug.rs` | +0 |
| p0-audit | — | **P0 审核报告修复 5 项**：①runtime.py executor 安全降级（无 API key 时回退 stub，修复 test_runtime_integration 挂死）②TUI _listen_events 处理 UserInputRequiredEvent（auto-select + resolve_user_input 解除死锁）③deepseek.py per-chunk idle timeout（asyncio.wait_for 包装每个 SSE chunk 读取，对齐 Rust STREAM_CHUNK_TIMEOUT_SECS=90）④parallel tool read-only 检查（非 read-only 工具拒绝并行）⑤parallel tool 递归自调用阻止 | +0 |
| p1-audit | — | **P1 审核报告修复 5 项**：①3 个缺失工具实现：ValidateDataTool（JSON/TOML 验证 + auto 检测）、RunTestsTool（pytest/cargo/npm 自动检测）、RevertTurnTool（git checkout 回滚）②Session 自动持久化（_auto_persist_session 写 current.json）③SubAgent 7 种 system prompt（SubAgentType.system_prompt() + _SUBAGENT_PROMPTS 字典）④Steer input 处理（EngineHandle._steer_queue + drain_steers + Engine 每轮循环开头注入 user message）⑤builder.py 注册 3 个新工具 | +0 |
| p2-audit | — | **P2 审核报告修复 8 项**：①fake_tool_wrapper 过滤（streaming.py: TOOL_CALL_START/END_MARKERS + FakeWrapperFilter + contains_fake_tool_wrapper + turn_loop 集成；buffer 保留 raw 以兼容 tool_parser 回退，emit 仅出干净文本）②per-tool snapshot undo（Engine.tool_snapshots + _take_pre_tool_snapshot for write_file/edit_file/apply_patch + undo_last_tool + /undo slash 接通）③RLM rlm_query 修复（错误的 client.events/models 导入修正为 protocol.responses，加 close 善后）④CLI 7 个 thread 子命令接通 SessionManager（list/read/resume/fork/archive/unarchive/set-name）⑤skill update（读 .installed-from → 重装 → 保留 trust 标记）⑥MCP server stdio 模式（mcp/server.py: initialize/tools/list/tools/call/resources/list JSON-RPC + CLI mcp-server 接通）⑦web_run Playwright 集成（缺依赖时返回安装提示而非沉默 stub）⑧Composer Ctrl+Enter 换行 + Ctrl+E 调 $EDITOR | +0 |
| p3-debt | — | **集成债 5 类清理（2026-05-10）**：①OSC8（85 LOC + 7 tests） ②Clipboard（150 LOC + 9 tests） ③Notifications（210 LOC + 13 tests） ④FrameRateLimiter（75 LOC + 6 tests，集成 _AssistantCell） ⑤Backtrack 状态机（140 LOC + 12 tests，Esc-Esc chord 接 app.action_esc_press） ⑥Plan prompt（165 LOC + 11 tests，cmd_plan slash 接通） ⑦Onboarding（190 LOC + 5 tests，_start_engine 接通） ⑧Composer paste（Textual native events.Paste + 抑制窗口 + 3 Pilot tests） ⑨App Server 6 长尾路由（/skills /tasks /tasks/{id} /tasks/{id}/cancel /apps/mcp/servers /apps/mcp/tools /workspace/status）⑩RLM in-process exec()（600 LOC + 26 tests：prompt + repl 沙箱 + turn loop + tool 适配器） ⑪AgentCard widget（290 LOC + 14 tests：DelegateCard/FanoutCard 状态机 + apply_to_*） ⑫Pager（310 LOC + 20 tests：PagerState 全键位 + ModalScreen） ⑬ContextInspector（225 LOC + 11 tests：build_context_inspector_text + cmd_context 接通） | +137 |
| pre-realapi-fix | — | **接入真实接口测试前置修复 P0×5 + P1×5（2026-05-10）**：①`max_tool_round_trips` 默认 3→100（对齐 Rust `EngineConfig::max_steps`，否则 4 轮以上工具调用直接被截断） ②`edit_file` schema 改用 Rust-parity `search`/`replace` 主键 + 兼容旧 `old_string`/`new_string` 别名（DeepSeek 模型见过的是 Rust schema） ③`Usage` 加 Pydantic v2 `AliasChoices`：`prompt_tokens`/`completion_tokens`/`prompt_cache_hit_tokens`/`prompt_cache_miss_tokens` + 嵌套 `completion_tokens_details.reasoning_tokens` 提取（之前被静默丢弃，`/tokens`/`/cost` 永远显示 0 cache hit） ④Engine 增 `default_reasoning_effort/temperature/top_p/extra_body` 字段，`Engine.create` 从 `Config.reasoning_effort` + `provider_cfg` 注入；`_run_conversation` 把它们写入 `MessageRequest`；`TurnLoop._run_turn_loop` 重建 `stream_request` 时也保留这些字段（之前推理模型不会启用 thinking） ⑤`DeepSeekClient` httpx `read=None`，让 per-chunk `asyncio.wait_for` 独占 SSE idle timing（之前 httpx 全局 90s read timeout 可能先于 90s per-chunk wait_for 触发，抛 `httpx.ReadTimeout` 走错误重试分支） ⑦`CancelRequestOp` 在 `engine.run` 中现 `self.handle.cancel_event.set()`，让任何直接 `send_op(CancelRequestOp(...))` 的调用方也能取消（之前 `continue` 静默丢弃） ⑨`grep_files` 改用 `re.compile`（之前是 `pattern in line` 子串），加 `ignore_case` 参数；invalid regex 抛 `ToolError` ⑩`exec_shell` 加 `timeout_ms` 参数（默认 120_000ms，max 600_000ms 对齐 Rust `shell.rs:1481-1482`），foreground 走 `asyncio.wait_for`，超时 terminate→kill→返回 `timed_out:true` 元数据 ⑪`DeepSeekClient` 新增 `_stream_with_pre_retry`：连接阶段 429/5xx + ConnectError/ReadError/RemoteProtocolError 重试 ≤3 次 +1s/2s/4s 退避（之前直接抛错） ⑫`DeepSeekTUI._apply_resume_or_fork`：`--resume <id>` / `--fork <id>` 从 `~/.deepseek/sessions/<id>.json`（或 `current.json` 兜底）反序列化 messages 灌回 `Engine.session_messages` + 重建 transcript（之前 ID 接收但完全不用） | +22 |
| pre-realapi-batch-2 | — | **P1/P2 第二批 6 项（2026-05-10）**：①`Engine` 实例化 `CycleConfig` + `SeamManager`（默认 disabled，`Config.cycle_enabled` / `Config.seam_enabled` 触发；`_maybe_advance_cycle` 在每轮开头检测 `should_advance_cycle` 阈值，超过时 `archive_cycle` 写 JSONL + 保留最近 8 条 messages 作为 seed —— 833 LOC 旧孤岛代码现至少有 1 个 wire-up 入口） ②`DeepSeekTUI` 加 8 个 Rust-parity 键位 binding：Ctrl+R/Ctrl+M/Ctrl+P/Tab/Ctrl+L/PageUp/PageDown/Ctrl+T，分别接 `SessionPicker` / `ModelPicker` / `FilePicker` / `cycle_mode` / `clear_transcript` / 滚动 / `toggle_thinking` ③App Server 同时挂载 `/` 和 `/v1/` 两个前缀（`server.py:build_fastapi_app` 调 `include_router` 两次） + 新增 `/threads/{id}/resume` `/threads/summary` `/threads/{id}/events/stream` 三条 Rust 缺位路由；`RuntimeThreadManager.resume_thread` 调 `_ensure_engine_loaded` 并 emit `thread.resumed`；`threads_summary` 返回 active/archived/mode 计数 ④`_should_include_reasoning` 拓宽匹配 6 个 Rust marker：`deepseek-r` / `reasoner` / `-reasoning` / `-thinking` / `deepseek-v3.2` / `deepseek-v4`；effort 处理 `off|disabled|none|false` 四个 Rust 关键字（之前只识别 `"off"`） ⑤Config 加 4 个新子模型：`NotificationsConfig`/`NetworkPolicyConfig`/`SkillsConfig`/`MemoryConfig` + 顶层 `tools_file: Path?`，确保用户从 Rust 二进制带过来的 TOML 不被 Pydantic 静默丢字段（行为暂时不读，留待下阶段消费） ⑥MCP server 加 `deepseek` 元工具（`McpStdioServer._deepseek_meta_call` 走 `DeepSeekClient.from_config` 一次性 LLM 调用）+ `resources/list` 输出 `session://*` URI 列表 + 新增 `resources/read` 处理 `session://` / `file://` schemes | +30 |
| logging-batch | — | **真实接口测试前置：rotating-file 日志系统（2026-05-10）**：①`src/deepseek_tui/trace.py`（~110 LOC）`contextvars` 两个 `ContextVar` (`turn_id` / `tool_id`) + `bind_turn` / `bind_tool` `contextmanager` + `TraceFilter` `logging.Filter` 注入 `trace_tag=[turn=ab12c34d tool=ee56f78g]` 字段 ②`src/deepseek_tui/logging_setup.py`（~250 LOC）`setup_logging(config, level_override, dir_override, console_override)`：`TimedRotatingFileHandler(when="H", backupCount=24)` + `_rotated_namer` 把 `deepseek.log.YYYY-MM-DD-HH` 重写成 `deepseek-YYYY-MM-DD-HH.log` + `httpx`/`urllib3`/`textual`/`aiosqlite`/`uvicorn.access` 自动 WARNING 静音 + 重复调用幂等（`_strip_previous_handlers` 清旧 handler）+ `current_log_path` / `tail_log` 两个 introspection helper ③`Config.logging` 子段（`LoggingConfig`：`enabled`/`level`/`dir`/`console`/`keep_hours`/`per_logger`），CLI 三个新 flag `--log-level` / `--log-dir` / `--log-console` 在 `main_callback` 内调 `setup_logging` ④Engine 埋点：`engine_run_start` / `turn_start`（user_text 截 200）/ `round_start`（每轮 + 工具数 + msg数）/ `compact_triggered` / `cycle_advance_triggered` + `cycle_archived` / `tool_call_start` 包 `bind_tool(tool_call_id)` / `tool_call_end` / `tool_call_error` / `approval_required` + `approval_decision` / `approval_cache_hit` / `engine_cancel_request` / `lsp_post_edit_hook` / `turn_complete`（usage 全字段：input/output/cache_hit/reasoning_tokens）⑤TurnLoop 埋点：`stream_start`（model + msg_count + tools_count + max_tokens + reasoning_effort）/ `sse_chunk`（DEBUG，每个 type） / `tool_call_received` / `stream_transparent_retry` / `stream_chunk_timeout` / `stream_wall_clock_exceeded` / `stream_content_exceeded` / `context_overflow` / `tool_parser_fallback` / `stream_done`（usage） ⑥DeepSeekClient 埋点：`http_request`（POST + url + body_bytes，**永不打 api_key/Authorization**）/ `http_response`（elapsed_ms）/ `pre_stream_retry` / `http_connect_error` / `http_client_close` ⑦Tools 埋点：`exec_shell_start` + `exec_shell_end` + `exec_shell_timeout`，`read_file` / `write_file` / `edit_file` + `edit_file_no_match` / `edit_file_not_unique`，`grep_files` + `grep_files_invalid_regex`，`file_search`，`apply_patch` + `apply_patch_changes` ⑧TUI 埋点：`tui_on_mount` / `tui_engine_create` + `tui_engine_started` / `tui_no_api_key` / `composer_submit` / `tui_quit` ⑨App Server 中间件：`http_access` 每个 HTTP 请求记 method/path/status/duration_ms（替代 `uvicorn.access`，对齐 trace_tag）+ `app_server_start` / `app_server_stop` ⑩`/log` slash 命令：`/log` 显示路径 / `/log tail [N]` 打最近 N 行（最多 5000）⑪19 个 parity 测试（`test_logging.py`）覆盖 trace / setup / overrides / handler 去重 / tail / noisy logger 静音 / `/log` slash 全分支 | +19 |
| audit-fix-0511 | — | **孤岛代码修复 + 链路接通（2026-05-11）**：①`tools/knowledge_tools.py::ReviewTool` 修复 3 处错误 import（`client.models`→`protocol.requests`、`client.events`→`protocol.responses`、`stream_chat_completion`→`stream_with_retry`）—— 调用即崩的 P0 硬 bug ②`app_server/thread_manager.py:552` import 路径修正（`client.deepseek_client`→`client.deepseek`）③`app_server/thread_manager.py::_ensure_engine_loaded` 改用 `Engine.create(config=self.config, ...)` 替代裸 `Engine(...)` 直构造，补全 tool_runtime + skills ④`app_server/server.py::build_fastapi_app` 初始化 `app.state.thread_manager = RuntimeThreadManager(...)` —— 接通 13 条 `/threads/*` durable routes（之前全部返回 `{"ok":false,"error":"runtime thread manager not configured"}`）⑤`engine/executors.py::_create_engine_for_execution` 加 `config` 参数 + 默认走 `ConfigLoader().load()` 而非空 `Config()`，子 agent/task 不再丢失父配置 ⑥`tools/builder.py` 注册 `RlmTool()`（name=`"rlm"`，完整沙箱版）与 `RlmQueryTool()`（name=`"rlm_query"`，简化版）并存 ⑦`engine/turn_loop.py` `max_tokens` 改为 `request.max_tokens or TURN_MAX_OUTPUT_TOKENS`，上层显式传值时不再被 262144 覆盖 ⑧`tui/app.py` `_current_mode` 实例变量 + `action_cycle_mode` 存值 + `on_composer_submitted` 非 agent 模式时在消息前缀注入 `[mode:xxx]`，mode 切换真正影响发出的 prompt ⑨P3 死代码清理：删 `state/{checkpoints,jobs,messages,offline_queue,sessions,threads}.py` 6 个孤岛 Store（~526 行）+ 删 `tui/screens/{chat,config_ui}.py` 2 个孤岛 Screen（~226 行）+ 删 `app_server/sse.py::SseStream` 类（30 行）+ 清 `state/__init__.py`/`app_server/__init__.py`/`tui/screens/__init__.py` 中对应 export | +0 |
| **累计** | | | **1323 passed, 4 skipped** |

### Stage 2.1–2.6 审核结论（2026-05-07）

> 审核视角：功能是否实现 × 是否接入系统 × 测试覆盖

| Stage | 功能实现 | 系统接入 | 测试 | 判定 |
|-------|---------|---------|------|------|
| 2.1 turn_loop | ⚠️ 骨架级（270+ 行 vs Rust 1,597 行） | ✅ Engine 调用 | ✅ 流式集成测 | 部分达标 |
| 2.2 capacity | ✅ 核心决策逻辑（326 行）+ capacity_flow.py（140 行） | ✅ Engine 3 checkpoint 调用 | ✅ 14+4 tests | **达标** |
| 2.3 compaction | ⚠️ ~21% Rust 规模（423+180 行） | ✅ Engine auto-compact + turn_loop emergency | ✅ 23+3 tests | **达标** |
| 2.4 tool_parser | ✅ ~96% Rust 规模（488 行） | ✅ turn_loop text fallback | ✅ 25+2 tests | **达标** |
| 2.5 execpolicy 集成 | ✅ Policy→ToolContext→ExecShell | ✅ shell 执行路径 | ✅ 40+ tests | **达标** |
| 2.6 command_safety | ✅ 4 级 + 11 步管道（405 行） | ✅ ExecShellTool heuristic fallback | ✅ 22+6 tests | **达标** |

**关键发现（2026-05-08 Stage 2-int 修复后更新）：**

1. ~~**3 个孤岛**（capacity / compaction / tool_parser）~~ → ✅ 已全部接入 Engine 运行时
2. ~~**tool_parser fallback 缺失**~~ → ✅ turn_loop StreamDone 后 fallback 已实现
3. ~~**context overflow recovery 空壳**~~ → ✅ 紧急 compaction 已接入
4. ~~**analyze_command() 是死代码**~~ → ✅ 已接入 ExecShellTool heuristic fallback
5. **COMMAND_ARITY 94 前缀**（非声称的 163）— 仍待补齐

**修复计划**：Stage 2-int 已于 2026-05-08 执行完毕（见 docs/BUG.txt）。剩余 COMMAND_ARITY 补齐见集成债清单。

### 五阶段缺口审核（`docs/AUDIT/`）

五份详尽审核 + 一份 SUMMARY + 一份 Codex vs Claude 差异对比，2,382 行。**接手时必读 `SUMMARY.md` 第七节（Stage 0–7 路线图）**。

### make check

```
make check  # = ruff + mypy + pytest
# 全绿：ruff / mypy 0 errors，pytest 322 passed, 2 skipped
```

### 关键已修 bug

1. `.venv/bin/python` 曾指向另一台机器的 `/Users/fjw/miniconda3/...`——已用 `/opt/homebrew/bin/python3.12` 重建。
2. ruff 16 项错误（未用 import / async 测试误调 `pathlib`）——已清零。
3. 密钥优先级反了（env 优先于 keyring，违反 Rust 安全规则）。
4. Tool name 不可逆（`multi_tool_use.parallel` 会被毁成 `multi_tool_use_parallel`）。

---

## 三、接下来要做什么（路线图）

按 `docs/AUDIT/SUMMARY.md` 第七节，剩余 Stage 2–7，合计 29–42 周（一名全职）。

### Stage 2（4–6 周）：engine 核心 + execpolicy

**P0 任务**（按顺序）：

1. `engine/turn_loop.py` 从 83 行 → ~1,500 行
   - **读** `crates/tui/src/core/engine/turn_loop.rs`（1,597 行）
   - 事件循环、tool polling、approval gate、capacity checkpoints
2. `engine/capacity.py` 新建 ~750 行
   - **读** `crates/tui/src/core/capacity.rs`（784）+ `capacity_flow.rs`（975）
   - token / step / cost / subagent budget + risk band + GuardrailAction
3. `engine/compaction.py` 新建 ~1,800 行
   - **读** `crates/tui/src/compaction.rs`（2,008 行）
   - 消息汇总 + working_set 去重 + cache-breakpoint
4. `engine/tool_parser.py` 新建
   - **读** `crates/tui/src/core/tool_parser.rs`（510）
   - 流式工具调用片段重组
5. `execpolicy/` 整套重写
   - **读** `crates/tui/src/execpolicy/{parser,matcher,policy,rules,amend,rule,decision,error}.rs`（~1,286 行）
6. `execpolicy/command_safety.py` 新建 ~1,000 行
   - **读** `crates/tui/src/command_safety.rs`（~1,200 行）
   - 163 命令 arity 字典 + 危险模式（`rm -rf`, `dd`, `format` 等）
7. ~~`execpolicy/sandbox/seatbelt.py`~~ — **已跳过**（2026-05-07 用户决定）
   - 原因：macOS Seatbelt OS 级隔离不做；命令黑名单 + cwd 边界 + env 清洗已足够
   - 详见集成债清单（第九节）

**Stage 2 Integration commit（P0，2026-05-07 审核后追加）：**

> 2026-05-07 审核发现 Stage 2.2/2.3/2.4 三个模块是孤岛（代码存在但系统从未调用），违反原则 B。
> 需要一个 Integration commit 把它们接入 Engine/TurnLoop。

接入顺序（按依赖关系）：

1. **tool_parser → turn_loop**（~15 行，无外部依赖）
   - 在 `turn_loop.py` 流结束后加 fallback：`has_tool_call_markers` → `parse_tool_calls`
   - Rust 对应：`turn_loop.rs:726-758`
   - 触发条件：API 未返回结构化 tool blocks 但文本中有 `[TOOL_CALL]` / `<invoke>` 标记

2. **compaction → Engine + turn_loop**（~40 行接入）
   - `Engine._run_conversation` 每轮前：`should_compact` → `compact_messages_safe` → 替换 messages + 合并 summary_prompt
   - `turn_loop.py` context overflow：替换空 `continue` 为紧急 compaction 调用
   - Rust 对应：`turn_loop.rs:85-168`（自动）+ `turn_loop.rs:177-208`（紧急）

3. **capacity → Engine**（~200 行 capacity_flow + Engine 改动）
   - `Engine.__init__` 实例化 `CapacityController`
   - `Engine._run_conversation` 加 3 个 checkpoint：pre-request / post-tool / error-escalation
   - 新建 `engine/capacity_flow.py` 实现 `apply_targeted_context_refresh`（调 compaction）/ `apply_verify_with_tool_replay`（重跑只读工具）/ `apply_verify_and_replan`（重建 canonical state）
   - Rust 对应：`capacity_flow.rs:1-975`

4. **command_safety → ExecShellTool heuristics**（~10 行）
   - 把 `Policy.check()` 的 heuristics fallback 从 `lambda _: ALLOW` 改为 `analyze_command` 映射
   - 补齐 COMMAND_ARITY 至 163 前缀

### Stage 3（4–6 周）：74 工具补齐

按 `docs/AUDIT/phase_C_tools.md` 的 inventory 表逐行推进。

**Stage 3 本次窗口只做这 4 个核心 P0**（用户 2026-05-07 决定）：

1. ~~durable Task 系统~~ ✅ **Stage 3.1 已完成**（commit `c8c72e1`）—— 实际用 JSON 文件持久化，不是 SQLite
2. **Sub-agent runtime**（用 `asyncio.Task` + child CancellationToken，与 Rust tokio 协程对齐；**不**用 multiprocessing，2026-05-07 翻案）
3. **apply_patch 模糊匹配**（Rust `MAX_FUZZ=50` + 合并冲突检测）
4. **PTY shell**（用 `ptyprocess` 或 `pexpect`；不集成 Seatbelt，见第九节集成债）

**以下工具延后到 Stage 3.next**（核心逻辑跑通后再做）：

5. ~~approval cache 指纹~~（延后）
6. ~~web_run / Playwright~~（延后）
7. ~~RLM / Remember / Plan / Skill / Validate_data / Test_runner / Truncate / Request_user_input 等~~（延后）

### Stage 4（4–6 周）：MCP / LSP / Hooks / App Server

1. **FastAPI App Server + 28 路由**（`docs/AUDIT/phase_D_...md` 有完整路由表）
2. **RuntimeThreadManager**（Rust `runtime_threads.rs` 4,413 行）
3. **SSE 流**（turn.started / message.delta / tool.progress / approval.required / turn.completed）
4. **MCP HTTP transport + stdio server**
5. **Hooks 7 类事件 + 条件 + webhook 重试**（Rust `hooks.rs` 914 行）

### Stage 5（6–8 周）：CLI + slash 命令 + prompts

1. **22 个 CLI 子命令**（`doctor / models / sessions / resume / fork / init / setup / exec / review / apply / eval / mcp / features / serve / completions / login / logout / auth / config / model / thread / sandbox / app-server / metrics / update`）
2. **49 个 slash 命令**（`docs/AUDIT/phase_E_...md` 有完整表）
3. **17 个 prompt 模板**（从 `crates/tui/src/prompts/` 直接复制 `.md` / `.txt` 文件到 Python 项目）
4. **skills 子系统**（Rust 2,070 行）

### Stage 6（8–12 周）：TUI 完整化

按 Phase E 审核，48 个 ratatui widget → Textual 等价实现。P0：

1. `tui/ui.rs` 顶层编排（7,055 行）→ Textual App screens
2. `tui/app.rs` 事件循环（4,140 行）
3. 流式 transcript + chunking + commit_tick
4. Markdown / diff 渲染
5. approval gate UI
6. command palette + file mention + file picker

### Stage 7（2–4 周）：收尾

1. e2e parity 测试（与 Rust mock client 事件流比对）
2. 性能基准
3. CI/CD、PyPI、Docker

---

## 四、**工作方法论**：任何 AI 接手都按这个流程走

这是我和用户对齐后的**协作模式**，严格执行可以避免 90% 的返工：

### 🔴 两条核心原则（2026-05-07 用户追加，所有 stage 必须遵守）

**原则 A：真实场景测试优先 —— 能用真实大模型 API 验证的，就必须用真实 API 测**

> 用户原话："一定要判断是否能在真实大模型接口的逻辑下实现测试就真实场景测试。"

自检清单（写完模块后，commit 前逐条过）：
1. 本模块是否**可能**出现在真实 LLM 调用路径上？（client / engine / turn_loop / AppRuntime / tool execution / approval / engine event bridge / SSE streaming / hooks / LSP 都算）
2. 如果**是**：必须新增至少一个真实 API 集成测。用 `tests/_real_api.py` 的 `has_deepseek_api_key()` 做 opt-in（没 key 自动 skip，有 key 自动跑）。**不许用"全是 mock 的测试"冒充真实场景**——mock 测对象能初始化，真实 API 测 wire 行为与真实对端吻合，两者必须共存。
3. 如果**纯算法、纯数据结构、纯本地 IO**（apply_patch / command_safety / classify_command / approval_key fingerprint / SSE framing 等）：不需要真实 API 测，但必须有足够的单元测试覆盖 Rust parity 的每条 `#[test]`。
4. 真实 API 测失败时 **不许偷偷 skip 掉**。必须调通或在集成债清单登记（带明确还清计划）。
5. 真实 API 测里如果用到敏感参数（model 名 / base_url / 工具数量），要让**用户的 config.toml 生效**，不要硬编码偏离用户环境的值。

典型例子（本项目已有）：
- ✅ `tests/test_real_api.py` — DeepSeekClient 直接打 API
- ✅ `tests/parity/phase_d/test_prompt_stream.py::TestStreamPromptRealApi` — AppRuntime→Engine→turn_loop→SSE 全链路走真实 flash 模型返回 "pong"

**原则 B：写的每一行代码都必须能"接进系统里"，不许写孤岛**

> 用户原话："写的功能一定是为了继承到系统里。"

自检清单（写完模块后，commit 前逐条过）：
1. `grep -rn '<ClassName|function_name>' src/ tests/` 在**本模块之外**有没有匹配？
   - **没有** = 孤岛。不许 commit。
2. 新模块的所有 public 入口，在**同一个 stage 内**必须被**下列之一**接通：
   - `ToolRegistry` / `ToolContext`（工具类）
   - `AppRuntime` / `Engine` / `ToolRuntime`（运行时类）
   - `build_default_registry` / `create_tool_runtime` / `AppRuntime.create`（装配工厂）
   - CLI 子命令 / HTTP 路由（入口类）
   - 另一个已接通的模块（链式依赖）
3. 集成点**在同一 commit 或紧邻 commit 内完成**。不许 "Stage X 只建模块，集成留给 Stage X.next"——除非用户明确批准延后并在集成债清单登记。
4. 写**集成测试**验证"对象从顶层入口真的能到达这个模块"（不是单测 manager 自己能工作；要测 `registry.get("task_create").execute(...)` 真的调到了 TaskManager）。
5. 如果一个 stage 里的集成链路长，用 **Integration #N** 命名的独立 commit 单独做集成（例子：`dca3816 Integration #2: wire Stage 3 managers into registry + Engine`）。

典型例子（本项目已有）：
- ✅ Stage 3.1/3.2 Manager 建好后，Integration #2 commit (`dca3816`) 把它们挂到 `ToolRuntime` + `Engine.create` + `ToolContext.metadata`
- ✅ Stage 4.2 发现 `hooks/` 是孤岛（没人调用），本 stage 的核心工作就是**接线**而不是新建
- ✅ Stage 4.4 LSP 栈已存在但孤岛，stage 的工作是 `Engine._run_post_edit_lsp_hook` 和 `flush` 接入 turn_loop

**违反原则 A 或 B 的 commit 视为债务**，必须立即在集成债清单登记。

---

### 步骤 0 — 心态：遇到问题不许随意简化（2026-05-06 用户要求）

> 用户原话："简化流程一定是遇到问题一定要告知我为什么要简化，可以做哪些替代方案，而不是遇到问题一味的简化。"

**硬约束：任何"简化"（stub / 跳过 / 降级 / `NotImplementedError` / 返回硬编码值）都必须先经过以下流程。禁止隐式简化。**

遇到一个难点（Rust 行为复杂 / 依赖库不存在 / 时间不够 / 不确定怎么做）时：

1. **停下写代码**。不要自作主张用 stub 糊过去。
2. **向用户说明**（用 `AskUserQuestion` 工具）：
   - **为什么卡住**：哪个 Rust 行为难复刻？缺什么依赖？边界不清楚在哪？
   - **至少 2 个替代方案**：每个方案的代价 + 后果 + 什么时候能补回"百分百"。
   - **推荐哪个**：说清楚你的推荐理由，但**不替用户决定**。
3. **用户决策后**写代码，并在 **commit message + 代码注释**里写清楚"本处是简化，原因 X，用户于日期 Y 批准方案 Z，补齐计划 W"。
4. **简化项必须进集成债清单（第九节）**。无论用户选哪个方案，只要当前不是"百分百 Rust 行为"，就记一条 `⬜ <stage>.simplified: <feature>`，写清楚"还需做什么才能恢复完整行为"。

**反例**（禁止）：
- ❌ "Rust 用了 Starlark crate，Python 没有，我直接跳过了 policy parser，返回空 Policy"
- ❌ "这个字段 Rust 是 i64 timestamp，改起来麻烦，我留 str 了"
- ❌ "web_run 需要 Playwright，先返 NotImplementedError 吧"

**正例**（按流程）：
- ✅ "Rust 用 Starlark DSL，Python 没现成库。我用 AskUserQuestion 给了 3 方案：手写 mini-parser / 引入 starlark-python 包 / 只支持 TOML 子集。用户选 1。我实现了 mini-parser 覆盖 `prefix_rule(...)` 语法，注释里写清楚了不支持 `def/if/for/import`，集成债清单里留了一条 `⬜ 2.1.simplified: full Starlark grammar (currently mini-subset)`。"

### 步骤 1 — 读 Rust 源，提炼行为清单

**不要**看到 Rust 代码就直接翻译。先：

1. `wc -l` 看文件规模
2. `grep -nE '^pub (fn|struct|enum)' <file>` 列出所有 public 符号
3. 对每个 P0 符号完整 `Read` 一次
4. **一定要找测试文件**（`tests/*.rs` 或 `#[cfg(test)] mod tests`）——Rust 的测试就是最权威的行为规范

### 步骤 2 — 给用户**行为清单 + 决策点**

发给用户前按这个结构写：

```markdown
## Stage X.Y — <功能名> 行为清单

### 🎯 目标
<一句话>

### 📊 Rust 里有什么
- 类型 / 函数 / 常量清单（带 Rust 文件:行号引用）
- 关键魔数 / 阈值

### 🐍 Python 现状
- 哪些已实现、哪些缺失、哪些不兼容

### 📋 我打算怎么改
- 要新增 / 修改的文件清单
- 旧 API 怎么兼容（还是直接破坏）

### ⚠️ 需要你决策的点
- 用 AskUserQuestion 工具列出 1-3 个关键选择
```

**用户确认后再动手写代码**。这是最重要的一条。

### 步骤 3 — 写实现

三个原则：

1. **Rust 文件:行号注释**：每个新建的 Python 文件顶部要写 "Mirrors `crates/.../foo.rs:xxx-yyy`"，每个关键函数要写对应的 Rust 行号。
2. **保留旧 API 兼容**：重写某个模块时，**旧的 public 函数名 / 参数 / 返回类型都保留**，内部委托到新实现。避免级联改动。
3. **不要加代码注释解释代码在做什么**（`CLAUDE.md` 的指示）。只在解释"为什么"时写注释。

### 步骤 4 — 写 parity 测试

测试放 `tests/parity/phase_{a-e}/test_<feature>.py`。分两类：

1. **直接移植 Rust `#[test]`**——每个 Rust 测试对应一个 Python 测试，测试名前加 `test_`，函数体翻译。测试 docstring 里写 "Mirror of Rust `<test_name>` (path:line)"。
2. **Python 补充边界测试**——Rust 原本没覆盖但明显值得测的 edge case。

### 步骤 5 — 验证 + 提交

每个 stage 必做三项：

```bash
PYTHONPATH=src .venv/bin/python -m ruff check src tests
PYTHONPATH=src .venv/bin/python -m mypy src
PYTHONPATH=src .venv/bin/python -m pytest tests
```

**三项必须全绿**才能 commit。

Commit message 模板（严格遵循）：

```
Stage X.Y: <one-line summary>

<为什么这个 stage 重要；对应的 P0 审核项>

## What changed

- <文件>:
    <做了什么>

## Tests

tests/parity/phase_X/test_<name>.py — N tests:
- <测试覆盖面>

## make check

ruff: All checks passed!
mypy: Success: no issues found in XXX source files
pytest: <N> passed (<prev> + <delta>), 2 skipped

Co-Authored-By: <your-coauthor-tag>
```

然后 `git push origin main`。

### 步骤 6 — 更新 HANDOVER.md

每个 Stage 完成后，追加到本文档的"已完成"表；如果路线图有调整，更新第三节。

---

## 五、**绝对不要做的事**

（这些都是我踩过坑或者用户明确说过的）

1. **不要盲目 `git add -A`**——总是先 `git status` 看一眼，可能包含你不想提交的删除/改动。Stage 1.5 就是这个教训。
2. **不要跳过行为清单直接写代码**——即使功能看起来简单。Rust 实现往往有魔数 / 边界 / 历史修复，翻译时很容易漏。
3. **不要用 `Exception` 做 `pytest.raises`**（ruff B017）——用具体类型如 `ValidationError`。
4. **不要在 Python 里加"改进"**——比如看到 Rust 代码重复就想抽象，这会破坏 parity 可审计性。
5. **不要静默降级**——比如 `finance` 工具复杂就返回 stub；用户明确要"百分百复刻"。真要 escape 也得先问。
6. **不要在测试用例里调真实的 keyring / 真实 API**——总用 `InMemoryKeyringStore` 或 mock。
7. **不要改 `docs/DeepSeek-TUI-main/`**——这是只读的 parity 参考。
8. **不要在工作区外找 Rust 源**——所有 Rust 源都在 `docs/DeepSeek-TUI-main/crates/`。
9. **不要写"孤岛代码"**——新模块写完后 `grep -rn '<new symbol>' src/` 在它自己的模块外**没有任何匹配**就是债，必须按步骤 7 在同一 Stage 内还清，或明确记入第九节集成债务清单。2026-05-06 用户原话："光写代码进来有什么用，主要是为了用起来"。
10. **不要用"全是 mock 的测试"冒充集成验证**——单元测试 + mock 测"对象能初始化"；集成测"运行时调用链激活"；真实 API 测"wire 行为与真实对端吻合"。三者必须共存。
11. **不要 skip 真实 API 测试"因为没 key"**——`tests/_real_api.py` helper 先看 `DEEPSEEK_API_KEY` 再看 `config.toml`，本地只要有 config.toml 就自动跑。
12. **不要写无意义测试**——参见步骤 4 的黑名单。2026-05-06 清理移除了 34 个此类测试。新增测试前先过 3 问自检。
13. **不要隐式简化**（2026-05-06 用户要求）——任何"stub / 跳过 / 硬编码 / NotImplementedError / 降级"都要按步骤 0 先问用户，不许自作主张。简化完成后在集成债清单补一条 `⬜ <stage>.simplified: <feature>`。
14. **不要一次性堆大量不可跑的代码**（2026-05-06 用户要求）——参见第三节"路线图编排原则"。如果本次提交的代码**没有任何 make check / 真实 API 测试路径能触发**，它就是孤岛，拆小或延后，不许提交。

---

## 六、跨对话 / 跨 AI 接手时的速查

### 上手前必读（按顺序）

1. `AGENTS.md` + `CLAUDE.md` — 项目级 AI 指令
2. **`docs/AUDIT/SUMMARY.md`** — 最重要，列出所有缺口和 Stage 路线图
3. `docs/AUDIT/CODEX_VS_CLAUDE_DIFF.md` — 之前的方法论对比
4. `docs/AUDIT/phase_{A-E}_*.md` — 对应想做的 Stage 看对应 phase
5. 本文档

### 环境搭建

```bash
# 已在 README 里；核心命令：
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
make check  # 所有绿 = 环境 OK
```

### 每个 Stage 的推进模板

```
阶段 X.Y: <feature>
├── 阶段 X.Y.a：读 Rust 源 + 写行为清单 → AskUserQuestion
├── 阶段 X.Y.b：写实现（src/deepseek_tui/<module>/<file>.py）
├── 阶段 X.Y.c：写 parity 测试（tests/parity/phase_<letter>/test_<feature>.py）
├── 阶段 X.Y.d：make check 三项全绿
└── 阶段 X.Y.e：commit + push + 更新 HANDOVER.md
```

### 常用命令

| 场景 | 命令 |
|---|---|
| 查 Rust 文件结构 | `grep -nE '^pub (fn\|struct\|enum)' <file>` |
| 查 Rust 测试 | `grep -n '#\[test\]\|fn test_' <file>` |
| 对比行数 | `wc -l <rust-file> <python-file>` |
| 看已有调用面 | `grep -rn '<symbol>' src/ tests/` |
| 跑单个 parity 测试 | `PYTHONPATH=src .venv/bin/python -m pytest tests/parity/phase_X/<file>.py -v` |
| 跑完整 make check | `PYTHONPATH=src .venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src && PYTHONPATH=src .venv/bin/python -m pytest tests` |

### 遇到问题时的决策树

1. **Rust 行为不清楚** → 读 Rust 测试（`#[test]` 或 `tests/*.rs`）
2. **Rust 用了奇特的 serde / macro** → 看它生成的 JSON 样本（运行 Rust 测试 `cargo test -- --nocapture` 或看 fixtures）
3. **Python 写了但行为和 Rust 不符** → 对比 Rust / Python 测试断言；**Rust 才是真理**
4. **选库选不准**（如 FastAPI vs aiohttp） → 查 `SUMMARY.md` 第六节锁定的决策；没锁的用 `AskUserQuestion` 问用户
5. **性能 / 工作量超预期** → 别偷偷降级，用 `AskUserQuestion` 告诉用户原因并给方案

---

## 七、附：项目目录结构（Stage 1.5 末）

```
deepseek-tui-py/
├── .venv/                                # Python 3.12 venv（已 gitignore）
├── config.toml                           # 用户 API key（已 gitignore）
├── config.example.toml
├── docs/
│   ├── AUDIT/                            # 五阶段缺口审核 + 路线图 + 本文档
│   │   ├── SUMMARY.md                    # 最重要
│   │   ├── CODEX_VS_CLAUDE_DIFF.md
│   │   ├── HANDOVER.md                   # ← 你现在看的
│   │   ├── MASTER_RECONSTRUCTION_AUDIT.md
│   │   ├── phase_A_protocol_config_secrets_state.md
│   │   ├── phase_B_client_engine_execpolicy.md
│   │   ├── phase_C_tools.md
│   │   ├── phase_D_mcp_lsp_hooks_appserver.md
│   │   └── phase_E_tui_cli_commands_prompts.md
│   └── DeepSeek-TUI-main/                # Rust 原项目（parity 参考基线，不修改）
├── src/deepseek_tui/
│   ├── app_server/                       # Stage 4 要重写
│   ├── cli/                              # Stage 5 要重写
│   ├── client/                           # Stage 2.? 要扩
│   ├── config/                           # Stage 1 补过 provider_registry
│   ├── engine/                           # Stage 2 要重写
│   ├── execpolicy/                       # Stage 2.5/2.6 已集成 ✓（不含 sandbox 子目录，Seatbelt 跳过）
│   ├── hooks/                            # Stage 4 要补
│   ├── lsp/                              # Stage 4 微调
│   ├── mcp/                              # Stage 4 补 HTTP + stdio server
│   ├── protocol/                         # Stage 1.4 已全部补齐 ✓
│   │   ├── app.py / approval.py / errors.py / events.py /
│   │   ├── ipc.py / mcp_lifecycle.py / messages.py / prompt.py /
│   │   └── requests.py / responses.py / threads.py / tool_payload.py
│   ├── secrets/                          # Stage 1.2 已全部补齐 ✓
│   │   ├── env_map.py / errors.py / facade.py / file_store.py /
│   │   └── manager.py / store.py
│   ├── state/                            # Stage 2 要补（SQLite schema 对齐）
│   ├── tools/                            # Stage 3 要补齐 74 个
│   │   ├── base.py / builder.py / context.py / encoding.py (已改 ✓) /
│   │   └── registry.py (已改 ✓) / <各工具文件>
│   └── tui/                              # Stage 6 要重写
├── tests/
│   ├── parity/                           # Rust parity 测试
│   │   ├── conftest.py
│   │   ├── rust_fixtures/                # Rust 参考样本目录
│   │   ├── phase_a/                      # 已有：test_secrets.py, test_protocol.py, test_provider_capability.py
│   │   ├── phase_b/                      # 已有：test_tool_name_codec.py
│   │   └── phase_c/                      # 已有：test_registry.py
│   └── test_*.py                         # 其余模块测试
├── .gitignore
├── AGENTS.md
├── CLAUDE.md
├── Makefile
├── pyproject.toml
└── README.md
```

---

## 八、给任何接手 AI 的三句话

1. **用户要的是百分百行为复刻**，不是最快完成；任何想偷工减料的地方先问用户。
2. **Rust 才是规范**；Python 的旧实现很多地方是错的（从 Stage 0 审核可见）。每个 stage 前先读 Rust 源。
3. **每完成一个 P0 就 commit + push**；不要累积改动超过一个逻辑单元。用户希望能在 GitHub 上审阅每一步。
4. **两条核心原则（2026-05-07）** — 见第四节 🔴 章节：
   - **A**：能用真实大模型 API 测的模块，就必须写真实 API 测（不是 mock）
   - **B**：每一行新代码必须能"接进系统"，孤岛代码不许提交，一个 stage 内必须接通

---

## 九、集成债清单（Simplification Debt）

按照第四节步骤 0 的要求，任何偏离"百分百 Rust 行为复刻"的简化都必须记在这里。每条写清楚：**简化了什么、为什么、恢复完整行为需要做什么**。

| 条目 | Stage | 简化内容 | 原因 | 恢复完整行为需要做什么 |
|---|---|---|---|---|
| ⬜ 2.7.simplified: macOS Seatbelt sandbox | 2.7 | 跳过 `sandbox/seatbelt.py` 不实现；`exec_shell` 直接 `subprocess.create_subprocess_shell()` 无 OS 级隔离 | 用户 2026-05-07 决定：命令黑名单 + cwd 边界 + env 清洗足够本地开发用；Seatbelt 做完约 ~800 行工作量换来的是"OS 级兜底"，在本地开发场景收益不高 | 参考 `crates/tui/src/sandbox/{mod,policy,seatbelt}.rs`（~1,364 行），实现：1) `SandboxPolicy`（读/写/执行 allowlist） 2) `SeatbeltProfile` XML 生成 3) `exec_shell` 子进程用 `sandbox-exec -p <profile>` 包装 4) `CommandSpec` 编排器 |
| ⬜ 3.1.simplified: TaskExecutor 占位版 | 3.1 | `task_manager.py::_stub_executor` 只 sleep 50ms 返回合成 summary，不真实调用 LLM / 不驱动 engine / 不真正产出 artifacts | 用户 2026-05-07 决定：让 TaskManager 的持久化/队列/状态机/重启恢复四层骨架今天落地；真 Executor 等 Stage 4 engine 链接通后替换 | 实现 `EngineTaskExecutor`：接 `engine/turn_loop` + `client/deepseek_client` + `ToolRegistry`，把 Rust `task_manager.rs::EngineTaskExecutor`（行 413-699）行为翻过来 —— 含 `TaskExecutionEvent` 流 + `apply_execution_event` + runtime_event_count 累加 + 产出 artifacts |
| ✅ 3.1.simplified: task_shell_start/wait 空壳 | 3.1 | `TaskShellStartTool` / `TaskShellWaitTool` 原为 `raise ToolError("not yet implemented")` | PTY shell 归在 Stage 3.4 | **Stage 3.4 已还清**（commit `7456887`）：两工具直接调 `ExecShellTool`（pty=True 默认），wait 时把 output 以 `TaskArtifactRef` 形式记到 `TaskRecord.artifacts` 并 append timeline 事件；`task_shell_wait` 额外接受 `task_id` 关联任务 |
| ✅ 4.1.simplified: /prompt 不调 LLM | 4.1 → 4.1.next → 4.1.nn | 原为 3-frame placeholder；**已还清**（commit `234dbe9`）：AppRuntime.stream_prompt 注入 LLMClient 时走真实 Engine → turn_loop → DeepSeekClient → SSE，12 种 EngineEvent 全部桥接；无 client 时保持 3-frame placeholder（向后兼容）。含真实 DeepSeek API 集成测（/prompt/stream → flash 模型 → "pong" round-trip） | — | — |
| ⬜ 3.2.simplified: SubAgent 占位 Executor | 3.2 | `subagent/manager.py::_stub_executor` sleep 50ms 返合成 result；没有真实 LLM 调用 / 没 turn loop / 没工具派发 / 不累加 token usage | 用户 2026-05-07 决定：让 Manager+Mailbox+持久化+重启恢复+10 工具接口今天落地，LLM 驱动等 Stage 4 接通 | 实现 `LlmSubAgentExecutor`：用 `DeepSeekClient` + mini turn loop + 为 sub-agent 构建过滤过的 `ToolRegistry`（按 `agent_type.allowed_tools()`）+ 发 `MailboxMessage.tool_call_started/completed` + 发 `MailboxMessage.token_usage`。参考 Rust `mod.rs:1077+`（run_loop / dispatch_tool / handle_api_response）约 ~800 行 |
| ✅ 3.2.simplified: SubAgent system prompt (2026-05-10 p1-audit) | 3.2 | `SubAgentType.system_prompt()` 实现 + `_SUBAGENT_PROMPTS` 7 种类型的 prompt + 自动追加 `subagent_output_format.md` | — | — |
| ✅ 2.4.orphan: tool_parser 已接入 turn_loop (2026-05-08) | 2.4 | `engine/tool_parser.py`（488 行）实现完整但 turn_loop 流结束后没有 fallback 检查文本中的工具调用；DeepSeek 模型在某些场景会把工具调用写成文本而非结构化 blocks，此时 Python 版会**丢失工具调用** | 2026-05-07 审核发现：Rust `turn_loop.rs:726-758` 在流结束后检查 `has_tool_call_markers` → `parse_tool_calls` 作为 fallback，Python 缺此路径 | 在 `turn_loop.py` 的 `StreamDone` 处理后、`break` 前加入：`if not tool_calls and buffer.has_text(): has_tool_call_markers → parse_tool_calls → 追加到 tool_calls + 替换 buffer text`（~15 行） |
| ✅ 2.3.orphan: compaction 已接入 Engine/turn_loop (2026-05-08) | 2.3 | `engine/compaction.py`（423 行）+ `working_set.py`（180 行）实现了但 4 个触发路径全断：①自动 compaction ②手动 /compact ③紧急 context overflow ④capacity refresh | 2026-05-07 审核发现：Rust 在 turn_loop 每步开头调 `should_compact`，context overflow 时调紧急 compaction；Python 的 context overflow recovery 是注释占位（`turn_loop.py:167`） | 1) `Engine._run_conversation` 每轮前调 `should_compact` → `compact_messages_safe` 2) `turn_loop.py` context overflow 路径调紧急 compaction 替代空 `continue` 3) compaction 结果回写 messages + 合并 summary_prompt 到 system_prompt |
| ✅ 2.2.orphan: capacity 已接入 Engine（3 checkpoint 实现） (2026-05-08) | 2.2 | `engine/capacity.py`（326 行）决策逻辑正确但 Engine/TurnLoop 从未实例化或调用 `CapacityController`；缺 `capacity_flow` 执行层（Rust 975 行） | 2026-05-07 审核发现：Rust 在 turn_loop 的 pre-request / post-tool / error-escalation 三处调 capacity checkpoint；Python 完全没有 | 1) `Engine.__init__` 实例化 `CapacityController` 2) 实现 `capacity_flow.py`（~200 行）含 `run_capacity_pre_request_checkpoint` / `run_capacity_post_tool_checkpoint` / `run_capacity_error_escalation_checkpoint` 3) pre-request 的 `TARGETED_CONTEXT_REFRESH` 触发 compaction 4) post-tool 的 `VERIFY_WITH_TOOL_REPLAY` 选只读工具重跑对比 5) error-escalation 的 `VERIFY_AND_REPLAN` 重建 canonical state |
| ✅ 2.6.dead_code: analyze_command 已接入 ExecShellTool heuristic (2026-05-08) | 2.6 | `command_safety.py::analyze_command()`（11 步安全管道）存在但 `ExecShellTool` 走的是 `Policy.check()`（前缀规则），不是 safety 分析管道 | 设计选择：Rust 中 `command_safety` 是 `Policy` 的**输入源**之一（为无规则匹配的命令提供 heuristic fallback），Python 的 `Policy.check()` 第二参数 `heuristics_fn` 硬编码为 `lambda _: Decision.ALLOW` | 把 `ExecShellTool` 的 heuristics fallback 从 `lambda _: ALLOW` 改为调用 `analyze_command` 并映射：`SAFE/WORKSPACE_SAFE → ALLOW`、`REQUIRES_APPROVAL → PROMPT`、`DANGEROUS → FORBIDDEN` |
| ⬜ 2.6.data: COMMAND_ARITY 数量不足 | 2.6 | HANDOVER 声称 163 前缀，实际只有 94（git 37 + npm 26 + cargo 21 + python 2 + docker 6 + node 2） | 2026-05-07 审核发现 | 对照 Rust `command_safety.rs` 补齐缺失前缀（预计 +69 条），覆盖 brew/pip/yarn/pnpm/kubectl/systemctl/chmod/chown/mv/cp 等 |
| ✅ 2.1.stub: turn_loop context recovery 已接入紧急 compaction (2026-05-08) | 2.1 | `turn_loop.py:167` 注释 "would call recover_context_overflow()" 但实际只 `continue`（无限重试直到 MAX_CONTEXT_RECOVERY_ATTEMPTS） | 实现时 compaction 尚未就绪 | 接入 compaction 后替换为真实紧急 compaction 调用（见 2.3.orphan 修复方案第 2 点） |
| ⬜ 2.1.dead_state: consecutive_tool_error_steps 未使用 | 2.1 | `_TurnState.consecutive_tool_error_steps` 声明但从未递增或判断 | Rust 在 post-tool 阶段递增此计数器并在 ≥3 时 hard stop；Python 的工具执行在 Engine 层而非 TurnLoop 层 | 在 `Engine._run_conversation` 的工具执行循环中追踪连续失败步数，≥3 时 break 并 emit ErrorEvent（或在 capacity error escalation 中处理） |
| ⬜ 5.1: P1 CLI 子命令骨架（11 个） | 5.1 | `thread list/read/resume/fork/archive/unarchive/set-name`、`exec`、`review`、`apply`、`eval`、`sessions`、`resume`/`fork`、`mcp`、`mcp-server`、`app-server`、`metrics` 均为 exit(1) + 提示 | 依赖模块 Stage 6–7 才就绪 | 各子命令需接入对应后端模块：thread→StateStore, exec→Engine+TUI, eval→eval 框架, mcp→MCP 管理 UI 等 |
| ✅ 5.1: config set/unset 写文件 (2026-05-09 bugfix-7) | 5.1 | CLI `config set` / `config unset` 已实现真实文件写入（读取→修改→回写 config.toml） | — | — |
| ✅ 5.1: _launch_tui 未接 Engine | 5.1 → 6.1 | 原为空 EngineHandle 传入 DeepSeekTUI | — | **Stage 6.1 已还清**：`_launch_tui` 传 Config → `DeepSeekTUI` on_mount 构建真实 Client+Engine+Task |
| ✅ 5.1: _run_one_shot 未实现 | 5.1 → 6.1 | 原只打印信息 | — | **Stage 6.1 已还清**：`_run_one_shot_async` 构建 Client+Engine 执行单次对话 |
| ⬜ 5.2: P1 slash 命令（30 个） | 5.2 | 注册在 REGISTRY 中 `p0=False`，dispatch 返回 "not yet implemented (P1)" | 依赖 Engine/MCP/Config/Session 等后端模块 | 分类：Engine 依赖（/models /provider /compact 等）、MCP/Tool 依赖（/attach /task /jobs 等）、Config 依赖（/trust /lsp 等）、Session 依赖（/queue /stash） |
| ⬜ 5.2: P0 handler 功能深度不足 | 5.2 | `/save` `/load` `/sessions` → "requires StateStore"；`/edit` `/undo` `/retry` → "requires Engine"；`/tokens` `/cost` `/context` → "requires Engine"；`/statusline` → "requires TUI widget integration" | 需 Engine/StateStore 集成 | 逐个接入：save/load→StateStore, edit/undo/retry→Engine 会话管理, tokens/cost→Engine usage 统计 |
| ✅ 5.2: slash_menu 集成 | 5.2 → 6.5 | 原 SlashMenu 未被 Composer/App 使用 | — | **Stage 6.5 已还清**：Composer 检测 `/` → SlashMenu.show()，Selected → dispatch() |
| ⬜ 5.3: GitHub skill install 未实现 | 5.3 | `install.py` 对 `kind="github"` 返回 FAILED + P1 提示 | 需 HTTP client (httpx) 下载 tarball + 验证 + 解压 | 实现 GitHub tarball 下载、checksum 验证、原子解压 |
| ✅ 5.3: skill update (2026-05-10 p2-audit) | 5.3 | `update()` 实现：读 `.installed-from` → 删除 → 重装 → 保留 trust 标记 | — | — |
| ⬜ 5.3: Skills ↔ Engine 集成 | 5.3 | `render_available_skills_context()` 未被 `engine/prompts.py` 调用；`load_skill` 工具未注册；`active_skill` 一次性注入未实现 | 需 Engine + ToolRegistry 集成 | 1) engine/prompts.py 调 render_available_skills_context() 2) 注册 load_skill 工具 3) Engine 消息队列支持 active_skill 注入 |
| ⬜ 5.3: 远程 Registry 获取 | 5.3 | `fetch_registry()` 未实现 | 需 httpx GET | 实现 httpx GET + RegistryDocument.from_json()，`DEFAULT_REGISTRY_URL` 已准备 |
| ⬜ 6: LineBuffer commit_tick 深度集成 | 6 | `LineBuffer` 存在但 Transcript 仍逐 delta 刷新 | Rust `commit_tick` 按固定间隔提交缓冲区减少重绘 | 在 `_listen_events` 中用 timer 限流 Transcript 刷新 |
| ⬜ 6: Markdown 渲染升级 | 6 | Transcript 当前用 Rich markup，Rust 有自定义 markdown 渲染器（559 LOC） | Textual 内建 `Markdown` widget 可用 | 将 `_AssistantCell` 从 Static 改为 Markdown widget，支持代码块、表格等 |
| ⬜ 6: Diff 渲染 | 6 | Rust `diff_render.rs`（449 LOC）未实现 | — | 在 Transcript 中支持 unified diff 格式渲染 |
| ⬜ 6: ChatScreen/ConfigScreen 整合 | 6 | `screens/chat.py` 和 `screens/config_ui.py` 仍独立存在，未被 DeepSeekTUI 使用 | — | 统一架构或删除重复 |
| ⬜ 6: Help Screen | 6 | Rust `views/help.rs`（672 LOC）未实现 | `/help` 仅输出文本 | 实现专用 Help Screen |
| ⬜ 6: Sidebar | 6 | Rust `sidebar.rs`（770 LOC）会话/线程侧边栏未实现 | — | 实现 Textual 侧边栏 widget |
| ⬜ 6: Model/Provider Picker | 6 | Rust 981 LOC combined 未实现 | `/model` 可接受参数但无 UI picker | 实现 ModalScreen picker |
| ⬜ 6: Session Picker | 6 | Rust `session_picker.rs`（671 LOC）未实现 | — | — |
| ✅ 6: Onboarding Screen (2026-05-10) | 6 | `tui/screens/onboarding.py`（~190 LOC）— `OnboardingStep` (Welcome/ApiKey/Tips) 三步流 + `mask_key`/`is_onboarded`/`mark_onboarded` (`~/.deepseek/.onboarded` 标记) + `OnboardingScreen` ModalScreen。`_start_engine` 接通（首次启动 / 无 API key 时弹出）。5 parity tests | — | — |
| ✅ 6: Ctrl+Enter 换行 (2026-05-10 p2-audit) | 6 | Composer 现支持 Ctrl+Enter / Ctrl+J 插入换行 | — | — |
| ⚠️ 6: Paste burst detection (2026-05-10) | 6 | 用 Textual native `events.Paste` 替代 Rust 的 char-timing 检测（Rust `paste_burst.rs`:328 LOC 之所以存在是因为 ratatui 不支持 bracketed paste）。`Composer.on_paste` 处理粘贴，含换行时设 `_paste_suppress_until` 抑制下一次 Enter 提交（对齐 Rust `PasteBurst::newline_should_insert_instead_of_submit`）。3 Pilot 集成测试 | 用户 2026-05-10 决定：直接用框架原生支持替代 char-timing | 完整还原 char-timing 检测（50 ms char gap）只在不支持 bracketed paste 的极老终端有意义；Textual 自身依赖现代终端，没必要补 |
| ✅ 6: External editor ($EDITOR) (2026-05-10 p2-audit) | 6 | Composer Ctrl+E 调 `$VISUAL`/`$EDITOR` 编辑临时文件，保存后填回 | — | — |
| ⬜ 6: Keybinding 自定义配置 | 6 | Textual 有 BINDINGS 但未暴露自定义配置 | Rust `keybindings.rs`（349 LOC） | — |
| ⬜ 6: Subagent/Shell/MCP 输出路由 | 6 | Rust `subagent_routing.rs`（333）+ `shell_job_routing.rs`（182）+ `mcp_routing.rs`（161）未在 TUI 中显示 | — | 各 routing 模块接入 Transcript |
| ⚠️ 6: Agent card widget (2026-05-10) | 6 | `tui/widgets/agent_card.py`（~290 LOC）— `AgentLifecycle` / `DelegateCard`（含 `DELEGATE_MAX_ACTIONS=3` 截断 + ellipsis 行）/ `WorkerSlot` / `FanoutCard`（含 `claim_pending_worker` / `dot_grid` / `aggregate_status`）/ `apply_to_delegate` / `apply_to_fanout` / `AgentCardWidget`。14 parity tests 对齐 Rust `agent_card.rs:475-672` | 用户 2026-05-10 选 `big3_a`：完整 Textual 移植 | 仍待：1) Mailbox→Transcript 路由（把 `MailboxMessage` 推到对应 card）2) `tool_card` family glyph 暂用本地常量，日后可统一到 Rust `family_glyph` 等价 |
| ⚠️ 6: Pager (2026-05-10) | 6 | `tui/widgets/pager.py`（~310 LOC）— `PagerState` 含 j/k 单行 / Ctrl+D/U 半页 / Ctrl+F/B/Space/Shift+Space/PageDown/PageUp 全页 / `g g`(chord) / `G` / Home/End / `/` 搜索 / `n`/`N` 循环匹配 / wrap-around；`PagerScreen` 是 Textual ModalScreen。20 parity tests 对齐 Rust `pager.rs:483-808` | 用户 2026-05-10 选 `big3_a`：完整 Textual 移植 | 仍待：1) 渲染层 highlight match background（目前 `Static` 不支持子串重新着色；Rust 用 ratatui buffer cell 重写 fg/bg）2) 行 wrap（Rust 有 `wrap_text` ~30 LOC，本端 textual 自动 wrap，按需补） |
| ⚠️ 6: Context inspector (2026-05-10) | 6 | `tui/widgets/context_inspector.py`（~225 LOC）— `InspectorSnapshot` / `ContextReferenceView` / `ToolDetailView` 输入快照，`build_context_inspector_text` 输出包含 `Session Context` / `System Prompt Structure`（stable prefix vs working set）/ `References`（去重 + `MAX_REFERENCE_ROWS=12`）/ `Recent Tools`（active 优先，`MAX_TOOL_ROWS=8`）。`/context` slash 已接通（模型/workspace 段）。11 parity tests 对齐 Rust `context_inspector.rs:294-466` | 用户 2026-05-10 选 `big3_a`：完整 Textual 移植 | 仍待让 `cmd_context` 注入完整快照（`api_messages` / `system_prompt` / `references` / `tool_details_by_cell`）— 这些字段当前还没在 `DeepSeekTUI` 上暴露，需要先在 app 层加 instrumentation，然后 `/context` 才能拿到完整数据 |
| ✅ 6: Notifications/Toast (2026-05-10) | 6 | `tui/notifications.py`（~210 LOC）— `Method` enum (OFF/AUTO/OSC9/BEL) / OSC9 + BEL 序列 / tmux passthrough / `humanize_duration` / `notify_done_to`。app 接入 `_listen_events` 的 `TurnCompleteEvent`。13 parity tests | — | — |
| ✅ 6: OSC-8 hyperlinks (2026-05-10) | 6 | `tui/osc8.py`（~85 LOC）— `wrap_link` / `strip_into` / `strip` / `set_enabled` / `enabled`。7 parity tests 对齐 Rust `osc8.rs` | — | — |
| ⚠️ 6: Clipboard integration (2026-05-10) | 6 | `tui/clipboard.py`（~150 LOC）— `read_text` / `write_text`（走 pbcopy/pbpaste、xclip、wl-copy 子进程，不要求额外依赖）+ `osc8.strip` 净化 + `clipboard_images_dir` 解析。`PastedImage` label。9 parity tests | — | 图片粘贴（`PastedImage`）需要 `Pillow` + 平台图片剪贴板后端；Rust `clipboard.rs` 走 `arboard` crate，Python 这块按需扩 |
| ⚠️ 6: Backtrack/Undo flow (2026-05-10) | 6 | `tui/backtrack.py`（~140 LOC）— `BacktrackPhase` (Inactive/Primed/Selecting) / `Direction` / `EscEffect` / `BacktrackState` 状态机；`DeepSeekTUI.action_esc_press` 接 Esc-Esc chord，目前以 transcript system 消息显示提示而非完整 overlay。12 parity tests | — | 完整 overlay 需要 `OverlayScreen` 在 transcript 上方画选中条 + 左/右键移动；状态机已就绪，UI 可后续补 |
| ⬜ 6: TranscriptCache/HistoryCell 接入 | 6 | `TranscriptCache` / `HistoryCell` 存在但未接入 Transcript widget | — | 接入 Transcript 实现滚动缓存 |
| ✅ 6: Frame rate limiter (2026-05-10) | 6 | `tui/frame_rate_limiter.py`（~75 LOC）— `FrameRateLimiter`（120 FPS 默认 / 30 FPS low-motion）/ `clamp_deadline` / `mark_emitted` / `time_until_next_draw` / `set_low_motion`。集成到 `_AssistantCell` 流式刷新。6 parity tests | — | — |
| ✅ 6: Plan mode prompt UI (2026-05-10) | 6 | `tui/plan_prompt.py`（~165 LOC）— `PlanOutcome` (ACCEPT_AGENT/ACCEPT_YOLO/REVISE/EXIT_PLAN/DISMISSED) / `PlanPromptState` 状态机（支持 1-4 数字 + a/y/r/q/e 字母快捷键 + 上下移动） / `PlanPromptScreen` ModalScreen。`cmd_plan` slash 接通。11 parity tests | — | — |
| ⬜ 6: UI integration test harness | 6 | Rust `ui/tests.rs`（3,052 LOC）无 Textual Pilot 集成测试 | 当前仅单元测试 | 用 Textual Pilot 编写集成测试 |
| ✅ 3.next.rlm.simplified: in-process exec() RLM (2026-05-11 接通注册) | 3.next | 在 `src/deepseek_tui/tools/rlm/`（~600 LOC）实现 RLM 工具：把 Rust `repl/runtime.rs` 的 `python3 -u` 子进程 + JSON-RPC 网桥（共 877 LOC + 协议层 410 LOC）替换为单个 Python 进程内的 `exec()` namespace + 限制 builtins。helpers (`llm_query` / `llm_query_batched` / `rlm_query` / `rlm_query_batched` / `FINAL` / `FINAL_VAR` / `SHOW_VARS` / `repl_set` / `repl_get`) 直接以函数注入 namespace，sub-LLM 调用通过 `asyncio.run_coroutine_threadsafe` 跨 `asyncio.to_thread` worker 桥接到主事件循环。**2026-05-11：`RlmTool()` 已在 `builder.py` 注册（name=`"rlm"`），与简化版 `RlmQueryTool()`（name=`"rlm_query"`）并存** | 用户 2026-05-10 选 `rlm_a`（"In-process exec()"）— 与已拍板的"不做 OS 级 Seatbelt"一致，subprocess 隔离收益低、维护成本高。已落 26 个 parity 测试覆盖 namespace 持久化 / FINAL 触发 / 禁止 builtins / 系统 prompt 行为 / 驱动循环 NoCode 拒绝 / FINAL after RPC | 完整 OS 隔离需要还原 Rust 子进程 + JSON-RPC：1) 用 `python3 -u -c <bootstrap>` 子进程 2) `__RLM_RUN__/__RLM_END__` sentinels 3) `__RLM_REQ_<sid>__::{json}` ↔ `__RLM_RESP_<sid>__::{json}` 协议（参考 `crates/tui/src/repl/runtime.rs:178-877`） 4) per-round `tokio::time::Instant` 精确计时（目前用 `time.monotonic()`）。**不影响 API 测试**（工具签名/行为/输入校验都按 Rust 同步） |
| ✅ 4: App Server /threads/* durable routes (2026-05-11 接通) | 4 → 4.next | 已补 6 条聚合长尾路由：`/skills` / `/tasks` / `/tasks/{id}` / `/tasks/{id}/cancel` / `/apps/mcp/servers` / `/apps/mcp/tools` / `/workspace/status`，delegate 到现有 `SkillRegistry` / `TaskManager` / `McpManager`。**2026-05-11：`build_fastapi_app` 初始化 `app.state.thread_manager = RuntimeThreadManager(...)`，13 条 `/threads/*` durable routes 全部接通；`_ensure_engine_loaded` 改用 `Engine.create(config=self.config)` 补全 tool_runtime；`_get_llm_client` import 路径修正** | — | 还原 Rust 完整 28 条：对照 `crates/tui/src/app_server/routes.rs`（842 LOC）与 `runtime_threads.rs`（4,413 LOC）逐一补 Thread CRUD 长尾（set_metadata、resolve_archived_path、tree fork resolution 等）|
| ⚠️ pre-realapi#2 edit_file multi-occurrence (2026-05-10) | pre-realapi-fix | Schema 已改成 Rust-parity `search`/`replace` 主键 + `old_string`/`new_string` 兼容别名；行为仍保留"必须唯一匹配，否则报错"（Python 安全）。Rust 默认 `replace_all` —— 全量替换 | 当前是用户决策的安全行为：模型常误判替换次数，要求唯一匹配能避免误改 | 若确定要 100% Rust 行为，把 `EditFileTool.execute` 的 `count > 1 → ToolError` 改成 `content.replace(search, replace)` 全量替换；同时考虑加 `count` / `occurrence` 参数允许调用方指定 |
| ⬜ pre-realapi#6 capacity_flow real implementation | 2.2 → 2.next | `run_pre_request_checkpoint` 调 `compact_fn` 但 `run_post_tool_checkpoint` 和 `run_error_escalation_checkpoint` 只 logging。**这次 batch 没动**，原因：完整实现是 Rust 975 LOC（replay only-read tools / 重建 canonical state），单独 stage 处理 | 工作量大于"快速修复" | 实现：1) `apply_targeted_context_refresh` 调 compaction 2) `apply_verify_with_tool_replay` 重跑只读工具对比 3) `apply_verify_and_replan` 重建 canonical state。参考 Rust `capacity_flow.rs:384-727` |
| ⬜ pre-realapi#8 steer mid-stream injection | — | `_run_conversation` 在每轮循环开头 `drain_steers`，工具执行期间发的 steer 要等下一轮才生效。**这次 batch 没动**，原因：流内注入需要从 Engine 信号传到 TurnLoop 内 SSE 循环，是架构改动 | 单独 stage 处理 | Rust `turn_loop.rs:314-357, 540-557` 在 SSE 循环里 select `pending_steers` channel；Python 需要在 `TurnLoop._run_turn_loop` 加 `handle.drain_steers()` 检查（每个 chunk 之间）+ steer 文本暂存到下一轮的 messages 注入路径 |
| ⚠️ batch-2#F1.cycle full briefing path | pre-realapi-batch-2 | `_maybe_advance_cycle` 已实现 wire-up（阈值检测 + JSONL archive + 最近 8 条 seed），但 Rust `produce_briefing` LLM 调用 + `<carry_forward>` 提取 + structured-state seed message 没接到引擎触发路径上 | 这次只做"把孤岛接进来"的最小集成，深度 LLM 调用单独 stage | 在 `_maybe_advance_cycle` 内调 `cycle_manager.produce_briefing(...)` 拿 carry-forward block，用 `cycle_manager.build_seed_messages(...)` 替换简单的 `keep=8` seed；同时把 `seam_manager.collect_seam_texts` 的结果合并到 system_prompt |
| ⚠️ batch-2#F1.seam append checkpoint | pre-realapi-batch-2 | `SeamManager` 已注入 `Engine.seam_manager`，但没有自动调 `produce_soft_seam` 的触发点。当前只有 `seam_enabled=True` 时实例存在 | 只挂 manager，避免每轮都跑 LLM 召唤 seam | 在 `_run_conversation` 每轮开头加 `seam_level_for_active_input` 检查；level 命中时 `produce_soft_seam(messages, level, start, end)` 并把返回的 `<archived_context>` 块作为 assistant message append 到 messages 末尾 |
| ⚠️ batch-2#F2.tui keybinding subset | pre-realapi-batch-2 | 加了 8 个高频 binding（Ctrl+R/M/P/L/T、Tab、PgUp/PgDn）。Rust 完整 catalog 40+ 个（Ctrl+S/U/A/E、Alt+1/2/3、Alt+!/@/#、Ctrl+/、l/v/g/G、`[`/`]`、F1、Ctrl+Shift+C 等）尚未对齐 | 选择最高流量的；剩余按需 | 对照 `crates/tui/src/tui/keybindings.rs::KEYBINDINGS` 79-292 行清单逐项加 `Binding(...)` + 对应 `action_*`；`Tab` cycle 等动作可能需要 mode picker / panel focus 配套 |
| ⚠️ batch-2#F2.toggle_thinking advisory | pre-realapi-batch-2 | `Ctrl+T` 切换 `Config.ui.show_thinking` 但 transcript 仍然总是渲染 thinking deltas（`_listen_events` 无条件调 `transcript.append_thinking`）| 需要 `_ThinkingCell` 配合判断 | `_listen_events` 处理 `ThinkingDeltaEvent` 时检查 `self.config.ui.show_thinking`；`_ThinkingCell` 加 `display = self.config.ui.show_thinking` 或类似条件 |
| ⚠️ batch-2#F3.events SSE 30-tick window | pre-realapi-batch-2 | `/threads/{id}/events/stream` 是 30 tick × 100ms = 3 秒窗口，不是 Rust 的真实 long-poll subscribe。**注意：`subscribe_events()` 已在 `RuntimeThreadManager`（`thread_manager.py:137`）实现，HANDOVER 之前误判为"Python 没有 subscribe_events channel"**。真正缺的是路由层没有消费它 | 路由层 SSE generator 没调用 `subscribe_events()` | 修复：route 内 `mgr.subscribe_events()` 拿 queue + `while not done: await queue.get()` yield SSE frame，替代 30 tick 文件轮询 |
| ⬜ batch-2#F3.automations subtree | — | 整个 `/v1/automations*` 路由子树（CRUD + run + pause + resume + runs 列表）都没实现 | Rust 382 LOC 调度器 | 实现 `AutomationManager`：cron 解析、JSON 持久化、tick scheduler；接 7 条 routes |
| ⬜ batch-2#F4.responses_api full path | — | Rust `responses_api_proxy/mod.rs`（406 LOC）`POST /v1/responses` 完整 forwarder 没实现 | 单独 endpoint 整套 | 新建 `client/responses.py`：构造 OpenAI Responses API request；`/v1/responses` route delegate；schema 字段含 `previous_response_id` 等 |
| ⚠️ batch-2#F5.config nested behavior | pre-realapi-batch-2 | `notifications`/`network`/`skills`/`memory` 子段已加 Pydantic 模型可加载，但运行时还没消费它们（除了 `notifications.method` 仍走 `Config.ui.notify_method`） | 字段对齐先于行为对齐 | 1) `notifications.method` → `_maybe_notify_turn_done` 优先读 2) `network.rules` → 实例化 `ExecPolicyEngine` 时合并 3) `skills.registry_url` → `skills.fetch_registry()` HTTP 4) `memory.mode` → `RememberTool` / `RecallArchiveTool` 行为分支 |
| ⚠️ batch-2#F6.deepseek-reply meta-tool | pre-realapi-batch-2 | 加了 `deepseek` meta-tool（一次性 LLM 调用），但 Rust 的 `deepseek-reply`（带 `previous_message_id` 的 continuation 模式）没加 | 工作量翻倍且依赖 `responses_api_proxy` 端 | 实现后接到 `_tools_call`：维护 `_reply_threads: dict[str, list[Message]]`，每次 `deepseek-reply` 把回复挂到指定 thread |
| ⬜ batch-2.deferred finance tool | — | Rust `tools/finance.rs` 1,068 LOC 金融指标计算（NPV/IRR/折现率/技术指标等）完全未移植 | 工作量过大，超出 batch 范畴 | 单独 stage：1) 翻译 `compute_*` 数值函数 2) 注册到 `build_default_registry`（feature flag）3) 测试用 Rust `#[test]` 黄金值对照 |
| ⬜ batch-2.deferred RLM subprocess sandbox | — | 用户 2026-05-10 已选 `rlm_a` in-process exec()。完整 OS 隔离的 `python3 -u` 子进程 + JSON-RPC（Rust 877 LOC）保留延后 | 隔离收益与维护成本权衡 | 已在第九节 `⚠️ 3.next.rlm.simplified` 条目记录恢复路径 |
| ⬜ batch-2.deferred Hooks shell exec (tui/hooks.rs) | — | Rust `crates/tui/src/hooks.rs`（914 LOC）的 `SessionStart`/`SessionEnd`/`MessageSubmit`/`ToolCallBefore`/`ToolCallAfter`/`ModeChange`/`OnError` 7 类配置驱动 shell 钩子（条件 + 超时 + 后台 + continue_on_error）整体未实现 | 与 `crates/hooks` webhook 系统是不同子系统 | 实现 `tui_hooks/` 包：1) TOML config 读取 2) 7 个 event 触发点接到 Engine / Composer 3) shell exec with `wait_timeout` + `kill_on_drop` |
| ⬜ batch-2.deferred Markdown 渲染管线 | — | Transcript 仍走 `_AssistantCell`（Rich Static + 简单 markup），没换到 Textual `Markdown` widget 也没接 `MarkdownRenderer` 自定义渲染 | 改架构，影响 transcript 全部测试 | 把 `_AssistantCell` 子类改成 `Markdown` 或 mount `MarkdownRenderer` 得到的 `Static`；保留流式 append 接口 |
| ⚠️ logging.no_redactor | logging-batch | 没加自动 PII redactor。当前依赖埋点处 **不主动序列化敏感字段** (`api_key` / `Authorization` 永不 log；user/tool args 截 200 字符) | 集中 redactor 会改所有 `logger.info(...)` 调用语义，工作量翻倍且容易漏；选择"埋点处自律"+code review 兜底 | 若日后想要二次保险：在 `TraceFilter.filter` 末尾对 `record.msg` + `record.args` 做正则扫描（`Bearer\s+[A-Za-z0-9_\-]+` / `sk-[A-Za-z0-9]{20,}` / `api[_-]?key=...`），命中替换为 `***` |
| ⬜ logging.json_format | — | 设计文档拍板 text-only。需要机器解析时用 `jq` / `awk` on text format 也够 | 用户 2026-05-10 选择 | 加 `LoggingConfig.format = "json"` 选项，新建 `JsonFormatter` 输出 `{"ts":..., "level":..., "trace_turn":..., "msg":..., **fields}` |
| ⬜ logging.tui_console_clash | logging-batch | `--log-console` 在 TUI 模式下会污染 alt-screen，目前文档化不解决 | TUI 模式 stderr 与 textual 渲染冲突 | 在 `_launch_tui` 内强制 `console=False`；或写到 `~/.deepseek/logs/console.log` 单独文件 |
| ⬜ logging.subagent_engine_separate | — | 子代理 `Engine` 共用同一 logger root，无法区分父/子 turn 的 trace_turn | 当前 `bind_turn` 是 contextvar，子代理 spawn 时复制父 context，可能串 ID | 子代理 executor 在 `asyncio.to_thread(...)` 进入处主动 `bind_turn(short_id())` 重置 |
| ⬜ logging.mcp_lsp_hooks_emit | — | MCP / LSP / Hooks 子系统的 logger 调用还是基础日志；没在每个 `dispatcher.emit` / `mcp_client.call_tool` / `lsp.diagnostics_for` 入口埋点 | 时间限制在 batch 内只覆盖 Engine + Client + Tools + TUI + AppServer 五个核心域 | 各模块顶部加 `logger = logging.getLogger(__name__)`，在 `dispatcher.emit`、`McpClient.call_tool`、`LspManager.diagnostics_for` 入口加 INFO 级埋点 |
| ✅ workingset.2026-05-14 wired | engine | 2026-05-14：`engine/working_set.py`（187 行）此前是孤岛——下游 `cycle_manager.CycleState.working_set_summary` / `compaction.py:289` 都在等数据，但没有 producer。**修复**：①`Engine.__init__` 实例化 `self.working_set = WorkingSet(workspace=tool_context.working_directory)`（Engine 单例，每个 thread 一份，Q3=A 决策） ②`_handle_send_message` 进入处调 `observe_user_message(op.content)` ③`_execute_tool_calls` 工具结果回包后调 `observe_tool_call(name, args, content)`（所有工具都喂，由 `_extract_paths_from_text` 内部的扩展名正则过滤噪音，Q4=A 决策） ④`build_system_prompt` 收 `working_set_summary=self.working_set.summary() or None`。`tests/parity/phase_b/test_working_set_wiring.py` 8 用例（含 1 skipped 的端到端 read_file 例，注释说明）。 | — | — |
| ✅ pager.2026-05-14 wired | tui | 2026-05-14：`tui/widgets/pager.py::PagerScreen`（含 vim 键 + `g g` chord + `/` 搜索）此前从未被任何 `push_screen` 调用——只有 `PagerState` 的纯单元测试。**修复**：①`ToolCell.can_focus = True` + 加 `BINDINGS = [Binding("o", "open_pager", ...)]`（Q5=A 仅 ToolCell 入口、Q6=A `o` 单键） ②`action_open_pager` 把 `_result.splitlines()` + `f"{tool_name} · {status}"` 喂给 `PagerScreen` 并 `app.push_screen(...)` ③空 result 时 no-op，避免在还没产出的 cell 上弹空 modal。`tests/parity/phase_e/test_pager_route.py` 5 用例：binding 存在、cell 可 focus、push 成功、空 result 不 push、`q` 关闭 modal。 | — | — |
| ✅ skills_cli.2026-05-14 wired + hardened | tui + skills | 2026-05-14：`/skill` slash 此前只 `cat` SKILL.md，不接 install/update/uninstall/trust；`/skills` 只列目录，不接 `--remote`/`sync`/`<prefix>`；`install_system_skills()` 实现存在但**无人调用**，bundled `skill-creator` 永远没装。**修复**：①`tui/commands/handlers.py::cmd_skills` 加 `--remote / remote / sync / --sync / <prefix> / -<flag>-rejected` 分支，对齐 Rust `commands/skills.rs:37-130` ②`cmd_skill` 加 `install <spec> / update <name> / uninstall <name> / trust <name>` 子命令，对齐 Rust `commands/skills.rs:142-310` ③`tui/app.py::on_mount` 起头处调 `install_system_skills()`（包了 try/except，bundled-skill 失败不挡 TUI 启动）④`tui/widgets/__init__.py` + `tui/__init__.py` 修正之前 commit `059261d` 删 `markdown_render.py` / `history.py` / `streaming.py` 时遗留的断链 import（顺手补全 `PagerScreen / PagerState` re-export）。**同时还清审核报告 K-1..K-7 安全项**：①K-1 流式下载 + `DEFAULT_MAX_SIZE_BYTES = 5 MiB` cap（对齐 Rust `install.rs:66`）+ 解压时累加 `member.size` 触顶抛错（gzip-bomb 防御） ②K-2 host 白名单 `GITHUB_ALLOWED_HOSTS = {github.com, www.github.com}` + main → master URL fallback ③K-3 `candidate.resolve().relative_to(dest_resolved)` 路径遍历显式拒绝 ④K-4 `member.issym() / islnk()` 显式跳过 + warning log ⑤K-5 prefix 检测改 `Path.parts[0]` + 跨成员一致性校验，处理"首成员是单文件"边界 ⑥K-7 SKILL.md 接受 `dest/SKILL.md` 或 `dest/<single-subdir>/SKILL.md` 两种布局 ⑦`fetch_registry` 改 `httpx`（Q2=B 决策） + 加 `REGISTRY_ALLOWED_HOSTS` 白名单（默认接受 `raw.githubusercontent.com`）。`tests/parity/phase_e/test_skills_cli.py` 26 用例覆盖：CLI 7 个 dispatch 场景 + 安全 7 个 K-* 场景 + helper 4 个 + startup 1 个 + 集成 1 个。 | — | 仍待：①Skills ↔ Engine 集成（`render_available_skills_context` 接到 `engine/prompts.py`、`load_skill` 工具注册——见旧条目 `⬜ 5.3: Skills ↔ Engine 集成`，未变） ②`/skills sync` 当前只 fetch + 提示，不真正下载到本地缓存（Rust 是 `~/.deepseek/cache/skills/`），后续单独 stage 处理 |
| ✅ audit-fix.2026-05-14 finance_stub_unwired | tools | 2026-05-15 cleanup：`FinanceTool`（stub 假数据）已下架——删 `tools/web_tools.py:152-183` 整个类 + 删 `tools/__init__.py` 的 import + `__all__` 导出。LLM 不再能调用一个返回 `"(finance stub for ...)"` 字符串的工具。 | — | — |
| ✅ audit-fix.2026-05-14 automation_unwired | tools | 2026-05-15 完整接入（详见下方 ✅ automation.2026-05-15 wired 条目）。schema 对齐 Rust（`prompt`/`rrule`/`cwds`）+ JSON 持久化 + 后台调度 loop + reconcile + 审批门禁。原"假冒定时器"问题彻底解决。 | — | — |
| ✅ audit-fix.2026-05-14 web_run_decision | tools | 2026-05-15 cleanup：`WebRunTool`（Playwright/browser-use 风格）已下架——删 `tools/web_tools.py:93-149` + 删 `tools/__init__.py` 导出。**保留** `FetchUrlTool` + `WebSearchTool`（轻量 web 检索，与 LLM 实际使用场景吻合）。未来若需要浏览器自动化走 browser-use MCP（外部子进程），不在主仓库内实现。 | — | — |
| ✅ audit-fix.2026-05-14 auth_orphan | auth | 2026-05-15 cleanup：`src/deepseek_tui/auth/`（1637 行）整目录删除——Rust 端无对应实现，包外 0 引用，多用户/远程 HTTP 部署需求未来再做。顺手清掉 `config/models.py` 里指向已删 `auth/` 的 ~30 行 `AuthConfig` 重复定义残骸（保留另一份 ServerConfig 用的 placeholder）。 | — | 未来若做 App Server 多用户 HTTP 部署：参考 git 历史 commit 之前的 auth/ 实现（JWT + RateLimit + setup_auth_middleware），重新接入到 `app_server/server.py::build_fastapi_app` |
| ✅ automation.2026-05-15 wired | tools | **2026-05-15：从孤岛脚手架升级到完整子系统。** 之前 `automation_tools.py` 296 行实现假装注册 8 个工具，store 在内存 dict、`automation_run` 只 echo 字符串、未注册到 builder——LLM 创建定时任务以为有效果实际啥也没发生（比 stub 还坏）。**修复**：①新建 `tools/automation_manager.py`（~520 行），完整翻译 Rust `automation_manager.rs:120-760`：`AutomationStatus/AutomationRunStatus` Enum、`AutomationRecord/AutomationRunRecord/CreateAutomationRequest/UpdateAutomationRequest` dataclass、`AutomationSchedule.parse_rrule(rrule)` 支持 `FREQ=HOURLY;INTERVAL=N[;BYDAY=...]` + `FREQ=WEEKLY;BYDAY=...;BYHOUR=N;BYMINUTE=N`、`next_after(dt)` Local 时区计算、`AutomationManager.{create/get/list/save/update/pause/resume/delete_automation, list_runs, save_run, run_now, scheduler_tick, reconcile_run_statuses}`、`write_json_atomic` (tmp + os.replace)、`default_automations_dir()` (`$DEEPSEEK_AUTOMATIONS_DIR` 或 `~/.deepseek/automations`) ②新建 `tools/automation_scheduler.py`（~80 行）`run_scheduler_loop` async loop with cancel `asyncio.Event`，`tick → reconcile → asyncio.wait_for(cancel.wait, timeout=interval)`，tick/reconcile 抛错 log warning 不挂 loop（对齐 Rust `tracing::warn!`） ③重写 `tools/automation_tools.py`（~480 行）8 个 Tool schema 对齐 Rust（`prompt/rrule/cwds`）；4 个写工具（create/update/delete/run）加 `ToolCapability.REQUIRES_APPROVAL` + `ApprovalRequirement.REQUIRED` ④`config/models.py::FeatureConfig` 加 `automations: bool = False`（默认关，opt-in） ⑤`tools/runtime.py::create_tool_runtime` 在 `cfg.features.automations` 时 `AutomationManager.open()` → 挂 `metadata['automation_manager']` + `metadata['task_manager']`（AutomationRunTool 用）→ `asyncio.create_task(run_scheduler_loop(...))` 存到 `ToolRuntime._automation_scheduler_task`；`ToolRuntime.shutdown` 设 cancel event 并 `await` 任务停止（5s timeout 兜底） ⑥`tools/builder.py` 新分支 `if cfg.features.automations:` 注册 8 个工具。**测试**：`tests/parity/phase_c/test_automation_manager.py` 48 用例，覆盖：5 个 Rust `#[test]` 翻译（parse_rrule × 3、deletes_automation_and_runs、idempotency）+ 11 个 RRULE 边界（INTERVAL=0 / BYHOUR=24 / 大小写 / 缺 FREQ / 不支持 freq…）+ 4 个 next_after 边界（HOURLY 无 BYDAY、HOURLY+BYDAY 跨周日 → 周一、WEEKLY 跨日、aware 检查）+ 2 validate + 2 default_location + 9 个 CRUD（create + paused 不 arm + sort by updated_at desc + update rrule 重算 next_run + pause/resume re-arm + delete 清 runs 子目录 + 拒绝 future schema_version）+ 5 个 scheduler（fire 准点 + 幂等 same slot 不重复 + 跳过 paused + reconcile completed/failed 写 last_run_at）+ 1 个 run_now + 6 个 tools dispatch（缺 manager 报错、create→list→read→delete 链、create 必审批、run 缺 task_manager 报错、update、pause+resume）+ 3 个 runtime 集成（features 开启时挂 manager + scheduler、关闭时跳过、scheduler 取消事件 < 2s 退出）+ 3 个 dataclass round-trip。**全部 48 passed in 0.6s。** | 用户 2026-05-15 决定全部按推荐选项实现：Q1=Engine.create wiring（与 SubAgent/Task 同构）、Q2=15s tick（对齐 Rust）、Q3=features.automations 默认 False、Q4=`automation_create` 必审批、Q5=cwds 不显式校验（与 Rust 同义）、Q6=manager 不锁（asyncio 单线程串行 + atomic write 已足够） | 仍待：①App Server `/v1/automations*` 路由子树（Rust ``responses_api_proxy/automations.rs`` 7 条 routes）—— 当前仅工具层 + 调度器接入，HTTP 暴露面没做。已在第九节 `⬜ batch-2#F3.automations subtree` 条目记录 ②Rust `automation_create` 工具的 ApprovalCache fingerprint 未对齐（Python 通过现有 `ApprovalCache + approval_handler` 走通用路径，行为基本等价，但缓存键格式略有差异）③`run_now` 当前 `enqueue_run_task` 直接捕获 `Exception` ——Rust 是只捕获 `add_task` 的特定 Result::Err；Python 行为更宽松（任何异常都标 Failed），实际用例下结果一致 |
| ✅ automation.2026-05-15 task-dependency fail-fast | tools | 2026-05-15：把 `features.automations → features.tasks` 的依赖从运行时报错升级为构造期 fail-fast。Automation 本身没有 executor —— 每次 fire 都得调 `TaskManager.add_task`。之前 `create_tool_runtime` 用 `if task_manager is not None:` 软兜底（自动跳过启 scheduler），结果用户配 `automations=True, tasks=False` 时表面看注册了 8 个工具，运行到 `automation_run` 才报"TaskManager is not attached"。改为构造时 `raise ValueError("features.automations requires features.tasks=True ...")`，对齐 Rust `registry.rs::with_runtime_task_tools` 把 task + automation 注册放同一个 builder 方法的设计意图。`tests/parity/phase_c/test_automation_manager.py::test_automations_requires_tasks_fail_fast` 覆盖。 | — | — |
| ⚠️ cache_chip.2026-05-15 cumulative | engine | **2026-05-15：刻意偏离 Rust，原因有说明。** Rust `tui/ui.rs:7377 footer_cache_spans` 只显示 `last_prompt_cache_hit_tokens` —— 最近一轮的本轮命中数。DeepSeek 的 prefix cache 行为决定：多轮会话从第二轮起 prefix 几乎全部命中，本轮命中率始终 ~99%，这个数字是常量没有信息量。**修复**：①`engine.py::Engine.__init__` 加 `self.session_cache_hit_total: int = 0` / `self.session_cache_miss_total: int = 0` ②`_handle_send_message` 处理 usage 时 `self.session_cache_hit_total += usage.cache_read_input_tokens` / `self.session_cache_miss_total += usage.cache_creation_input_tokens` ③`TurnCompleteEvent.cache_hit_tokens` / `cache_miss_tokens` 改用累计值 ④status bar 的 `_cache_chip` 公式（`100 * hit / (hit + miss)`）不变；现在反映"整个会话有多少 prompt 流量是被缓存掉的"。**测试**：`tests/parity/phase_b/test_session_cache_chip.py` 4 用例（初始 0/0 + 两轮累计 60+90=150 hit / 40+10=50 miss + 冷启 → 热缓存的累计比例验证不是 Rust 的 90% 而是 45% + Usage 无 cache 字段时不增）。**全部 4 passed in 0.3s。** | 用户 2026-05-15 拍板："信息量 > Rust 原版"。Rust per-turn 在 prefix cache 场景下永远 99%，截图实际所见。 | 若要严格 Rust parity 可还原：删 `session_cache_hit_total` / `session_cache_miss_total` + 改回 `cache_hit_tokens = usage.cache_read_input_tokens` —— 4 行回退。 |

> **约定**：✅ 已还清 / ⚠️ 部分还清 / ⬜ 未还清
>
> **环境备注**（Stage 6 发现）：Python 3.12.13 中 `_editable_impl_*.pth` 被跳过（以 `_` 开头被视为 hidden），已通过在 `pyproject.toml` 设置 `pythonpath = ["src"]` 解决。

---

## 十、联系方式（用户侧）

- 仓库：https://github.com/fjw1049/deepseek-tui-py
- 用户 ID: fjw1049
- 开发机：macOS（Python 3.12.13 via Homebrew / uv）
- 用户自述："我不太懂 Rust"——所以行为清单写给用户看时，要**用人话解释 Rust 在做什么**。

---

**本文档会随每个 Stage 完成而追加"已完成"条目。如果发现本文档与实际状态不符，以 git log 和 `docs/AUDIT/SUMMARY.md` 为准。**
