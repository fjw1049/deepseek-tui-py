# Python 阶段一到四实现追溯

日期：2026-05-05

范围：仅覆盖 `TASKS.md` 阶段一到四；阶段五及之后的 TUI、LSP、hooks、app_server 不纳入本轮实现。

## 追溯来源

- `docs/DeepSeek-TUI-main/docs/CONFIGURATION.md`
- `docs/DeepSeek-TUI-main/docs/TOOL_SURFACE.md`
- `docs/DeepSeek-TUI-main/docs/MCP.md`
- `docs/DeepSeek-TUI-main/docs/MODES.md`
- `docs/DeepSeek-TUI-main/docs/ARCHITECTURE.md`
- `docs/DeepSeek-TUI-main/docs/RUNTIME_API.md`
- `docs/DeepSeek-TUI-main/crates/tui/src/client/chat.rs`
- `docs/DeepSeek-TUI-main/crates/tui/src/models.rs`
- `docs/DeepSeek-TUI-main/crates/state/src/lib.rs`
- `docs/DeepSeek-TUI-main/crates/execpolicy/src/lib.rs`

## 新增了什么

### 配置层

- 新增 `config/paths.py`
  - 统一处理 `~/.deepseek/config.toml`、项目 `.deepseek/config.toml`、`.env`、managed config、requirements 路径。
  - 支持 `.env` 加载，且不覆盖已经存在的环境变量。
- 新增 `config/provider_registry.py`
  - 记录 provider 默认 `base_url` 和模型。
  - 将 `deepseek-chat` / `deepseek-reasoner` 作为兼容别名归一到 `deepseek-v4-flash`。
  - 提供模型 context window 基础判断。
- 扩展 `config/models.py`
  - 增加 `default_text_model`、`approval_policy`、`sandbox_mode`、`allow_shell`、`mcp_config_path`、`skills_dir`、`notes_path`、`memory_path`。
  - 增加 `retry`、`features`、`snapshots`、`context`、`capacity`、`subagents`、`tui` 等前四阶段后续会依赖的配置结构。
- 扩展 `config/loader.py`
  - 加入加载顺序：用户 config -> profile -> 项目 overlay -> env -> CLI -> managed config -> requirements 校验。
  - 支持 `workspace` 和 `no_project_config`。

### 状态层

- 扩展 `state/schema.py`
  - 新增 `threads`、`messages`、`thread_dynamic_tools`、`jobs` 表。
  - 保留现有 `sessions`、`checkpoints`、`offline_queue` 兼容层。
- 新增 `state/threads.py`
  - 提供 thread upsert/get/list/archive/delete。
- 新增 `state/messages.py`
  - 提供 message append/list，以及 JSON content encode/decode。
- 新增 `state/jobs.py`
  - 提供 job upsert/get/list_recent。

### API 协议层

- 新增 `client/chat_messages.py`
  - 将内部 block message 转换成 DeepSeek/OpenAI Chat Completions wire format。
  - 支持 assistant `tool_calls`、tool result、system prompt。
  - 支持 DeepSeek V4 thinking 模型的 `reasoning_content` 回放占位。
  - 清理 orphaned tool calls，避免发送 DeepSeek 会拒绝的消息链。
- 扩展 `protocol/requests.py`
  - 增加 `tool_choice`、`temperature`、`top_p`、`reasoning_effort`、`extra_body`。
- 修改 `client/deepseek.py`
  - 工具 schema 改为 OpenAI-compatible function shape。
  - streaming 请求增加 `stream_options.include_usage`。
  - 空 tools 不再发送。
  - `reasoning_effort="off"` 作为内部关闭语义处理，不再发送给 DeepSeek API。

### 工具与安全层

- 修改 `tools/registry.py`
  - `to_api_tools()` 输出：
    `{"type":"function","function":{"name":...,"description":...,"parameters":...}}`
  - 工具路径越界错误统一包装为 `ToolError`。
- 新增 `tools/builder.py`
  - 提供 `build_default_registry(config, mode)`。
  - 按 `features`、`allow_shell`、`mode` 装配默认工具。
- 修改 `tools/context.py`
  - 默认禁止绝对路径和 `..` 逃出 workspace。
  - `trust_mode=True` 时允许访问 workspace 外路径。
- 修改 `tools/utility_tools.py`
  - `project_map` 改用统一 workspace path resolver。

### 审批层

- 新增 `engine/approval.py`
  - 提供 `ApprovalHandler`、`AutoApprovalHandler`、`DenyApprovalHandler`、`EventApprovalHandler`。
- 扩展 `engine/events.py`
  - 新增 `ApprovalRequiredEvent`、`ApprovalResolvedEvent`、`SandboxDeniedEvent`。
- 修改 `engine/engine.py`
  - 工具执行前接入 `ExecPolicyEngine.evaluate()`。
  - 审批拒绝时不执行工具，并返回 tool error 给模型。
  - 审批通过时记录 session decision。
- 扩展 `execpolicy/engine.py`
  - 增加 `approval_policy` 模式基础支持：`on-request`、`auto`、`never`、`yolo`。

### MCP 层

- 新增 `mcp/loader.py`
  - 读取 `mcp.json`。
  - 兼容 `servers` 和 `mcpServers`。
  - 支持 `enabled` / `disabled`、timeouts、`required`、`enabled_tools`、`disabled_tools`。
- 扩展 `mcp/client.py`
  - 增加 resources/list、resources/templates/list、resources/read、prompts/get 方法。
  - 对未实现的 HTTP MCP transport 返回明确错误。
- 扩展 `mcp/manager.py`
  - MCP discovered tools 输出 OpenAI-compatible function schema。
  - 增加资源、模板、prompt 读取路由。
- 新增 `tools/mcp_tools.py`
  - `list_mcp_resources`
  - `list_mcp_resource_templates`
  - `read_mcp_resource`
  - `mcp_get_prompt`

### 工程脚本

- 修改 `Makefile`
  - `ruff`、`mypy`、`pytest` 改为 `.venv/bin/python -m ...`，避免虚拟环境脚本 shebang 指向旧路径导致 `make check` 失败。

## 减少了什么

- 默认工具注册器不再暴露仍是 stub 的 `web_run`、`finance`、task、automation、subagent 工具。
- Chat Completions payload 不再发送旧的 Anthropic-style top-level `input_schema` tool shape。
- `reasoning_effort="off"` 不再作为 API 字段发送，避免 DeepSeek 当前返回 `unknown variant off`。
- 文件工具默认不再允许 workspace 外路径。
- `make check` 不再依赖 `.venv/bin/mypy` / `.venv/bin/pytest` 脚本自身的 shebang。

## 已实现的功能

- DeepSeek/OpenAI-compatible function tool schema。
- DeepSeek live API 工具 payload 验证通过。
- Chat Completions message serializer 支持 tool call/tool result 链。
- Workspace path boundary 默认保护。
- Engine 工具执行前审批 gate。
- `.env`、项目 overlay、managed config、requirements 的配置加载链。
- 前四阶段状态层扩展到 threads/messages/jobs。
- MCP config 文件加载和 MCP resources/prompts helper 基础。
- 默认工具注册器按 mode/features 装配工具。

## 优化了什么

- API 兼容性：工具 payload 从会被 DeepSeek 400 拒绝，变为 live API 200。
- 安全性：文件路径默认限制在 workspace 内。
- 可测试性：审批不再只在孤立单测里存在，而进入 engine 工具执行路径。
- 可维护性：Chat Completions message 转换从 client 中拆出，便于单独补 parity。
- 可恢复性：状态 schema 从单一 transcript JSON 扩展到 thread/message/job 维度。
- 工程稳定性：`make check` 在当前目录可直接通过。

## 当前统计

- Python 源文件：84 个。
- Python 源码行数：6513 行。
- 测试文件：9 个。
- 测试行数：1864 行。
- 测试数量：68 个。
- 本轮新增核心文件：10 个。
  - `config/paths.py`
  - `config/provider_registry.py`
  - `client/chat_messages.py`
  - `engine/approval.py`
  - `state/threads.py`
  - `state/messages.py`
  - `state/jobs.py`
  - `mcp/loader.py`
  - `tools/builder.py`
  - `tools/mcp_tools.py`

## 验证记录

- `make check`：通过。
- `ruff check src tests`：通过。
- `mypy src`：通过，84 source files。
- `pytest tests`：通过，68 passed。
- DeepSeek live API：
  - 使用 `deepseek-v4-flash`。
  - 当前 Python 生成的 tool payload 返回 HTTP 200。

## 仍未完成或仅完成基础骨架

- task tools 仍是内存兼容实现，尚未接真实 durable task manager。
- automation tools 仍是内存兼容实现，尚未接真实 cron/heartbeat 调度。
- subagent tools 仍是内存兼容实现，尚未启动真实子代理 loop。
- `web_run` 和 `finance` 仍是 stub；本轮已从默认 registry 中移除，避免误用。
- MCP HTTP transport 未实现，仅 stdio 可用。
- MCP server mode 未实现，仍应保持 `TASKS.md` 可选未完成。
- 原实现的 capacity/context compaction、skills、memory、snapshots、LSP、runtime API 属于后续阶段或更大 parity 范围。
