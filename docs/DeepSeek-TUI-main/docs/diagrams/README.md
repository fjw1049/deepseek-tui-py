# DeepSeek-TUI 架构图表文档

本目录包含 DeepSeek-TUI 项目的完整架构可视化文档，深入展示每个子系统的工作原理和数据流。

## 📊 图表列表

### 00. [系统总览](./00-system-overview.html)
完整的端到端流程，展示所有 12 个子系统如何协作：用户输入 → TUI → Engine → LLM → 流式响应 → 工具执行 → 渲染。

### 01. [配置系统](./01-config-system.html)
- 配置加载优先级链（CLI 参数 → 环境变量 → config.toml → 默认值）
- Profile 合并策略
- Provider 配置
- 环境变量映射
- 运行时更新机制

### 02. [CLI 启动流程](./02-cli-startup.html)
- main() 入口点
- 参数解析（clap）
- 配置加载
- Secrets 初始化
- State 初始化
- TUI/AppServer 启动

### 03. [TUI 事件循环](./03-tui-event-loop.html)
- crossterm 事件捕获（48ms/24ms 轮询）
- AppMode 状态机（Agent/Yolo/Plan）
- 用户输入处理
- 渲染管线（ratatui）
- StreamingState 管理

### 04. [Engine 引擎](./04-engine-agent-loop.html)
- Op 调度
- 系统提示构建
- MessageRequest 构建
- Turn Loop 编排
- 工具执行
- 响应聚合
- 容量控制

### 05. [LLM 客户端 & 流式处理](./05-llm-client-streaming.html)
- HTTP 请求构建
- SSE 流解析
- ContentBlock 跟踪（Text/Thinking/ToolUse）
- 超时机制（90s 空闲 / 30min 总计）
- 重试逻辑（2 次透明重试 / 5 次错误重试）
- Delta 分发

### 06. [工具系统](./06-tool-system.html)
- ToolRegistry 注册表
- 工具查找
- 能力检查（ReadOnly/WritesFiles/ExecutesCode/Network）
- 执行流程
- 超时控制
- 结果返回

### 07. [MCP 集成](./07-mcp-integration.html)
- 服务器发现（mcp.json）
- 启动流程
- JSON-RPC 2.0 通信
- 工具过滤（allow/deny）
- 名称编码（mcp__server__tool）
- 工具调用

### 08. [审批 & 执行策略](./08-approval-execpolicy.html)
- ExecPolicyEngine 评估
- 风险分级（Benign/Destructive）
- 审批请求
- UI 对话框
- 决策缓存
- 会话审批

### 09. [Hooks & 持久化](./09-hooks-state.html)
- 事件广播（HookDispatcher）
- Sink 分发（Stdout/JSONL/Webhook）
- SQLite 会话存储
- Checkpoint 机制
- 崩溃恢复
- 离线队列

### 10. [Secrets & Agent 注册](./10-secrets-agent.html)
- 密钥解析优先级（环境变量 → OS Keyring → config.toml）
- 模型注册表
- Provider 映射
- 能力查询

## 🎨 设计特性

- **纯 HTML/CSS/SVG**：无外部依赖，可离线查看
- **深色主题**：专业的深色背景（#1a1a2e）
- **颜色编码**：每个子系统独特的颜色标识
- **交互式流程图**：SVG 箭头展示数据流
- **可折叠详情**：使用 `<details>` 标签展开/收起详细信息
- **响应式设计**：支持不同屏幕尺寸
- **导航栏**：快速跳转到其他图表
- **中文标注**：所有标签和说明均为中文

## 📖 使用方法

### 在浏览器中查看

```bash
# 打开索引页面
open docs/diagrams/index.html

# 或直接打开特定图表
open docs/diagrams/00-system-overview.html
```

### 推荐浏览顺序

1. **初学者**：
   - 00-system-overview.html（系统总览）
   - 02-cli-startup.html（启动流程）
   - 03-tui-event-loop.html（TUI 事件循环）
   - 04-engine-agent-loop.html（Engine 引擎）

2. **深入理解**：
   - 05-llm-client-streaming.html（LLM 客户端）
   - 06-tool-system.html（工具系统）
   - 08-approval-execpolicy.html（审批策略）

3. **扩展与集成**：
   - 07-mcp-integration.html（MCP 集成）
   - 09-hooks-state.html（Hooks & 持久化）
   - 10-secrets-agent.html（Secrets & Agent）

4. **配置与定制**：
   - 01-config-system.html（配置系统）

## 📊 统计信息

- **图表数量**：11 个详细图表
- **子系统数量**：12 个核心子系统
- **总文档大小**：382KB
- **代码引用**：精确到文件路径和行号
- **流程步骤**：每个子系统 8-12 个详细步骤

## 🔍 关键文件位置

所有图表都引用了实际的源代码位置：

- `crates/tui/src/tui/ui.rs` - TUI 事件循环（7055 行）
- `crates/tui/src/client.rs` - HTTP 客户端（2320 行）
- `crates/tui/src/core/engine.rs` - Engine 引擎（1797 行）
- `crates/tools/src/lib.rs` - 工具系统
- `crates/mcp/src/lib.rs` - MCP 集成
- `crates/execpolicy/src/lib.rs` - 执行策略
- `crates/hooks/src/lib.rs` - Hooks 系统
- `crates/state/src/lib.rs` - 持久化
- `crates/config/src/lib.rs` - 配置系统
- `crates/secrets/src/lib.rs` - 密钥管理
- `crates/agent/src/lib.rs` - Agent 注册

## 🎯 适用场景

- **新手入门**：快速理解 DeepSeek-TUI 的整体架构
- **代码贡献**：了解各子系统的实现细节和交互方式
- **问题排查**：追踪数据流和定位问题根源
- **架构设计**：参考设计模式和最佳实践
- **文档编写**：作为技术文档的可视化补充

## 📝 更新日志

- **2026-05-04**：初始版本，包含所有 11 个图表
  - 基于 DeepSeek-TUI v0.8.8 代码库
  - 深度分析所有 14 个 workspace crates
  - 精确到行号的代码引用

## 🤝 贡献

如果发现图表中的错误或需要补充内容，请：

1. 检查对应的源代码文件
2. 提交 Issue 或 Pull Request
3. 在 PR 中说明需要更新的图表和具体内容

## 📄 许可证

与 DeepSeek-TUI 项目保持一致。
