# 配置文档

## 配置文件位置

DeepSeek-TUI 按以下顺序查找配置文件：

1. 命令行指定的路径：`--config /path/to/config.toml`
2. 项目配置：`$PWD/.deepseek/config.toml`
3. 用户配置：`~/.deepseek/config.toml`
4. 系统配置：`/etc/deepseek/config.toml`

## 配置优先级

配置值的优先级（从高到低）：

1. 命令行参数
2. 环境变量
3. 项目配置文件
4. 用户配置文件
5. 系统配置文件
6. 默认值

## 基础配置

### Provider 和 Model

```toml
# Provider 名称（deepseek, openai, anthropic 等）
provider = "deepseek"

# 默认文本模型
default_text_model = "deepseek-v4-pro"

# 当前使用的模型（覆盖 default_text_model）
model = "deepseek-v4-flash"

# API Key（也可以通过环境变量设置）
api_key = "sk-your-key-here"

# API Base URL
base_url = "https://api.deepseek.com"

# Reasoning effort（low, medium, high）
reasoning_effort = "medium"
```

### 审批策略

```toml
# 审批策略
# - "auto": 自动批准所有操作
# - "on-request": 高风险操作需要批准
# - "never-ask": 从不询问（危险）
approval_policy = "on-request"

# 沙箱模式
# - "workspace-write": 只能在工作区内写入
# - "workspace-read": 只能在工作区内读取
# - "trust": 信任模式，不检查路径
sandbox_mode = "workspace-write"

# 是否允许 shell 命令
allow_shell = true
```

### 路径配置

```toml
# MCP 配置文件路径
mcp_config_path = "~/.deepseek/mcp.json"

# 笔记文件路径
notes_path = "~/.deepseek/notes.txt"

# 内存文件路径
memory_path = "~/.deepseek/memory.md"

# Skills 目录
skills_dir = "~/.deepseek/skills"

# 指令文件列表
instructions = [
    "~/.deepseek/instructions.md",
    ".deepseek/project-instructions.md",
]
```

### 子代理配置

```toml
# 最大并发子代理数
max_subagents = 10
```

## Provider 配置

可以为每个 provider 单独配置：

```toml
[providers.deepseek]
api_key = "sk-deepseek-key"
base_url = "https://api.deepseek.com"
model = "deepseek-v4-pro"
timeout = 120
max_tokens = 4096
temperature = 0.7

[providers.openai]
api_key = "sk-openai-key"
base_url = "https://api.openai.com/v1"
model = "gpt-4"
timeout = 90
max_tokens = 2048
temperature = 0.8

# 额外的 HTTP 头
[providers.deepseek.extra_headers]
"X-Custom-Header" = "value"

# 额外的请求体参数
[providers.deepseek.extra_body]
custom_param = "value"
```

## Profile 配置

Profile 允许快速切换不同的配置组合：

```toml
[profiles.work]
provider = "deepseek"
model = "deepseek-v4-pro"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
allow_shell = true

[profiles.personal]
provider = "deepseek"
model = "deepseek-v4-flash"
approval_policy = "auto"
sandbox_mode = "trust"
allow_shell = true

[profiles.safe]
provider = "deepseek"
model = "deepseek-v4-pro"
approval_policy = "on-request"
sandbox_mode = "workspace-read"
allow_shell = false
```

使用 profile：

```bash
deepseek-tui --profile work
```

## UI 配置

```toml
[ui]
# 颜色方案
color_scheme = "default"

# 是否显示思考过程
show_thinking = true

# 主题
theme = "default"

# 是否自动压缩上下文
auto_compact = false

# 是否显示工具详情
show_tool_details = true

# 语言环境
locale = "auto"  # auto, en, zh-CN, zh-TW

# 默认模式
default_mode = "agent"  # agent, chat

# 最大历史记录数
max_history = 1000

# 是否使用备用屏幕
alternate_screen = "auto"  # auto, always, never

# 是否捕获鼠标
mouse_capture = true
```

## 状态配置

```toml
[state]
# 数据库路径
database_path = "~/.deepseek/state.db"

# 是否自动保存
autosave = true
```

## 重试配置

```toml
[retry]
# 是否启用重试
enabled = true

# 最大重试次数
max_retries = 3

# 初始延迟（秒）
initial_delay = 1.0

# 最大延迟（秒）
max_delay = 60.0

# 指数退避基数
exponential_base = 2.0
```

## 功能开关

```toml
[features]
# 是否启用 shell 工具
shell_tool = true

# 是否启用子代理
subagents = true

# 是否启用网页搜索
web_search = true

# 是否启用 apply_patch
apply_patch = true

# 是否启用 MCP
mcp = true

# 是否启用审批策略
exec_policy = true
```

## 快照配置

```toml
[snapshots]
# 是否启用快照
enabled = true

# 快照最大保留天数
max_age_days = 7
```

## 上下文配置

```toml
[context]
# 是否启用上下文压缩
enabled = false

# 保持原样的最近轮次数
verbatim_window_turns = 16

# L1 阈值（tokens）
l1_threshold = 192000

# L2 阈值（tokens）
l2_threshold = 384000

# L3 阈值（tokens）
l3_threshold = 576000

# Cycle 阈值（tokens）
cycle_threshold = 768000

# Seam 模型
seam_model = "deepseek-v4-flash"
```

## 容量配置

```toml
[capacity]
# 是否启用容量管理
enabled = false

# 低风险最大容量
low_risk_max = 0.50

# 中风险最大容量
medium_risk_max = 0.62

# 严重最小余量
severe_min_slack = -0.25

# 严重违规比例
severe_violation_ratio = 0.40

# 刷新冷却轮次
refresh_cooldown_turns = 6

# 重新规划冷却轮次
replan_cooldown_turns = 5

# 每轮最大重放次数
max_replay_per_turn = 1

# 启用护栏前的最小轮次
min_turns_before_guardrail = 4

# Profile 窗口大小
profile_window = 8
```

## 子代理配置

```toml
[subagents]
# 最大并发子代理数
max_concurrent = 10

# 默认模型
default_model = "deepseek-v4-flash"

# Worker 模型
worker_model = "deepseek-v4-flash"

# Explorer 模型
explorer_model = "deepseek-v4-flash"

# Review 模型
review_model = "deepseek-v4-pro"

# Custom 模型
custom_model = "deepseek-v4-pro"

# 自定义模型映射
[subagents.models]
my_agent = "deepseek-v4-pro"
```

## 环境变量

以下环境变量会覆盖配置文件中的值：

### API Keys

```bash
# DeepSeek API Key
export DEEPSEEK_API_KEY=sk-your-key-here

# OpenAI API Key
export OPENAI_API_KEY=sk-your-key-here

# Anthropic API Key
export ANTHROPIC_API_KEY=sk-your-key-here
```

### Provider 配置

```bash
# Provider
export DEEPSEEK_PROVIDER=deepseek

# Model
export DEEPSEEK_MODEL=deepseek-v4-pro

# Base URL
export DEEPSEEK_BASE_URL=https://api.deepseek.com
```

### 其他配置

```bash
# 审批策略
export DEEPSEEK_APPROVAL_POLICY=on-request

# 沙箱模式
export DEEPSEEK_SANDBOX_MODE=workspace-write

# 是否允许 shell
export DEEPSEEK_ALLOW_SHELL=true

# 数据库路径
export DEEPSEEK_DATABASE_PATH=~/.deepseek/state.db
```

## .env 文件

可以在项目根目录或 `~/.deepseek/` 目录下创建 `.env` 文件：

```bash
# .env
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_APPROVAL_POLICY=auto
```

## 配置示例

### 最小配置

```toml
provider = "deepseek"
api_key = "sk-your-key-here"
```

### 开发配置

```toml
provider = "deepseek"
model = "deepseek-v4-flash"
approval_policy = "auto"
sandbox_mode = "trust"
allow_shell = true

[ui]
show_thinking = true
show_tool_details = true
auto_compact = false

[retry]
enabled = true
max_retries = 3
```

### 生产配置

```toml
provider = "deepseek"
model = "deepseek-v4-pro"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
allow_shell = true

[ui]
show_thinking = false
show_tool_details = false
auto_compact = true

[retry]
enabled = true
max_retries = 5
initial_delay = 2.0
max_delay = 120.0

[state]
database_path = "/var/lib/deepseek/state.db"
autosave = true

[snapshots]
enabled = true
max_age_days = 30
```

### 安全配置

```toml
provider = "deepseek"
model = "deepseek-v4-pro"
approval_policy = "on-request"
sandbox_mode = "workspace-read"
allow_shell = false

[features]
shell_tool = false
subagents = false
web_search = true
apply_patch = false
mcp = false
exec_policy = true
```

## 配置验证

运行以下命令验证配置：

```bash
# 显示当前配置
deepseek-tui --show-config

# 验证配置文件
deepseek-tui --validate-config

# 使用特定配置文件
deepseek-tui --config /path/to/config.toml --show-config
```

## 故障排除

### 配置未生效

1. 检查配置文件路径是否正确
2. 检查配置文件语法是否正确（TOML 格式）
3. 检查环境变量是否覆盖了配置
4. 使用 `--show-config` 查看实际生效的配置

### API Key 未找到

1. 检查环境变量：`echo $DEEPSEEK_API_KEY`
2. 检查配置文件：`cat ~/.deepseek/config.toml`
3. 检查 keyring：`python -c "import keyring; print(keyring.get_password('deepseek-tui', 'deepseek'))"`

### 权限问题

1. 检查配置文件权限：`ls -l ~/.deepseek/config.toml`
2. 检查数据库文件权限：`ls -l ~/.deepseek/state.db`
3. 确保目录存在：`mkdir -p ~/.deepseek`
