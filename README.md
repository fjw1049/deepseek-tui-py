# DeepSeek-TUI Python

基于 [DeepSeek-TUI](https://github.com/deepseek-ai/DeepSeek-TUI)（Rust）的 Python 行为复刻版——一个功能完整的终端 AI Agent。

## 特性

- **完整的 LLM 对话引擎** — 流式输出、工具调用、多轮推理、容量控制、自动压缩
- **53+ 内置工具** — 文件操作、Shell、Git、Web、GitHub、任务管理、子代理等
- **现代 TUI 界面** — 基于 Textual：欢迎卡 + Markdown 渲染 + Diff 查看 + 右侧实时面板（Todos / Tasks / Agents）+ 三列状态条（mode·model·cost / 快捷键 chord / cache%·worked·ctx）
- **会话计费可视** — `cache 67%` chip 实时显示 prompt cache 命中率，$/¥ 双币 cumulative cost 自动累计（v4-pro 限时折扣自动识别）
- **多会话持久化** — SQLite 存储，支持会话恢复、fork、检查点
- **审批策略系统** — ExecPolicy + CommandSafety 4 级安全管道
- **MCP/LSP 集成** — 外部工具扩展 + 代码编辑后自动诊断
- **Hooks 事件系统** — 生命周期事件分发与日志
- **Cycle/Seam 上下文管理** — 长会话自动归档 + Flash 摘要 + prefix cache 友好
- **App Server** — FastAPI HTTP/SSE 接口，支持远程调用

## 快速开始

### 环境要求

- Python 3.10+
- macOS / Linux

### 安装

```bash
git clone https://github.com/fjw1049/deepseek-tui-py.git
cd deepseek-tui-py

# 推荐使用 uv（快速）
uv venv .venv --python 3.12
uv pip install -e ".[dev]"

# 或使用 pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

#### 精确版本复现（CI / 协作）

`requirements.lock` 是用本仓库当前 `.venv` `uv pip freeze` 出来的精确版本快照，
跟 1323 个 parity 测试通过的环境一一对应。任何机器从空白 venv 还原同一环境：

```bash
# 推荐 uv（推送过 PyPI 镜像后秒级安装）
uv venv .venv --python 3.12
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  uv pip install -r requirements.lock
uv pip install -e .

# 或 pip
python -m venv .venv
source .venv/bin/activate
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.lock
pip install -e .

# 验证
pytest tests -q   # 应该 1323 passed
```

依赖文件分工：
- `requirements.txt` — 仅 runtime，floor 版本
- `requirements-dev.txt` — runtime + dev（pytest/mypy/ruff）
- `requirements.lock` — 全部依赖的精确版本（推荐 CI 使用）

升级依赖后用 `uv pip freeze | grep -v '^-e' > requirements.lock` 重新生成 lock。

### 配置 API Key

所有运行时数据（config、sessions、tasks、logs、state.db、skills、secrets）默认放在**项目根目录下的 `./.deepseek/`**，每个 clone 互相独立、不会污染（这是 2026-05-11 之后的设计，原来是 `~/.deepseek/`）。该目录已加入 `.gitignore`，不会被提交。

```bash
# 方式 1：环境变量（推荐，跨项目复用）
export DEEPSEEK_API_KEY=sk-your-key-here

# 方式 2：项目本地配置文件
mkdir -p .deepseek
cp config.example.toml .deepseek/config.toml
# 编辑 api_key 字段

# 方式 3：项目本地 keyring（默认走文件 keyring，落在 .deepseek/secrets/）
deepseek-tui login --provider deepseek --api-key sk-your-key-here
```

#### 用别处的 `.deepseek` 目录（共享配置）

如果想多个项目共用一份配置（例如复用历史 sessions），用 `DEEPSEEK_HOME` 环境变量指向想用的目录：

```bash
export DEEPSEEK_HOME=~/.deepseek-shared
deepseek-tui
```

`DEEPSEEK_HOME` 优先级最高，会覆盖项目本地路径。

#### 从旧版 `~/.deepseek/` 迁移

```bash
# 把旧的全局配置/会话拷到当前项目（按需挑要的子目录）
cp -r ~/.deepseek/config.toml ./.deepseek/
cp -r ~/.deepseek/sessions   ./.deepseek/
cp -r ~/.deepseek/skills     ./.deepseek/
# tasks 一般不要拷，旧版可能有僵尸任务
```

### 运行

最简单的方式 —— 一条命令搞定 sync + 启动：

```bash
bash scripts/start-service.sh              # 日常：增量 sync + 启动 TUI
bash scripts/start-service.sh --fresh      # 清空 .venv 后重建再启动
bash scripts/start-service.sh -- --help    # `--` 后的参数透传给 deepseek-tui
```

脚本里内置了几件事：

- `uv sync --inexact` 增量同步，不会剪掉你已装的 dev 依赖（pytest / ruff / mypy 等）
- `uv run --no-sync` 启动 TUI，避免冗余的二次同步
- `pyproject.toml` 里 `[[tool.uv.index]]` 默认走清华 TUNA 镜像，国内拉包秒级

需要手动控制每一步时（CI / 排查依赖问题）：

```bash
cd deepseek-tui-py
uv sync                    # 同步依赖 + 本地包（editable 安装）
source .venv/bin/activate  # 之后 shell 内可直接用 deepseek-tui
```

常用命令：

```bash
# 启动交互式 TUI（默认）
deepseek-tui

# 健康检查（确认依赖、API key、模型配置都就绪）
deepseek-tui doctor

# 单次对话（non-interactive，结果走 stdout）
deepseek-tui -p "你好"

# 启动 App Server（HTTP + SSE，默认监听 127.0.0.1:8787）
deepseek-tui serve --host 127.0.0.1 --port 8787

# 启动 App Server（stdio JSON-RPC，给上游 agent 调用）
deepseek-tui serve --stdio

# 用作 MCP server（其他客户端通过 stdio JSON-RPC 调本仓库的工具）
deepseek-tui mcp-server

# 恢复 / fork 历史会话
deepseek-tui resume <session-id>
deepseek-tui fork   <session-id>

# 查看 / 切换登录态
deepseek-tui auth status
deepseek-tui login --provider deepseek --api-key sk-...
```

## 项目结构

```
src/deepseek_tui/
├── config/          # 配置系统 + Provider 注册表
├── secrets/         # 密钥管理（keyring / env / config 三级优先级）
├── protocol/        # 消息协议（Message / Request / Response / Events）
├── client/          # LLM 客户端（流式 SSE + 重试）
├── engine/          # 核心引擎
│   ├── engine.py        # Engine 主体 + turn loop
│   ├── context.py       # 上下文预算 + token 估算
│   ├── capacity.py      # 容量控制 + 风险等级
│   ├── compaction.py    # 消息压缩 + LLM 摘要
│   ├── dispatch.py      # 工具调度
│   ├── tool_catalog.py  # 工具目录管理
│   ├── cycle_manager.py # Cycle 归档 + briefing
│   ├── seam_manager.py  # Seam 层级摘要（prefix cache 友好）
│   └── working_set.py   # 活跃文件追踪
├── tools/           # 53+ 工具实现
├── execpolicy/      # 执行策略 + 命令安全分析
├── state/           # SQLite 持久化 + SessionManager
├── tui/             # Textual TUI 界面
│   ├── app.py           # 主应用
│   └── widgets/         # Sidebar / Help / Pickers / Markdown / Diff
├── mcp/             # MCP 客户端（stdio + SSE transport）
├── lsp/             # LSP 集成（post-edit 诊断）
├── hooks/           # Hooks 事件系统
├── app_server/      # FastAPI HTTP 服务
├── cli/             # Typer CLI（22 子命令）
└── prompts/         # 17 个 prompt 模板
```

## 工具系统

### 文件操作
`read_file` · `write_file` · `edit_file` · `list_dir` · `multi_edit`

### 搜索
`grep_files` · `file_search` · `project_map`

### Shell
`exec_shell` · `exec_shell_cancel` · `exec_shell_wait` · `exec_shell_interact`

### Git
`git_status` · `git_diff` · `git_log` · `git_show` · `git_blame`

### Web & GitHub
`web_search` · `fetch_url` · `github_issue_context` · `github_pr_context` · `github_comment` · `github_close`

### 任务 & 子代理
`task_create` · `task_list` · `task_read` · `task_cancel` · `agent_create` · `agent_send` · `agent_read`

### 知识管理
`remember` · `note` · `update_plan` · `recall_archive` · `skill_load` · `review` · `rlm_query`

### 其他
`apply_patch` · `diagnostics` · `todo_read` · `todo_write` · `automation_run`

## 配置

配置文件：`~/.deepseek/config.toml`

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
database_path = "~/.deepseek/state.db"
autosave = true
```

## 许可证

MIT License
