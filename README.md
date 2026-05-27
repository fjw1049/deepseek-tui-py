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
uv pip install -e ".[dev]"

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
- **设置**：模型、审批策略（`on-request` / `auto` 等）、Runtime 连接

在输入框里可以用 `@文件路径` 把文件内容带进上下文。

---

## 常见问题

| 现象 | 处理 |
|------|------|
| 启动报错 `Cannot read properties of undefined` | 执行 `unset ELECTRON_RUN_AS_NODE` 后再跑 `./scripts/dev-workbench.sh` |
| 浏览器打开 7878 只有 JSON | 正常——请用 **Electron 窗口**，7878 是 Runtime API |
| 首次启动很慢 | 第一次 `npm ci` 要下 Electron（~150MB），之后会快很多 |
| 连不上 Runtime | 设置里检查 API Key；确认 `.deepseek/config.toml` 或环境变量已配置 |

更细的排错、环境变量、契约测试见 [`packages/workbench/README.md`](packages/workbench/README.md)。

---

## 配置说明

运行时数据默认在项目下的 `.deepseek/`（已 gitignore，每个 clone 独立）：

```toml
# .deepseek/config.toml
provider = "deepseek"
model = "deepseek-chat"

[providers.deepseek]
api_key = "sk-your-key-here"
```

也可用环境变量 `DEEPSEEK_API_KEY`。跨项目共享配置可设 `DEEPSEEK_HOME=~/.deepseek-shared`。

---

## 终端模式（可选）

喜欢终端的用户：

```bash
source .venv/bin/activate
deepseek-tui                    # 交互 TUI
deepseek-tui -p "你好"          # 单次问答
deepseek-tui doctor             # 健康检查
```

手动只起 API（给 GUI 或其它客户端用）：

```bash
deepseek-tui serve --http --port 7878 --config .deepseek/config.toml
```

---

## 开发与测试

```bash
# GUI 契约（Runtime /v1 API）
pytest tests/contract -q

# 日常单元测试（不含真实 API）
pytest tests -q -m "not live and not live_mcp"

# GUI 类型检查 + 冒烟（需 Runtime 已启动）
./scripts/verify-workbench.sh
```

---

## 仓库结构（简图）

```
deepseek-tui-py/
├── packages/workbench/     # Electron 桌面 GUI
├── src/deepseek_tui/       # Python 引擎、工具、Runtime API
├── scripts/dev-workbench.sh
├── .deepseek/              # 本地配置与会话（运行时生成）
└── contracts/              # Runtime API 契约
```

基于 [DeepSeek-TUI](https://github.com/deepseek-ai/DeepSeek-TUI)（Rust）的 Python 复刻，含 70+ 工具、MCP、子代理、审批与安全策略等能力。

---

## 许可证

MIT License
