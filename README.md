# DeepSeek-TUI Python

一个功能完整的 DeepSeek AI 助手终端界面（TUI），使用 Python 重写。

## 特性

- 🚀 **完整的 LLM 集成** - 支持 DeepSeek V4 Flash 和 Pro 模型
- 🛠️ **丰富的工具系统** - 32+ 内置工具（文件操作、Shell、Git、Web、GitHub 等）
- 🔐 **灵活的密钥管理** - 支持环境变量、配置文件、系统 keyring
- 💾 **持久化存储** - SQLite 数据库存储会话历史
- 🎨 **现代 TUI 界面** - 基于 Textual 的交互式终端界面
- 🔌 **MCP 集成** - 支持 Model Context Protocol 外部工具
- 🛡️ **审批策略** - 可配置的工具执行审批机制
- 🔍 **LSP 集成** - 代码编辑后自动诊断
- 📊 **Hooks 系统** - 事件分发和日志记录

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/yourusername/deepseek-tui-py.git
cd deepseek-tui-py

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

# 安装依赖
pip install -e .
```

### 配置

1. 设置 API Key（三种方式任选其一）：

```bash
# 方式 1：环境变量
export DEEPSEEK_API_KEY=sk-your-key-here

# 方式 2：配置文件
mkdir -p ~/.deepseek
cat > ~/.deepseek/config.toml << EOF
provider = "deepseek"
api_key = "sk-your-key-here"
EOF

# 方式 3：系统 keyring
python -c "import keyring; keyring.set_password('deepseek-tui', 'deepseek', 'sk-your-key-here')"
```

2. （可选）自定义配置：

```bash
cp config.example.toml ~/.deepseek/config.toml
# 编辑 ~/.deepseek/config.toml
```

### 运行

```bash
# 启动 TUI
deepseek-tui

# 或直接运行
python -m deepseek_tui.cli
```

## 架构

```
deepseek-tui-py/
├── src/deepseek_tui/
│   ├── config/          # 配置系统
│   ├── secrets/         # 密钥管理
│   ├── state/           # SQLite 持久化
│   ├── protocol/        # 消息协议
│   ├── client/          # LLM 客户端
│   ├── engine/          # 引擎核心
│   ├── tools/           # 工具系统
│   ├── mcp/             # MCP 集成
│   ├── execpolicy/      # 审批策略
│   ├── tui/             # TUI 界面
│   ├── lsp/             # LSP 集成
│   ├── hooks/           # Hooks 系统
│   └── app_server/      # App Server
└── tests/               # 测试套件
```

## 工具系统

内置 32+ 工具：

### 文件操作
- `read_file` - 读取文件
- `write_file` - 写入文件
- `edit_file` - 编辑文件
- `list_dir` - 列出目录

### 搜索
- `grep_files` - 搜索文件内容
- `file_search` - 按名称搜索文件

### Shell
- `exec_shell` - 执行 Shell 命令
- `exec_shell_cancel` - 取消后台命令
- `exec_shell_wait` - 等待命令完成
- `exec_shell_interact` - 与命令交互

### Git
- `git_status` - Git 状态
- `git_diff` - Git 差异
- `git_log` - Git 日志
- `git_show` - 显示提交
- `git_blame` - Git blame

### Web
- `web_search` - 网页搜索
- `fetch_url` - 获取 URL

### GitHub
- `github_issue_context` - 获取 Issue 上下文
- `github_pr_context` - 获取 PR 上下文
- `github_comment` - 添加评论
- `github_close` - 关闭 Issue/PR

### 任务管理
- `task_create` - 创建任务
- `task_list` - 列出任务
- `task_read` - 读取任务
- `task_cancel` - 取消任务

### 其他
- `apply_patch` - 应用补丁
- `diagnostics` - 系统诊断
- `project_map` - 项目结构
- `todo_*` - Todo 管理
- `automation_*` - 自动化任务
- `agent_*` - 子代理管理

## 配置

配置文件位置：`~/.deepseek/config.toml`

### 基础配置

```toml
provider = "deepseek"
model = "deepseek-v4-pro"
api_key = "sk-your-key-here"
base_url = "https://api.deepseek.com"

# 审批策略
approval_policy = "on-request"  # auto, on-request, never-ask
sandbox_mode = "workspace-write"  # workspace-write, workspace-read, trust

# 工具配置
allow_shell = true
max_subagents = 10
```

### Provider 配置

```toml
[providers.deepseek]
api_key = "sk-your-key-here"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-pro"
timeout = 120
max_tokens = 4096
temperature = 0.7
```

### UI 配置

```toml
[ui]
color_scheme = "default"
show_thinking = true
show_tool_details = true
auto_compact = false
max_history = 1000
```

### 状态配置

```toml
[state]
database_path = "~/.deepseek/state.db"
autosave = true
```

### 重试配置

```toml
[retry]
enabled = true
max_retries = 3
initial_delay = 1.0
max_delay = 60.0
exponential_base = 2.0
```

## 开发

### 运行测试

```bash
# 运行所有测试
make test

# 或
pytest tests/

# 运行特定测试
pytest tests/test_integration.py -v

# 运行真实 API 测试（需要 API key）
export DEEPSEEK_API_KEY=sk-your-key-here
pytest tests/test_real_api.py -v
```

### 代码质量检查

```bash
# 运行所有检查
make check

# 或分别运行
ruff check src/ tests/
mypy src/
pytest tests/
```

### 格式化代码

```bash
ruff format src/ tests/
```

## API 文档

详细的 API 文档请参见 [API.md](docs/API.md)。

## 配置文档

详细的配置文档请参见 [CONFIG.md](docs/CONFIG.md)。

## 架构文档

详细的架构文档请参见 [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md)。

## 贡献

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

MIT License

## 致谢

本项目是 [DeepSeek-TUI](https://github.com/deepseek-ai/DeepSeek-TUI) 的 Python 重写版本。
