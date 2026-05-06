# DeepSeek-TUI Python 百分百复刻总审计

日期：2026-05-06  
范围：`src/deepseek_tui` 对照 `docs/DeepSeek-TUI-main` 的 Rust 原实现。  
目标：判断当前 Python 重构是否达到“百分百 Python 版本 1 复刻”，并给出分阶段补齐路线。

## 审计结论

当前 Python 版不能判定为百分百复刻，也不能按 `COMPLETION_SUMMARY.md` 中的“95% / 生产就绪”交付结论继续推进。它更接近一个“最小可运行骨架 + 部分核心工具 happy path + 大量同名接口占位”的版本。

已经具备的价值：

- Python 包结构、配置加载、基础 SQLite、基础 LLM streaming、基础工具注册、基础 TUI/Textual 壳、MCP stdio client、LSP stdio client、hooks sink、app server 桩都已经搭起来。
- `pytest` 在隔离 uv 环境下通过：97 passed, 2 skipped。
- `mypy src` 在隔离 uv 环境下通过：99 source files。

必须纠正的判断：

- 现有测试通过不等于行为复刻。多项测试只验证“对象能初始化 / 桩返回 not_implemented / 内存状态可读写”，没有覆盖 Rust 的真实流程。
- `make check` 当前不能直接运行，因为 `.venv/bin/python` 指向不存在的 `/Users/fjw/miniconda3/bin/python3`。
- `ruff check src tests` 当前失败 16 项，主要在测试文件未使用 import/变量，以及 async 测试中直接调用 `pathlib.Path` 同步方法。
- `src/deepseek_tui/tools/encoding.py` 的工具名编码是非可逆的下划线替换；Rust 原实现有可逆编码和 bare hex 纠错。这是 DeepSeek 工具调用链的 P0 兼容问题。
- `app_server`、subagent、automation、task、web_run、finance、runtime thread、slash command、snapshot/revert、capacity/compaction 等关键能力没有真实复刻。

## 本轮验证记录

运行环境说明：

- 项目目录不是 git 仓库，`git status --short` 返回 `fatal: not a git repository`。
- 项目内 `.venv` 存在，但 Python 链接损坏；因此 `make check` 失败在环境层。
- 使用 `/opt/homebrew/bin/uv run --isolated --with-editable . ...` 临时隔离环境做验证。

命令与结果：

```text
make check
=> failed: .venv/bin/python: No such file or directory

uv run --isolated ... python -m ruff check src tests
=> failed: 16 errors

uv run --isolated ... python -m mypy src
=> Success: no issues found in 99 source files

uv run --isolated ... python -m pytest tests
=> 97 passed, 2 skipped
```

## 原始运行逻辑摘要

Rust 原项目的真实主链路不是单一模块，而是 `crates/tui` 仍作为 live runtime，配合拆出的 workspace crates：

1. `deepseek` CLI dispatcher 解析参数、配置、模式、会话、server/subcommands。
2. TUI 接收输入，维护 transcript、mode、session、slash commands、approval UI、tool routing。
3. Core engine 构建 system prompt 和 message history，经 DeepSeek/OpenAI-compatible Chat Completions streaming 调用模型。
4. Streaming parser 解析 text/thinking/tool calls，工具调用进入 registry、approval gate、execpolicy、sandbox、hooks。
5. 工具结果回灌到模型，可能多轮循环；LSP post-edit diagnostics、capacity guardrail、compaction、snapshots、runtime thread/event timeline 在不同阶段介入。
6. 状态持久化覆盖 threads/messages/checkpoints/jobs/session index/task timeline/automation runs 等，而不是只保存一个 transcript JSON。
7. App server/runtime API 暴露 HTTP/SSE/JSON-RPC 线程、turn、task、automation、MCP introspection 等接口。

Python 当前只实现了这个链路的最小子集：用户消息、基础 streaming、基础工具执行和再次请求。围绕“长会话、生存性、审批安全、子代理、任务、自动化、运行时 API、完整 TUI 操作面”的主逻辑尚未复刻。

## 分阶段审计结果

### Phase A: Protocol / Config / Secrets / State

状态：不可认为等价。

关键问题：

- Protocol 缺少 Rust 的 envelope、event frame、thread request/response、approval event、MCP startup event、tool payload/output 等 IPC/streaming 协议类型。
- Config 缺少 provider capability matrix、network policy、LSP/skills/notifications/memory/auth/telemetry 等完整配置面。
- Secrets 解析顺序与 Rust 硬规则不一致。Rust 明确要求 keyring -> env -> config-file；Python 当前是 env -> config -> keyring。
- Secrets 缺少 FileKeyringStore、0600 权限校验、headless Linux fallback、错误类型和 backend probe。
- State schema 与 Rust 不兼容：Rust timestamp 是 INTEGER epoch，Python 多处是 TEXT；Rust ThreadMetadata 约 21 字段，Python threads 表只保留基础字段；checkpoint 作用域也不同。

优先级：P0。先修 protocol/secrets/state schema，否则后续 server/runtime/session 复刻会反复返工。

### Phase B: Client / Engine / Execpolicy / Sandbox

状态：核心骨架可跑，但远未等价。

关键问题：

- Tool name codec 不等价。Rust `to_api_tool_name/from_api_tool_name` 可逆编码 `-x00002E-` 并修复模型裸 hex 变形；Python `tools/encoding.py` 只把非法字符替换成 `_`，会丢失原名。
- Client 缺少连接健康状态、rate limiter、Retry-After 解析、SSE backpressure、stream idle timeout、health probe、granular LlmError、Responses fallback/probe。
- Engine 只有 3 次工具 round-trip 的最小循环，缺少 capacity guardrails、capacity flow checkpoints、context token accounting、working set、compaction、cycle manager、seam/backtrack、runtime thread coordination、session recovery。
- Execpolicy 只有粗略 risk/capability 判断，缺少 TOML/HCL policy parser、glob/regex matcher、standard rules、policy amendment。
- Sandbox 是 stub，没有 macOS Seatbelt、Linux Landlock、CommandSpec orchestrator、read/write/exec allowlists。
- Command safety 和 network policy 基本缺失，包括危险命令分类、network allow/deny/audit/session cache。

优先级：P0。尤其 tool name codec、engine 真实 turn loop、execpolicy/sandbox 是工具安全和 API 成功率的底座。

### Phase C: Tools

状态：工具名覆盖看起来不少，但大量是基础实现、内存实现或占位；不能按“全量工具实现”验收。

关键问题：

- `web_run` 和 `finance` 仍返回 stub metadata。
- Task/PR attempt/automation/subagent 是内存状态，不接 Rust 的 durable manager、cron/heartbeat、timeline、mailbox、agent loop。
- `agent_spawn` 不会真正启动子代理；`agent_wait` 只返回当前内存字段。
- `task_gate_run` 直接返回 passed，没有运行 gate 或记录证据。
- Shell 缺少 PTY、sandbox、env scrubbing、持久 job server、输出截断/摘要。
- `apply_patch` 缺少 Rust fuzzy matcher、conflict detection、auto-resolve heuristics。
- 文件工具缺少 PDF extraction；fetch_url 缺少内容类型抽取、HTML text extraction、bounded preview；GitHub 工具依赖 `gh` shell-out，未复刻 Rust REST/auth/approval 逻辑。
- 缺少 RLM、remember、skill_load、plan_update、note、recall_archive、revert_turn、validate_data、run_tests、truncate、request_user_input、review 等关键工具。
- Registry 虽然已排序，但缺少 capability filter、approval-required set、API cache 等 Rust registry 行为；approval_cache 缺失。

优先级：P0。先补 durable task/subagent/web_run/shell/apply_patch/snapshot/approval cache，再扩展 P1 工具。

### Phase D: MCP / LSP / Hooks / App Server

状态：MCP/LSP 有部分底层能力，hooks/app server 主要是骨架。

关键问题：

- MCP 缺少 HTTP transport、stdio server mode、startup lifecycle events、sandbox state update、resource templates full support、完整 TOML/JSON config schema。
- LSP 有 stdio client 和 manager，但未接进 engine post-edit hook，也没有把 diagnostics flush 回下一次 API 请求的完整链路。
- Hooks 缺少 SessionStart/End、MessageSubmit、ToolCallBefore/After、ModeChange、OnError、conditions、HookContext、shell command execution、webhook retry/backoff。
- App server HTTP 明确 `NotImplementedError`；routes 多数返回 `not_implemented`；没有 28 个 Rust runtime API route、没有 thread/turn manager、没有 SSE event timeline、没有 task/automation runtime。

优先级：P0/P1。App server 依赖 state/runtime thread/task manager，不能孤立补。

### Phase E: TUI / CLI / Slash Commands / Prompts / Managers

状态：严重不足。Textual 壳可显示基础对话，但不是 Rust TUI 功能复刻。

关键问题：

- CLI 只有 `run/config-show/version`，缺少 Rust 的 doctor/models/sessions/resume/fork/init/setup/exec/review/apply/eval/mcp/features/serve/completions/login/logout/auth/config/model/thread/sandbox/app-server/metrics/update 等命令面。
- 49 个 slash commands 没有 dispatcher 和真实实现；`slash_menu` 只是 UI widget。
- Prompts 只有 `build_system_prompt()` 小函数，缺少 Rust prompt assets、modes、personalities、approval prompts、subagent output format、skills loading。
- TUI 缺少 top-level UI orchestrator、mode transition、approval flow、command palette、file mention、markdown renderer、diff renderer、pager、sidebar、model/provider picker、session picker、external editor、clipboard、paste burst、OSC-8、notifications、tool/subagent/shell/MCP routing。
- 缺少 compaction/cycle/session/task/automation/seam/memory/project managers 等顶层管理器。

优先级：P1，但 slash commands、mode switching、approval UI、prompts、CLI exec/serve/auth 是可用性的 P0。

## 当前最大风险排序

1. P0: “生产就绪”判断错误。现状是 scaffold，不是 parity。
2. P0: Tool name encoding 非可逆，可能导致 DeepSeek 工具调用名不可还原或冲突。
3. P0: Secrets precedence 违背 Rust 安全规则。
4. P0: App server/runtime API 基本未实现，但 TASKS 标记为完成。
5. P0: Subagent/task/automation 只是内存模拟，会让模型以为任务已执行，实际没有后台 loop 或持久化。
6. P0: Sandbox/execpolicy/command safety 缺失，shell 直跑风险高。
7. P0: Engine 缺少 compaction/capacity/session recovery，长会话会偏离原项目设计。
8. P1: TUI/CLI/slash command 操作面缺失，用户工作流无法复刻。
9. P1: 测试覆盖偏“初始化和 happy path”，缺少 Rust parity fixtures 和 failure-mode 测试。
10. P2: 文档中多处“完成/生产就绪/95%”会误导后续排期，需要改为真实状态。

## 建议的分阶段实现路线

### 阶段 0：校准验收口径和工程环境

成功标准：

- 修复 `.venv`，`make check` 能在本机直接运行。
- 修复 ruff 16 项错误。
- 把 `TASKS.md`、`COMPLETION_SUMMARY.md` 中“完成/生产就绪/95%”改成“骨架/部分/未复刻”的真实状态。
- 建立 parity 清单：每个 Rust feature 对应 Python module、测试、fixtures、完成状态。

需要你确认：

- 是否要求 Python 版外部命令名仍叫 `deepseek`，还是接受 `deepseek-tui`。
- Textual 替代 ratatui 是否算“体验复刻”还是只要求功能等价。

### 阶段 1：协议、配置、密钥、状态底座

成功标准：

- Protocol 补齐 event frame/envelope/thread request/response/tool payload/approval/MCP startup 类型。
- Config 补齐 provider/network/lsp/skills/memory/auth/telemetry/capability matrix。
- Secrets 改为 keyring -> env -> config-file，并实现 FileKeyringStore fallback。
- State schema 对齐 Rust ThreadMetadata、messages、checkpoints、jobs、session index JSONL。
- 加 Rust fixture 到 Python 反序列化/序列化 parity tests。

### 阶段 2：Client、Engine、Execpolicy、Sandbox

成功标准：

- 先移植 Rust tool name codec，并覆盖非 ASCII、点号、短横线、裸 hex 变形测试。
- Client 补 Retry-After、rate limiter、connection health、SSE backpressure、idle timeout、pricing/cache accounting。
- Engine 补真实 turn loop、tool parser、tool catalog、capacity guardrails、context accounting、compaction、session recovery。
- Execpolicy 补 parser/matcher/default rules/amendment。
- Sandbox 至少先实现 macOS Seatbelt，再补 Linux Landlock。

### 阶段 3：工具系统真实化

成功标准：

- durable TaskManager、PR attempt、automation scheduler、subagent runtime 真实可运行并持久化。
- `web_run` 接 Playwright；`finance` 明确数据源或从默认 registry 移除并标为不支持。
- shell 具备 PTY、sandbox、job persistence、输出摘要。
- `apply_patch` 移植 fuzzy matcher。
- 补 RLM、remember、skill_load、plan、note、recall_archive、revert_turn、validate_data、run_tests、truncate、request_user_input。

需要你提供或确认：

- 浏览器自动化是否允许引入 Playwright 及浏览器下载。
- finance 是否必须复刻；如果必须，需要指定数据源或允许第三方 API。
- subagent 是否要复刻为进程内 asyncio task，还是允许多进程隔离。

### 阶段 4：Runtime API、MCP、Hooks、LSP 注入

成功标准：

- App server 实现 HTTP/SSE/stdio JSON-RPC routes，并绑定 RuntimeThreadManager。
- MCP 补 HTTP transport、server mode、startup lifecycle、resource templates。
- Hooks 补 config、conditions、HookContext、shell execution、webhook retry。
- LSP post-edit diagnostics 接入 engine，并在下一次请求前注入 synthetic user message。

### 阶段 5：TUI、CLI、Slash Commands、Prompts

成功标准：

- CLI 子命令面与 Rust 对齐，至少覆盖 run/exec/doctor/setup/auth/config/model/thread/serve/mcp/sandbox。
- Slash command dispatcher 和 49 个命令分批复刻。
- Prompts/modes/personalities/approval prompts 完整迁移。
- TUI 补 mode switching、approval UI、tool routing、markdown/diff/pager/session picker/model picker/file mention/external editor 等用户工作流。

### 阶段 6：Parity 测试与发布门禁

成功标准：

- 每个阶段都有 Rust fixture parity tests。
- 增加 E2E：真实工具 round-trip、tool denial、LSP post-edit、task resume、subagent wait、app server SSE、slash command。
- 增加 failure tests：API 429 Retry-After、stream 中断、sandbox deny、network deny、bad MCP server、broken keyring。
- 发布门禁：`make check`、coverage、manual TUI smoke、app server smoke、真实 DeepSeek tool call smoke。

## 下一步建议

不要从 TUI 或工具数量继续堆功能。下一步应先做阶段 0 和阶段 1：

1. 修环境和文档状态，避免继续在错误验收口径上推进。
2. 移植 tool name codec，因为它小但影响所有工具调用。
3. 修 secrets precedence，因为这是明确安全规则。
4. 对齐 state schema，因为 runtime API、task、session、automation 都依赖它。
5. 为上述三项补 parity tests，建立“以后每补一个模块都能证明等价”的测试方式。

