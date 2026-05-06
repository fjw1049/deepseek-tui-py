# API 文档

## 核心模块

### 配置系统 (`deepseek_tui.config`)

#### ConfigLoader

加载和合并配置。

```python
from deepseek_tui.config.loader import ConfigLoader

loader = ConfigLoader()
config = loader.load(
    config_path=None,  # 配置文件路径，None 则自动发现
    profile_name=None,  # Profile 名称
    provider=None,  # Provider 覆盖
    model=None,  # Model 覆盖
    workspace=None,  # 工作区路径
    no_project_config=False,  # 是否跳过项目配置
)
```

#### Config

配置模型。

```python
# 访问配置
print(config.provider)  # "deepseek"
print(config.model)  # "deepseek-v4-pro"
print(config.api_key)  # API key（如果配置了）

# 获取 provider 配置
provider_config = config.effective_provider_config()
print(provider_config.api_key)
print(provider_config.base_url)
print(provider_config.timeout)
```

### 密钥管理 (`deepseek_tui.secrets`)

#### SecretsManager

管理 API 密钥。

```python
from deepseek_tui.secrets.manager import SecretsManager

secrets = SecretsManager()

# 解析 API key（优先级：环境变量 > 配置文件 > keyring）
api_key = secrets.resolve_api_key(config, "deepseek")

# 设置 API key 到 keyring
secrets.set_api_key("deepseek", "sk-your-key-here")

# 删除 API key
secrets.delete_api_key("deepseek")

# 列出所有 providers
providers = secrets.list_providers(config)
```

### 持久化层 (`deepseek_tui.state`)

#### Database

SQLite 数据库管理。

```python
from deepseek_tui.state.database import Database
from pathlib import Path

db = Database(Path("~/.deepseek/state.db"))
await db.initialize()

# 获取连接
conn = await db.connect()
```

#### SessionsStore

会话存储。

```python
from deepseek_tui.state.sessions import SessionsStore, SessionRecord

store = SessionsStore(db)

# 创建/更新会话
record = SessionRecord(
    id="session-123",
    title="My Session",
    created_at="2024-01-01T00:00:00Z",
    updated_at="2024-01-01T00:00:00Z",
    transcript_json="[]",
)
await store.upsert(record)

# 获取会话
session = await store.get("session-123")

# 列出所有会话
sessions = await store.list_all()

# 删除会话
await store.delete("session-123")
```

### LLM 客户端 (`deepseek_tui.client`)

#### DeepSeekClient

DeepSeek API 客户端。

```python
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest

client = DeepSeekClient(
    api_key="sk-your-key-here",
    base_url="https://api.deepseek.com",
    timeout_seconds=90.0,
)

# 创建请求
request = MessageRequest(
    model="deepseek-v4-flash",
    messages=[
        Message.user("你好"),
    ],
    max_tokens=1000,
    temperature=0.7,
    stream=True,
)

# 流式调用
async for event in client.stream_chat_completion(request):
    if event.type == "text_delta":
        print(event.delta.text, end="", flush=True)
```

### 工具系统 (`deepseek_tui.tools`)

#### ToolRegistry

工具注册表。

```python
from deepseek_tui.tools import build_default_registry
from deepseek_tui.tools.context import ToolContext
from pathlib import Path

# 创建默认注册表
registry = build_default_registry()

# 获取 API 工具列表（OpenAI 格式）
api_tools = registry.to_api_tools()

# 创建工具上下文
context = ToolContext(
    working_directory=Path.cwd(),
    timeout_ms=5000,
    trust_mode=False,
)

# 执行工具
result = await registry.execute(
    "read_file",
    {"path": "test.txt"},
    context,
)

if result.success:
    print(result.content)
else:
    print(f"Error: {result.error}")
```

#### 自定义工具

```python
from deepseek_tui.tools.base import ToolSpec, ToolResult, ToolCapability
from deepseek_tui.tools.context import ToolContext

class MyTool(ToolSpec):
    def name(self) -> str:
        return "my_tool"
    
    def description(self) -> str:
        return "My custom tool"
    
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input text"},
            },
            "required": ["input"],
        }
    
    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]
    
    async def execute(
        self,
        input_data: dict,
        context: ToolContext,
    ) -> ToolResult:
        input_text = input_data["input"]
        return ToolResult(
            success=True,
            content=f"Processed: {input_text}",
        )

# 注册工具
registry.register(MyTool())
```

### 引擎 (`deepseek_tui.engine`)

#### Engine

对话引擎。

```python
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle

# 创建引擎
engine = Engine(
    client=client,
    registry=registry,
    database=db,
    config=config,
)

# 获取 handle
handle = engine.get_handle()

# 发送消息
from deepseek_tui.engine.ops import SendMessageOp

await handle.send_op(SendMessageOp(content="你好"))

# 监听事件
async for event in handle.events():
    if event.type == "text_delta":
        print(event.text, end="", flush=True)
    elif event.type == "turn_complete":
        break
```

### MCP 集成 (`deepseek_tui.mcp`)

#### McpManager

MCP 管理器。

```python
from deepseek_tui.mcp.manager import McpManager

# 创建 manager
manager = McpManager({
    "my-server": {
        "command": "node",
        "args": ["server.js"],
        "env": {},
    }
})

# 启动服务器
await manager.start_server("my-server")

# 列出工具
tools = await manager.list_tools("my-server")

# 调用工具
result = await manager.call_tool(
    "my-server",
    "tool_name",
    {"arg": "value"},
)

# 停止服务器
await manager.stop_server("my-server")
```

### 审批策略 (`deepseek_tui.execpolicy`)

#### ExecPolicyEngine

审批策略引擎。

```python
from deepseek_tui.execpolicy.engine import ExecPolicyEngine
from deepseek_tui.tools.base import ToolCapability

engine = ExecPolicyEngine(
    approval_policy="on-request",  # auto, on-request, never-ask
)

# 评估工具调用
request = engine.evaluate(
    tool_name="exec_shell",
    capabilities=[ToolCapability.EXECUTES_CODE],
)

if request is None:
    # 自动批准
    print("Auto-approved")
else:
    # 需要用户批准
    print(f"Approval needed: {request.reason}")
```

### TUI 界面 (`deepseek_tui.tui`)

#### DeepSeekTUI

TUI 应用。

```python
from deepseek_tui.tui.app import DeepSeekTUI

app = DeepSeekTUI(handle=engine_handle)
app.run()
```

### LSP 集成 (`deepseek_tui.lsp`)

#### LspManager

LSP 管理器。

```python
from deepseek_tui.lsp import LspManager, LspConfig

config = LspConfig(
    enabled=True,
    poll_after_edit_ms=5000,
    max_diagnostics_per_file=20,
    include_warnings=False,
)

manager = LspManager(config)

# 获取诊断
diagnostics = await manager.diagnostics_for(
    path=Path("test.py"),
    content="print('hello')",
    seq=1,
)

# 渲染诊断
from deepseek_tui.lsp import render_blocks
print(render_blocks(diagnostics))
```

### Hooks 系统 (`deepseek_tui.hooks`)

#### HookDispatcher

事件分发器。

```python
from deepseek_tui.hooks import (
    HookDispatcher,
    StdoutHookSink,
    JsonlHookSink,
    WebhookHookSink,
    ResponseStartEvent,
)

dispatcher = HookDispatcher()

# 添加 sinks
dispatcher.add_sink(StdoutHookSink())
dispatcher.add_sink(JsonlHookSink(Path("hooks.jsonl")))
dispatcher.add_sink(WebhookHookSink("https://example.com/webhook"))

# 发送事件
await dispatcher.emit(ResponseStartEvent(response_id="resp-123"))
```

## 类型定义

### Message

```python
from deepseek_tui.protocol.messages import Message, Role

# 创建消息
msg = Message.user("Hello")
msg = Message.assistant("Hi there")
msg = Message.system("You are a helpful assistant")

# 访问内容
for block in msg.content:
    if block.type == "text":
        print(block.text)
    elif block.type == "thinking":
        print(block.thinking)
    elif block.type == "tool_use":
        print(f"Tool: {block.name}, Input: {block.input}")
```

### StreamEvent

```python
from deepseek_tui.protocol.responses import StreamEvent, StreamEventType

# 事件类型
StreamEventType.TEXT_DELTA  # 文本增量
StreamEventType.THINKING_DELTA  # 思考增量
StreamEventType.TOOL_USE  # 工具调用
StreamEventType.DONE  # 完成
```

### ToolResult

```python
from deepseek_tui.tools.base import ToolResult

result = ToolResult(
    success=True,
    content="Result content",
    error=None,
    metadata={"key": "value"},
)
```

## 错误处理

### ToolError

```python
from deepseek_tui.tools.base import ToolError

try:
    result = await registry.execute("tool_name", {}, context)
except ToolError as e:
    print(f"Tool error: {e}")
```

### ConfigError

```python
from deepseek_tui.config.errors import InvalidConfigError, UnknownProfileError

try:
    config = loader.load(profile_name="unknown")
except UnknownProfileError as e:
    print(f"Profile not found: {e}")
```

## 最佳实践

### 1. 使用异步上下文

所有 I/O 操作都是异步的：

```python
import asyncio

async def main():
    db = Database(Path("state.db"))
    await db.initialize()
    
    # 使用数据库
    store = SessionsStore(db)
    sessions = await store.list_all()

asyncio.run(main())
```

### 2. 正确处理工具上下文

```python
# 创建工具上下文时指定工作目录
context = ToolContext(
    working_directory=Path.cwd(),
    trust_mode=False,  # 启用沙箱检查
    timeout_ms=5000,  # 设置超时
)

# 工具会自动检查路径是否在工作目录内
result = await registry.execute("read_file", {"path": "../etc/passwd"}, context)
# 如果 trust_mode=False，这会抛出错误
```

### 3. 使用工厂函数

```python
# 使用工厂函数创建默认配置
registry = build_default_registry()

# 而不是手动注册每个工具
registry = ToolRegistry()
registry.register(ReadFileTool())
registry.register(WriteFileTool())
# ...
```

### 4. 流式处理

```python
# 使用异步迭代器处理流式响应
async for event in client.stream_chat_completion(request):
    if event.type == "text_delta":
        print(event.delta.text, end="", flush=True)
```

### 5. 错误恢复

```python
from deepseek_tui.client.retry import RetryConfig

# 配置重试
config = RetryConfig(
    enabled=True,
    max_retries=3,
    initial_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
)

# 客户端会自动重试失败的请求
```
