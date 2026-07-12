# 插件系统（Plugin System）

> 实现位置：`src/deepseek_tui/integrations/plugins.py`（核心模块）
> 状态：Phase 1–4 已全部落地（含惰性加载、权限映射、Claude Code 互通、marketplace、Workbench GUI）

## 1. 设计定位：插件 vs 技能

| | 技能（Skill） | 插件（Plugin） |
|---|---|---|
| 本质 | 单个 `SKILL.md` 提示词能力 | **打包/分发/组合单元** |
| 内容 | 纯声明式文本 | 可捆绑多个技能 + Hooks + MCP 服务器 |
| 风险 | 无代码执行 | Hooks/MCP 会执行任意进程 |
| 信任 | 始终加载 | 可执行组件需显式信任 |

插件不是"另一种技能"，而是站在技能、Hooks、MCP 三个既有扩展点之上的**包管理层**：一次安装、一个版本号、一个信任开关，交付一整套能力。

## 2. 插件清单（Manifest）

清单查找顺序（第一个命中生效）：

```
<plugin>/.deepseek-plugin/plugin.json
<plugin>/.claude-plugin/plugin.json      ← Claude Code 兼容
<plugin>/.codebuddy-plugin/plugin.json   ← CodeBuddy/WorkBuddy 兼容
<plugin>/plugin.json
```

**清单是可选的**（对齐 Claude Code 规范）：无清单时按目录布局自动合成——
根部 `SKILL.md`（单技能插件），或任意约定组件目录（`skills/` / `commands/` /
`agents/` / `rules/` / `hooks/hooks.json` / `.mcp.json`）。清单存在但省略
`hooks` / `mcpServers` 键时，`./hooks/hooks.json` 与 `./.mcp.json` 作为
默认位置自动发现。

字段跟随 Claude Code 插件格式，社区插件可直接拖入使用：

```json
{
  "name": "my-plugin",
  "version": "1.2.0",
  "description": "示例插件",
  "permissions": ["read", "network"],
  "skills": "./skills",
  "hooks": ["./hooks.json"],
  "mcpServers": {
    "srv": {
      "command": "${PLUGIN_DIR}/bin/server",
      "args": ["--port", "0"],
      "lazy": true
    }
  }
}
```

- `skills`：一个或多个目录，内部按 `SKILL.md` 规则发现，复用技能系统的渐进式披露（系统提示里只占一行）。
- `hooks`：内联对象或指向 hooks 文件的相对路径；事件名必须属于 `LIFECYCLE_EVENTS`。
- `mcpServers`：内联 mcp.json 形状的表，或指向文件的相对路径（经 `servers_from_document()` 解析）。
- `permissions`：声明式权限（见 §5）。
- `${PLUGIN_DIR}`：在 hook 命令和 MCP 的 command/args/env 中展开为插件根目录，插件可携带脚本并可移植地引用。
- 暂不支持的组件键（`outputStyles` / `lspServers`）产生警告而非报错；`commands` / `agents` / `rules` 为已支持的声明式组件。

## 3. 作用域与发现

发现顺序（同名冲突时**前者获胜**）：

1. `<workspace>/.deepseek/plugins/` — 项目级
2. `~/.deepseek/plugins/` — 用户级
3. `~/.claude/plugins/` — Claude Code 互通（只读，见 §6）

每个作用域目录带一个 `installed_plugins.json` lockfile，记录每个插件的 `source` / `version` / `installed_at` / `enabled` / `trusted`。磁盘上存在但不在 lockfile 里的目录（开发中的裸 checkout）按"启用 + 未信任"发现。

## 4. 信任模型

- **技能**：声明式文本，始终加载（与技能系统一致）。
- **Hooks / MCP 服务器**：执行任意进程，**仅在插件被显式信任后激活**。
- 未信任插件携带可执行组件时，发现阶段产生警告并提示 `deepseek-tui plugin trust <name>`。
- GUI 的信任确认弹窗会列出插件声明的权限，供用户判断。

## 5. 权限声明 → ToolCapability 审批映射

manifest 的 `permissions` 归一化后映射到 `ToolCapability`：

| 声明值 | ToolCapability |
|---|---|
| `read` / `read-only` / `read_only` | `READ_ONLY` |
| `write` / `filesystem` / `writes_files` | `WRITES_FILES` |
| `shell` / `exec` / `execute` / `executes_code` | `EXECUTES_CODE` |
| `network` / `net` | `NETWORK` |

审批链路（`tools/approval.py` + `engine/orchestrator/tooling.py`）：

- 插件 MCP 工具执行前，`McpManager.declared_capabilities(qualified_tool_name)` 解析出所属服务器上声明的能力，传给 `approval_request_for_mcp()`。
- 有声明时复用标准的 capability→requirement 阶梯（`requirement_from_capabilities`）：
  - 只声明 `read` → AUTO，**不再触发"所有 MCP 动作一律审批"的兜底提示**；
  - 声明 `write` → SUGGEST；
  - 声明 `shell` → REQUIRED（强制审批）。
- 无声明或声明无法识别 → 保守默认（非只读 MCP 工具一律 REQUIRED）。
- 未知权限字符串在映射时丢弃，但仍原样显示在 CLI/UI 中。

权限声明是**建议性**的（advisory）：它只能放宽提示体验，信任门槛（§4）不受影响——未信任的插件其 MCP 服务器根本不会加载。

## 6. MCP 惰性启动（defer loading）

- `McpServerConfig` 新增 `lazy` 字段；`McpManager.start_all()` 跳过 lazy 服务器（应用启动、后台预热连接都不会拉起进程）。
- 插件贡献的 MCP 服务器**默认 `lazy=true`**（manifest 可写 `"lazy": false` 退出）；`mcp.json` 里的服务器不受影响（默认 eager）。
- 惰性服务器在首次工具发现或首次 `call_tool` 时经 `_ensure_client()` 按需连接——装 10 个插件不会在启动时多出 10 个子进程。

## 7. Claude Code 互通

- 扫描 `~/.claude/plugins`（可用 `CLAUDE_PLUGINS_DIR` 覆盖）：
  1. 优先解析 Claude Code 自己的 `installed_plugins.json`（v1 单记录 / v2+ 列表，按 `installPath` 直接定位，覆盖 `cache/<marketplace>/<plugin>/<version>` 布局）；
  2. 无 lockfile 时退回最深 4 层的有界目录遍历，命中清单即停止下探。
- 这些插件以 `claude` scope 出现，**只读接入**：
  - 启用/信任状态写入我们自己的用户级 lockfile（`~/.deepseek/plugins/installed_plugins.json`），**绝不写入 `~/.claude`**；
  - GUI 不提供更新/删除（文件归 Claude Code 管理）；
  - 同名冲突时 deepseek 自有作用域优先。

## 8. 装载链路（Engine 集成）

`Engine.create()` 是插件宿主（PluginHost），受 `features.plugins` 总开关控制（默认开）：

```
discover_plugins()                    发现（含三作用域 + lockfile 状态）
  └─ collect_contributions()          按信任状态扇出
       ├─ skills        → merge_plugin_skills(SkillRegistry)   工作区技能优先
       ├─ hook_entries  → 合并进 HooksConfig → HookExecutor    hook 名带 "插件名:" 前缀
       └─ mcp_servers   → create_tool_runtime(extra_mcp_servers=…) → McpManager
                          （mcp.json 同名服务器优先；插件服务器名自动加 "插件名-" 前缀）
```

所有变更在**新会话**生效。

## 9. 安装与生命周期

安装源：`github:owner/repo` 或本地目录路径。GitHub 安装复用技能系统加固过的下载/解压路径：

- 20 MiB 大小上限（gzip 炸弹防护）、路径穿越防护、符号链接拒绝；
- staging 目录 + 原子 rename 发布；
- host 白名单（仅 `github.com`）。

生命周期操作（全部写 lockfile）：`install` / `remove` / `update`（按记录的 source 重装，保留 enabled/trusted 状态）/ `enable` / `disable` / `trust` / `untrust`。

## 9.5 两级 Marketplace 模型（对齐 Claude Code）

一个 marketplace 是"广告多个插件的仓库"（`.claude-plugin/marketplace.json`，如
agents-main 的 88 个插件）。分发是两级的：**先注册市场，再按需装单个插件**——
避免全量灌入几十个插件导致上下文膨胀。

```
plugin marketplace add github:wshobson/agents   # 下载并注册（本地路径则原地引用）
plugin marketplace list                          # 已注册市场 + 插件数
plugin marketplace plugins <市场名>              # 市场里有什么
plugin install debugging-toolkit@<市场名>        # 只装这一个
plugin marketplace update <市场名>               # 刷新 GitHub 市场副本
plugin marketplace remove <市场名>               # 注销（绝不删本地 checkout）
```

- GitHub 市场下载到 `~/.deepseek/marketplaces/<name>/`（100 MiB 上限，复用加固的下载/解压路径）；本地市场原地引用，用户的 checkout 是权威副本。
- 注册表：`~/.deepseek/marketplaces/marketplaces.json`。
- `<插件>@<市场>` 装入后 lockfile 的 `source` 记录该 spec，`plugin update` 会重新经市场解析（先 `marketplace update` 再 `plugin update` 即可升级）。
- 三端入口：CLI `plugin marketplace …` / TUI `/plugins marketplace …` / REST `GET|POST /v1/plugins/marketplaces`、`POST /v1/plugins/marketplaces/{name}/update`、`DELETE /v1/plugins/marketplaces/{name}`；Workbench GUI 的 Marketplace 页签支持注册市场、按市场浏览并单个安装。

## 9.6 上下文治理

插件贡献的 commands/agents 清单注入系统提示时有折叠上限
（`PLUGIN_COMPONENT_LIST_LIMIT = 20`）：超限后从"逐项列举 + 描述"降级为
"按插件分组只列名字 + 总数"，防止大量安装（如 agents-main 全家桶 106
commands + 199 agents）撑爆常驻提示。skills 本就渐进式披露（一行/技能），
不受影响；`@plugin:name` 挂载时只展开该插件的能力面。

rules（CodeBuddy `alwaysApply: true` 场景规则）按挂载状态两级披露：

- **未挂载**：不注入规则正文，只按插件折叠为一行摘要（名称 + description +
  `@plugin:<name>` 挂载提示）。全量注入正文既让每轮多付几万 token（实测
  workbuddy 五个插件的 always-apply 规则合计 56K 字符），又会互相稀释——
  模型对 33K 字符的 deep-research 流程指令实测完全无视。
- **挂载后**：只注入该插件自己的规则正文（这正是插件的核心行为，挂载即
  用户显式 opt-in），其他插件的规则完全省略。规则正文中的
  `{{.CurrentDate}}` 会被替换为当前日期。

注意历史行为差异：早期实现是"挂载时抑制所有规则"，导致挂载 deep-research
反而看不到深度研究流程——现已反转为"挂载时才注入自己的规则"。

## 10. Marketplace（精选索引）

- 索引格式：仓库 `plugins-registry/index.json`：

```json
{
  "plugins": {
    "my-plugin": {
      "source": "github:owner/repo",
      "description": "…",
      "version": "1.0.0",
      "components": ["skills", "mcp"],
      "permissions": ["read"]
    }
  }
}
```

- `fetch_plugin_registry()` 复用技能 registry 的 host 白名单（`raw.githubusercontent.com` / `github.com`）与 10s 超时，失败静默返回 `None`。
- Workbench 市场卡片受 `WORKBENCH_FEATURES.pluginMarketplace` 门控（已翻开）；索引不可用时显示安静提示而非报错横幅。

## 11. 三端入口

| 入口 | 能力 |
|---|---|
| CLI `deepseek-tui plugin …` | `list` / `install <spec>@<市场>亦可` / `remove` / `update` / `enable` / `disable` / `trust` / `untrust` / `search` / `doctor` / `new`（脚手架）/ `marketplace add|list|plugins|update|remove` |
| TUI `/plugins`（别名 `/plugin`） | 与 CLI 等价的会话内管理 |
| HTTP API `/v1/plugins` | `GET /v1/plugins`（含 permissions/components/scope）、`GET /v1/plugins/registry`、`POST /v1/plugins/install`、`POST /v1/plugins/{name}/action`（enable/disable/trust/untrust/update）、`DELETE /v1/plugins/{name}` |
| Workbench GUI（Extensions → Plugins） | 已装列表（scope 徽章、信任徽章、权限 chip、开关）、安装弹窗、信任确认（列权限）、市场卡片一键安装 |

阻塞操作（安装/卸载/registry 拉取）在 FastAPI 路由中经 `asyncio.to_thread` 包装。

## 12. 文件地图

| 文件 | 职责 |
|---|---|
| `src/deepseek_tui/integrations/plugins.py` | 核心：manifest 解析、三作用域发现、lockfile、贡献扇出、安装/生命周期、权限映射、Claude 互通、registry |
| `src/deepseek_tui/engine/orchestrator/core.py` | `Engine.create()` 装载插件贡献 |
| `src/deepseek_tui/engine/orchestrator/tooling.py` | MCP 工具审批时注入声明能力 |
| `src/deepseek_tui/tools/approval.py` | `_mcp_requirement` 支持声明能力放宽 |
| `src/deepseek_tui/tools/runtime.py` | `extra_mcp_servers` 注入 McpManager |
| `src/deepseek_tui/mcp/config.py` | `McpServerConfig.lazy` / `.capabilities`；`servers_from_document()` |
| `src/deepseek_tui/mcp/manager.py` | `start_all` 跳过 lazy；`declared_capabilities()` |
| `src/deepseek_tui/config/models.py` | `features.plugins` 总开关 |
| `src/deepseek_tui/cli/app.py` | `plugin` 子命令组 |
| `src/deepseek_tui/tui/commands.py` | `/plugins` 斜杠命令 |
| `src/deepseek_tui/server/routes.py` | `/v1/plugins*` REST 路由 |
| `packages/workbench/.../extensions/PluginsView.tsx` | GUI 视图（列表 + 安装弹窗 + 市场） |
| `packages/workbench/src/shared/workbench-features.ts` | `pluginMarketplace` flag |
| `tests/test_plugins.py` | 单元/集成测试（发现、信任、惰性、权限、Claude、registry、Engine E2E） |
| `tests/contract/test_plugins_api.py` | `/v1/plugins*` 契约测试 |

## 13. 测试与隔离

- `tests/test_plugins.py`：manifest 解析、作用域优先级、lockfile 生命周期、信任门控、`${PLUGIN_DIR}` 展开、权限映射与审批放宽、lazy 默认/退出、`start_all` 跳过、Claude lockfile/遍历双路径、registry 解析、`Engine.create` 端到端。
- `tests/contract/test_plugins_api.py`：REST 全生命周期 + registry 路由 200/503。
- `tests/conftest.py` 有 autouse fixture 将 `CLAUDE_PLUGINS_DIR` 指向临时目录，保证测试不扫描开发机上真实的 `~/.claude/plugins`。
