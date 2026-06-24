# DeepSeek Workbench

本地 AI 编程助手：**桌面图形界面** + Python 运行时。在仓库里改代码、看工具调用、审批敏感操作，都在一个窗口里完成。

> 也支持终端 TUI（`deepseek-tui`），见文末「终端模式」。

---

## 三分钟上手（GUI）

**需要**：Python 3.10+、Node.js 20、DeepSeek API Key。

```bash
git clone https://github.com/fjw1049/deepseek-tui-py.git
cd deepseek-tui-py

# 1. Python 运行时
uv venv .venv --python 3.12
uv sync --extra dev

# 2. 配置 Key（任选其一）
export DEEPSEEK_API_KEY=sk-your-key-here
# 或：mkdir -p .deepseek && cp config.example.toml .deepseek/config.toml  # 填入 api_key

# 3. 安装 GUI 依赖并启动（首次会下载 Electron，约 3–6 分钟）
cd packages/workbench && npm ci && cd ../..
unset ELECTRON_RUN_AS_NODE   # 在 Cursor 里开发时建议执行
./scripts/dev-workbench.sh
```

启动后会打开 **Electron 窗口**——请用这个窗口聊天，不要单独打开 `http://127.0.0.1:7878`（那是后台 API，不是界面）。

---

## 界面里能做什么

- **多会话聊天**：流式回复、推理过程、工具调用记录
- **工作区**：绑定本地项目目录，让 Agent 读写你的代码
- **工具审批**：写文件、跑命令、访问网络等操作会弹出说明，可允许 / 拒绝 / 本会话记住
- **变更与 Diff**：查看 Agent 改动的文件
- **联网搜索**：内置 Web 搜索（AnySearch + Tavily，结果合并）与网页抓取
- **智能记忆**：可选的 L0→L3 分层记忆，跨会话记住用户偏好、项目习惯与踩坑（默认关闭，见「配置说明」）
- **自动化任务**：定时 / 触发式 Agent 任务，结果可投递到飞书或邮件
- **MCP**：通过 `.deepseek/mcp.json` 连接外部 MCP 服务（outbound client；不把 DeepSeek 暴露为 MCP Server）
- **桌面宠物**：输入框旁的小挂件（可在设置里关闭）
- **设置**：模型、审批策略（`on-request` / `auto` 等）、Runtime 连接、记忆、自动化、宠物

在输入框里可以用 `@文件路径` 把文件内容带进上下文。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| 启动报错 `Cannot read properties of undefined` | 执行 `unset ELECTRON_RUN_AS_NODE` 后再跑 `./scripts/dev-workbench.sh` |
| 浏览器打开 7878 只有 JSON | 正常——请用 **Electron 窗口**，7878 是 Runtime API |
| 首次启动很慢 | 第一次 `npm ci` 要下 Electron（~150MB），之后会快很多 |
| 连不上 Runtime | 设置里检查 API Key；确认 `.deepseek/config.toml` 或环境变量已配置 |

更细的排错见 [`packages/workbench/README.md`](packages/workbench/README.md)。

---

## 配置说明

运行时数据默认在 `~/.deepseek/`（也可用仓库内 `.deepseek/` 作项目覆盖）。每个 clone 可独立配置：

```toml
# .deepseek/config.toml
provider = "deepseek"
model = "deepseek-v4-pro"

[providers.deepseek]
api_key = "sk-your-key-here"

# 可选：联网搜索（任一 Key 即可，结果合并）
# anysearch_api_key = ""   # 或环境变量 ANYSEARCH_API_KEY
# tavily_api_key = ""      # 或环境变量 TAVILY_API_KEY

[features]
tasks = true
automations = true
mcp = true

# 可选：自动化投递（飞书 / 邮件）
# [automation.feishu]
# app_id = "..."
# app_secret = "..."
# chat_id = "..."
```

也可用环境变量 `DEEPSEEK_API_KEY`。跨项目共享配置可设 `DEEPSEEK_HOME=~/.deepseek-shared`。

完整可配项见 [`config.example.toml`](config.example.toml)。飞书入站 / 测试发送由 Runtime HTTP 路由提供（`/feishu/inbound`、`/feishu/test-send`），在 GUI 设置或 `config.toml` 的 `[automation.feishu]` 中配置即可。

MCP 配置文件默认路径：`~/.deepseek/mcp.json`（可用 `mcp_config_path` 覆盖）。CLI/TUI 均支持 `deepseek-tui mcp list|add|enable|…`。

---

## 终端模式（可选）

喜欢终端的用户：

```bash
uv run deepseek-tui                    # 交互 TUI
uv run deepseek-tui -p "你好"          # 单次问答
uv run deepseek-tui doctor             # 健康检查
```

手动只起 API（给 GUI 或其它客户端用）：

```bash
uv run deepseek-tui serve --http --host 127.0.0.1 --port 7878 \
  --config .deepseek/config.toml --insecure
```

---

## 开发与测试

```bash
# 安装 Python 开发依赖
uv sync --extra dev

# Runtime / Workbench 契约（/v1 API）
uv run pytest tests/contract -q

# 日常单元测试（不含 live / e2e）
uv run pytest -q -m "not live and not e2e"

# GUI 类型检查 + 前端单测
cd packages/workbench && npm run typecheck && npm test

# SSE 聊天冒烟（需 Runtime 已在 7878 就绪）
./scripts/smoke-workbench-chat.sh
```

内部设计备忘见 [`docs/HANDOVER.md`](docs/HANDOVER.md)（部分链接可能随文档精简而过期）。

---

## 仓库结构

```
deepseek-tui-py/
├── packages/workbench/          # Electron 桌面 GUI（React + Vite）
├── src/deepseek_tui/            # Python 包（合并后约 13 个子模块）
│   ├── cli/                     # Typer CLI（serve / doctor / mcp …）
│   ├── tui/                     # Textual 终端 UI
│   ├── server/                  # FastAPI Runtime（threads、SSE、审批桥）
│   ├── engine/                  # 对话引擎（orchestrator、turn、dispatch）
│   ├── tools/                   # 内置工具注册表与实现
│   ├── mcp/                     # MCP outbound client（manager / store / actions）
│   ├── policy/                  # 审批、沙箱、execpolicy 规则
│   ├── integrations/            # hooks、goal、skills、lsp
│   ├── workflow/                # 工作流 DSL 与运行时
│   ├── automation/              # 定时任务、飞书/邮件投递
│   ├── state/                   # 会话、密钥、@mention 上下文
│   ├── config/ / client/ / protocol/ / prompts/
├── scripts/
│   ├── dev-workbench.sh         # 启动 GUI（Runtime 由 GUI 拉起）
│   ├── smoke-workbench-*.sh     # 冒烟脚本
│   └── start-service.sh         # 仅起 Runtime 服务
├── contracts/                   # OpenAPI + SSE JSON Schema
├── config.example.toml
└── .deepseek/                   # 本地配置与会话（gitignore，运行时生成）
```

基于 [DeepSeek-TUI](https://github.com/deepseek-ai/DeepSeek-TUI)（Rust）的 Python 复刻，含 70+ 工具、MCP 客户端、子代理、审批与安全策略等能力。

---

## 许可证

MIT License
