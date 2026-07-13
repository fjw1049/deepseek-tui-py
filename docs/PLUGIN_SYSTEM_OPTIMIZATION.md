# 插件系统优化方案（Plugin System Optimization）

> 状态：设计稿，待用户确认后实施
> 基线：当前实现见 [PLUGIN_SYSTEM.md](./PLUGIN_SYSTEM.md)（Phase 1–4 已落地）
> 依据：Cursor 调研结论（贡献层 + 惰性激活 + 场景模式三层）+ 2026-07-13 代码核实

## 0. 一句话目标

把现在"挂载=插件的全部意义"的单路径模型，拆成业界主流的**三层模型**：Plugin 贡献层（主）/ Activation 按需激活 / Scenario Mode 场景模式（可选）。**不重写，外科式改造**。

---

## 1. 为什么要优化

### 1.1 当前实现的真实状态（已核实 file:line）

| 能力 | 落点 | 状态 |
|---|---|---|
| 清单解析 | `integrations/plugins.py:398` | ✅ 认 .deepseek/.claude/.codebuddy-plugin |
| 统一装配 | `core.py:591-606` Engine.create | ✅ skills/hooks/mcp/commands/agents/rules 扇出 |
| commands/agents 进 prompt | `prompts.py:147` 折叠(≥20降级) | ⚠️ 偏重，应更薄 |
| rules 两模式 | `prompts.py:241-291` | ✅ inactive 摘要 / mounted 全文 |
| @plugin 挂载 | `helpers.py:105-122` + `core.py:330-358` | ✅ 实现对，**命名错** |
| MCP lazy + trust | `plugins.py:1152-1153` | ✅ |
| 跨生态兼容 | `plugin_compat.py` | ✅ Claude/CodeBuddy |
| marketplace 生命周期 | `plugins.py:1580-2044` + lockfile | ✅ |

### 1.2 七个问题（按严重度）

1. **概念混淆**：`@plugin:name` 挂载被当插件主语义，实为 Scenario Mode。轻量插件不应走挂载独占。
2. **plugin agents 没真激活**：`PluginAgent.model/tools` 是 advisory（`plugins.py:695-712`），`agent_spawn` 不注入人设。Layer B 核心缺口。
3. **lazy MCP + 挂载白名单竞态**：`core.py:408-410` 调 `_server_tool_names()`，lazy server 未 spawn -> 空集 -> MCP 工具挂载后首次不可见。**真实 bug**。
4. **commands/agents 进 prompt 偏重**：有折叠但本质是预灌清单。
5. **rules `always_apply` 语义错位**：名不副实，`always_apply=False` 直接丢，无"仅场景内生效"语义。
6. **缺 hooks 可观测 UI**：前端只有 trust badge，无触发日志。
7. **Scenario 内 hooks 不隔离**：挂载时所有 trusted 插件 hooks 全局跑。

### 1.3 和 Cursor 调研的两点分歧（保留判断）

- **commands 预灌清单**：调研说不要预灌。我认为插件数少时折叠清单对模型决策有帮助，阈值化比一刀切务实。当前折叠机制方向对，不推翻。
- **@plugin 后端实现**：调研把独占加载全归 Scenario。我认为后端 `_active_plugin` + 工具白名单 + rules 全文注入的代码路径本身没错，错在命名和适用范围。保留代码，改 UI 定位。

---

## 2. 三层模型

| 层 | 职责 | 触发 | 进 prompt 什么 |
|---|---|---|---|
| **A. 贡献层**（主，默认态） | install+enable+trust 后常驻贡献 | 启用即生效 | 极薄目录：插件名+描述+组件计数 |
| **B. 按需激活** | 用到才展开 | `/plugin:cmd`、`agent_spawn`、`load_skill`、首次 MCP 调用 | 命中才灌正文 |
| **C. 场景模式**（可选） | rules 重的工作流接管 | 显式 `@plugin:name` 进入 | 该包 rules 全文 + 工具收窄 |

**核心原则**：装上 = 可贡献，不等于灌上下文。大多数插件（调试命令包、repo MCP、slash command 包）只走 A+B，不需要进 C。只有 rules 很重、要"整段接管工作流"的包才走 C。

---

## 3. 生命周期与状态

### 3.1 磁盘状态（lockfile `installed_plugins.json`，现状保留）

```
not_installed -> installed -> enabled -> trusted
                                   ↑
                              （hooks/MCP 装配门槛）
```

- **installed**：落盘 `~/.deepseek/plugins/<name>/`，写 lockfile `{source, version, installed_at, enabled:false, trusted:false}`
- **enabled**：`enabled=true`，Engine.create 时进入 Layer A 装配（skills/commands/agents/rules 摘要进 prompt）
- **trusted**：`trusted=true`，hooks/MCP 才装配（可执行组件需显式信任）
- **disabled**：`enabled=false`，从贡献态摘除，磁盘保留

### 3.2 会话级状态（Engine 内存，现状保留 + 语义澄清）

- `self._active_plugin: str | None`（`core.py:206`）
- `None` = Layer A 默认贡献态
- `<plugin_name>` = Layer C 场景模式

**语义澄清**：字段名保留（改字段成本高），但 UI/文档/注释统一改叫"场景模式（scenario）"，不再叫"挂载/active plugin"。

---

## 4. Layer A 贡献层具体行为

### 4.1 skills（现状保留）
- 装配：`merge_plugin_skills()` 合并进 workspace SkillRegistry（`core.py:646-648`）
- prompt：一行目录 `name: description`
- 激活：agent 自主调 `load_skill` 读全文（渐进披露）

### 4.2 commands（要改：P4）
- 装配：`engine.plugin_commands` dict，key=`<plugin>:<stem>`（`core.py:711-713`，保留）
- **现状**：prompt 列清单，>20 条折叠成按插件分组只列名
- **改成**：prompt 只留一行索引"已装 N 个插件命令，用 `/plugin:<plugin>:<cmd>` 调用"。命令 body 在模型实际调用 `/plugin:...` 时展开（Layer B）
- **阈值**：插件数 <5 且命令总数 <10 时，保留折叠清单（对模型决策有帮助）；超阈值切一行索引

### 4.3 agents（要改：P2 核心）
- 装配：`engine.plugin_agents` dict + `tool_context.metadata["plugin_agents"]`（`core.py:714-718`，保留）
- **现状问题**：`PluginAgent.model/tools` 是 advisory，`agent_spawn` 不注入人设--清单进了 prompt 但 spawn 不到真角色
- **改成**：
  - `agent_spawn type=plugin:<plugin>:<agent>` 时，从 metadata 取该 agent 的 `agents/*.md` body，作为 sub-agent 的 role 文本注入（走 custom 类型的 role 追加路径，不换 system prompt 架构）
  - `PluginAgent.tools` 非空时，spawn 套工具白名单（复用 skill allowed-tools 收窄逻辑 `core.py:970-974`）
  - prompt 里 agents 也只留一行索引，不预灌人设正文

### 4.4 rules（要改：P3）
- 装配：`engine.plugin_rules` 列表（`core.py:719-721`，保留）
- **现状问题**：`always_apply=True` 被收集但 inactive 时只灌摘要（名不副实）；`always_apply=False` 直接丢
- **改成**：
  - `always_apply=True` + inactive = 摘要一行进 prompt（现状不变）
  - `always_apply=True` + mounted = 全文进 prompt（现状不变）
  - `always_apply=False` = 不进默认摘要，但 **mounted 时也灌全文**（当前是丢，改成"仅场景内生效"）
  - `always_apply` 真正语义 = "是否进默认贡献目录"

### 4.5 hooks（现状保留 + P5 可观测）
- 装配：`plugin_contribs.hook_entries` 追加到 `cfg.hooks.hooks`，`build_lifecycle_hook_executor` 合并（`core.py:608-619`）
- 来源：plugin.json 的 `hooks` 字段（路径或内联），不从 SKILL.md frontmatter 读
- trust 门槛：有 hooks/MCP 但 `not plugin.trusted` 跳过收集并发 warning（`plugins.py:915-921`）
- 跨生态：Claude/CodeBuddy CamelCase 事件名 + matcher 工具名翻译（`plugin_compat.py`）
- **补**：hook 执行时往 SSE 推 `hook_fired` 事件

### 4.6 MCP（现状保留 + P0 修竞态）
- 装配：plugin servers prepend 进全局 manager，mcp.json 冲突时优先（`tools/runtime.py:428-429`）
- lazy：`server.lazy = True`，`start_all` 跳过，首次工具调用才 spawn
- **修竞态**：`_active_plugin_whitelist()`（`core.py:408-410`）当前调 `_server_tool_names()` 取工具名，lazy server 没 spawn 时返回空集。改成**按 server 名白名单**（挂载该插件 = 该插件声明的 MCP server 全量放行），或挂载时先触发该 server 的 discovery

---

## 5. Layer B 按需激活具体行为

| 触发 | 加载什么 | 现状 |
|---|---|---|
| `/plugin:<plugin>:<cmd>` | 展开 command body 执行 | 要补 |
| `agent_spawn type=plugin:<plugin>:<agent>` | 注入 agent 人设 + tools 白名单 | 要补（P2） |
| 模型选 skill | `load_skill` 读全文 | ✅ |
| 首次用某 MCP 工具 | 拉起 lazy server | ✅ |
| SessionStart 等事件 | 跑已信任 hooks | ✅ |

**P2 是 Layer B 核心**：让 plugin agents 从"prompt 里的空广告"变成"可真正 spawn 的角色"。约 80-120 行，落点：
- `SubAgentType` 已有 `custom` 类型（`types.py:32`），plugin agent 走这个
- spawn 时从 `tool_context.metadata["plugin_agents"]` 取 body，追加进 role 文本（`loop.py:138` 的 label->role 路径）
- `tools` 非空时套用工具收窄

---

## 6. Layer C 场景模式具体行为

**现状实现正确，改命名和适用范围**。

### 6.1 进入（`@plugin:<name>` 或 UI 点"进入场景"）
- `set_active_plugin()`（`core.py:330-358`）存 `self._active_plugin`
- 工具收窄：`_active_plugin_whitelist()`（`core.py:372-411`）= 读基础 + 该插件 skills allowed-tools + 该插件 MCP server（修竞态后按 server 名）
- rules：只灌被挂载插件的 rule bodies 全文（`prompts.py:262-277`），含 `always_apply=False` 的（P3 改动）
- components 清单抑制：挂载时不重复列 commands/agents（`core.py:445`）
- 读 root 放行：插件目录加入 `extra_read_roots`（`core.py:1349-1351`）

### 6.2 退出（`@plugin:off` 或 UI 点"退出场景"）
- 清空 `_active_plugin`（`core.py:336-338`）
- 回到 **Layer A 基线贡献态**（所有 enabled 插件贡献表重新可见），不是"出厂设置"

### 6.3 新增（P5 可选）
- `isolate_hooks` per-plugin 配置：挂载时只跑当前插件 hooks，默认关闭
- 场景模式专属入口：UI 在插件详情页标"场景插件"标签，引导用 `@plugin` 进入；轻量插件不展示这个入口

---

## 7. prompt 结构（优化后）

```
## Installed Plugins (contributing)
- <plugin1>: <description> [skills:3 commands:2 agents:1 rules:4]
- <plugin2>: <description> [skills:1 mcp:2]
Use /plugin:<plugin>:<cmd> for commands; agent_spawn type=plugin:<plugin>:<agent> for agents.

## Plugin Rules (inactive)
- <plugin1 rules>: <summary, 120 chars>
- <plugin2 rules>: <summary>
Enter scenario with @plugin:<name> to activate full rules.

## Active Scenario (only when _active_plugin set)
### <plugin> Rules (authoritative)
<full rule body, including always_apply=False ones>

### Available Skills (narrowed)
- <skill>: <description>
```

**对比当前**：
- `## Plugin Commands & Agents`：从"逐条/折叠清单"改成"一行索引 + 调用方式提示"（P4，阈值化）
- `## Plugin Rules (inactive)`：现状对，保留
- `## Active Plugin`：现状对，改名 `## Active Scenario`
- `always_apply=False` 的 rules：当前丢，改成 mounted 时进 `## Active Scenario`（P3）

---

## 8. GUI 前端交互

### 8.1 插件页（PluginsView，`PluginsView.tsx:20`）

**三个 tab**：已装 / 市场 / 场景（场景 tab 展示当前挂载 + 快速切换）

**已装列表**（`InstalledPluginsPanel.tsx:80`）每行：
- name / version / scope / trust / permissions
- **贡献态可视化（要改）**：当前只显示 `Skills · Hooks · MCP` 三个 bool。改成带计数：`Skills:3 · Commands:2 · Agents:1 · Rules:4 · Hooks:on · MCP:2`
- 操作：Trust/Untrust、Enable/Disable、Update、Remove
- 点击行展开详情：列出该插件贡献的 skills/commands/agents/rules 具体清单

**hooks 可观测面板（要补，P5）**：
- "最近触发的 hooks"日志面板，从 SSE `hook_fired` 事件来
- 每条：时间、插件名、事件类型、命令、exit_code

**市场 tab**：现状保留（已注册 marketplace 列表 + 远程 registry 浏览）

### 8.2 Composer 交互（`FloatingComposer.tsx`）

**默认贡献态**（大多数插件）：
- 不需要前缀，agent 自主调用 skills/commands/agents
- 用户手动触发：输入 `/` 触发 slash 菜单，列出所有 `/plugin:<plugin>:<cmd>`
- `agent_spawn type=plugin:...` 由模型自主调用

**场景模式入口（要改命名）**：
- 当前 Composer `+` 子菜单选插件后 `setFocusPlugin(name)`，发送时前缀 `@plugin:${focusPlugin}`（`FloatingComposer.tsx:742,1063`）--交互保留，**UI 文案改**：
  - 菜单项从"挂载插件"改成"进入场景（<plugin>）"
  - 只对"场景插件"标签的展示这个入口，轻量插件不展示
- 挂载后 Composer 顶部显示场景 badge（`:1879` 保留）
- 退出：发 `@plugin:off`（`:1901` 保留）或点 badge 旁"退出场景"

### 8.3 状态反馈
- 场景状态：从 STATUS item `metadata.active_plugin` 解析（`deepseek-runtime.ts:526`），存 `activePlugin`（`chat-store.ts:1135`）
- MCP lazy 启动：首次用 MCP 工具时 loading 提示（可选）
- hooks 触发：toast 或角标提示

### 8.4 前端 IPC（现状保留）
- 所有插件操作走 `runtime:request` 代理 `/v1/plugins*` HTTP
- 新增：订阅 SSE `hook_fired` 事件流

### 8.5 插件详情页（要补）
点击已装列表某行进入详情：
- 基本信息：name/version/description/author/source
- 贡献清单：skills/commands/agents/rules 各一个 section
- hooks：列出已注册事件+命令，标 trust
- MCP：列出声明 server，标 lazy/trust
- 操作：trust/untrust/enable/disable/update/remove

---

## 9. 修复优先级

| 优先级 | 改动 | 落点 | 工作量 |
|---|---|---|---|
| **P0** | 修 MCP 白名单竞态 | `core.py:408-410` | ~20 行 |
| **P1** | 概念拆开（UI/文档命名） | 前端文案 + 注释 | ~小 |
| **P2** | plugin agents 激活 | `subagent/manager.py` + `agent.py` + metadata 消费 | ~80-120 行 |
| **P3** | rules always_apply 语义 | `plugins.py:879` + `prompts.py:262-291` + `core.py:719-721` | ~30 行 |
| **P4** | commands/agents prompt 更薄 | `prompts.py:147-222` + slash 注册 | ~50 行（可选） |
| **P5** | hooks 可观测 + Scenario 隔离 | SSE 事件 + 前端面板 + isolate_hooks | ~100 行 |

---

## 10. 数据流总图

```
install -> lockfile -> enable -> Engine.create
                         ↓
              collect_contributions(plugins.py:898)
                         ↓
        ┌────────────┬─────────────┬──────────────┬───────────────┐
        skills       commands      agents         rules          hooks/MCP
        ↓            ↓             ↓              ↓              ↓
   SkillRegistry  plugin_commands  plugin_agents  plugin_rules   (trust gate)
        ↓            ↓             ↓              ↓              ↓
   一行目录进prompt  一行索引      一行索引       摘要(always)    事件触发跑
        ↓            ↓             ↓              ↓
   load_skill     /plugin:cmd    agent_spawn    @plugin:name
   (Layer B)      (Layer B 补)    (Layer B 补)   (Layer C)
                                                  ↓
                                          场景模式:全文+收窄
```

---

## 11. 交互场景示例（覆盖所有可能结果）

> 以下 10 个场景展示优化后插件系统在各种情况下的完整交互流程。每个场景含：初始状态、用户操作、前端 UI 变化、后端行为、prompt 变化、最终结果。

### 场景 1：轻量调试命令包（debug-cmds）—— 纯贡献态

**插件形态**：`debug-cmds/` 含 `commands/inspect.md`、`commands/profile.md`，无 hooks/MCP/rules/agents。

**初始状态**：未安装。

**操作**：
1. 用户打开插件页 -> 市场 tab -> 搜 "debug-cmds" -> 点安装
2. 安装弹窗显示：`debug-cmds v1.0.0，贡献 Commands:2，无 hooks/MCP，无需 trust`
3. 点确认 -> 落盘 `~/.deepseek/plugins/debug-cmds/` -> lockfile `{enabled:true, trusted:false}`
4. 插件页已装列表出现 `debug-cmds`，badge 显示 `Commands:2`

**后端**：新会话 Engine.create -> collect_contributions -> `engine.plugin_commands = {"debug-cmds:inspect": ..., "debug-cmds:profile": ...}`。无 hooks/MCP，trusted=false 不影响。

**prompt 变化**：
```
## Installed Plugins (contributing)
- debug-cmds: Debug helpers [commands:2]
Use /plugin:<plugin>:<cmd> for commands.
```

**使用**：
- 用户在 Composer 输入 `/` -> slash 菜单出现 `/plugin:debug-cmds:inspect`、`/plugin:debug-cmds:profile`
- 选 `/plugin:debug-cmds:inspect` -> 展开 command body -> agent 执行 -> 返回结果

**结果**：装上即用，无需 trust，无需进场景。**这是大多数插件的标准形态**。

---

### 场景 2：repo MCP 插件（repo-tools）—— trust + lazy

**插件形态**：`repo-tools/` 含 `mcpServers` 声明一个 lazy server + `permissions: ["read"]`。

**初始状态**：已安装未 trust。

**操作**：
1. 插件页显示 `repo-tools`，badge `MCP:1`，trust 状态"未信任"，黄色提示"含可执行组件，需信任"
2. 用户点 "Trust" -> 弹窗列权限 `read` -> 确认 -> lockfile `trusted:true`

**后端**：新会话 Engine.create -> plugin MCP server prepend 进 McpManager，`lazy=true`，`start_all` 跳过。权限 `read` 映射 `READ_ONLY` -> MCP 工具调用 AUTO 审批（不弹确认）。

**prompt 变化**：
```
## Installed Plugins (contributing)
- repo-tools: Repo analysis [mcp:1]
```
（MCP 工具 schema 不进 prompt，由 MCP 协议动态发现）

**使用**：
- 用户问"分析这个仓库的依赖图" -> agent 决定调用 `repo-tools__analyze_deps` 工具
- 首次调用触发 `_ensure_client()` -> spawn lazy server 进程 -> 工具执行 -> 返回结果
- 后续调用 server 已活，直接执行

**结果**：trust 后 MCP 可用，lazy 不占启动资源，权限声明让只读工具免审批。

---

### 场景 3：rules 重的工作流包（deep-research）—— 场景模式

**插件形态**：`deep-research/` 含 `rules/research-flow.md`（33K 字符，always_apply=true）、`skills/web-search/`、`skills/synthesize/`。

**初始状态**：已安装已 trust（skills 无代码，trust 不影响）。

**操作**：
1. 插件页显示 `deep-research`，badge `Skills:2 · Rules:1`，标"场景插件"标签（因 rules 体积 >10K）
2. 用户点"进入场景"按钮（或 Composer 发 `@plugin:deep-research 帮我做深度研究`）

**后端**：`set_active_plugin("deep-research")` -> `_active_plugin_whitelist` 收窄工具到读基础 + 2 个 skill 的 allowed-tools -> rules 全文注入 -> components 清单抑制。

**prompt 变化**：
```
## Active Scenario: deep-research
### deep-research Rules (authoritative)
<33K 字符研究流程正文>

### Available Skills (narrowed)
- web-search: ...
- synthesize: ...
```
（其他插件的贡献表不显示，专注当前场景）

**使用**：
- agent 按 rules 流程调用 web-search -> synthesize skill -> 输出研究报告
- 用户发 `@plugin:off` 退出 -> 回到 Layer A 基线（其他插件贡献表重新可见）

**结果**：rules 重包通过场景模式注入，不污染日常会话；退出即恢复。**这是 Scenario Mode 的正确用法**。

---

### 场景 4：含 agents 的插件（code-review-team）—— P2 激活

**插件形态**：`code-review-team/` 含 `agents/security.md`（人设+tools 白名单）、`agents/style.md`。

**初始状态**：已安装已 trust。

**操作**：用户问"帮我做代码审查，重点关注安全和风格"。

**后端（P2 改动后）**：
1. Engine.create -> `engine.plugin_agents = {"code-review-team:security": {body, tools:[...]}, "code-review-team:style": {body, tools:[...]}}` -> 进 `tool_context.metadata`
2. 主 agent 决定 spawn 两个子 agent
3. `agent_spawn type=plugin:code-review-team:security` -> 从 metadata 取 security.md body -> 追加进 sub-agent role 文本 -> 套 tools 白名单 -> spawn
4. 同理 spawn style agent
5. 两子 agent 并行审查，主 agent 汇总

**prompt 变化**：
```
## Installed Plugins (contributing)
- code-review-team: Review agents [agents:2]
Use agent_spawn type=plugin:<plugin>:<agent> for agents.
```
（agents 人设正文不进主 prompt，spawn 时才注入子上下文）

**结果**：装了 agents 插件后，agent_spawn 真能拿到人设并收窄工具。**当前实现做不到这点（advisory），P2 修复后才行**。

---

### 场景 5：含 hooks 的插件（auto-format）—— 可观测

**插件形态**：`auto-format/` 含 `hooks/hooks.json`：`PostToolUse`（matcher: `Write|Edit`）-> 跑 prettier。

**初始状态**：已安装未 trust。

**操作**：
1. 插件页显示 `auto-format`，badge `Hooks:on`，未信任提示
2. 用户点 Trust -> 确认 -> lockfile `trusted:true`

**后端**：Engine.create -> hook_entries 追加进 HookExecutor，事件 `tool_call_after`，condition `tool_name_any: [write_file, edit_file]`。

**使用**：
1. 用户让 agent 写文件 `src/foo.ts`
2. write_file 工具执行后 -> HookDispatcher 触发 `tool_call_after` -> 跑 prettier `src/foo.ts`
3. **P5 新增**：hook 执行时往 SSE 推 `hook_fired` 事件 `{plugin: "auto-format", event: "tool_call_after", command: "prettier src/foo.ts", exit_code: 0}`

**前端 UI**：
- 插件页 hooks 可观测面板出现一条："2026-07-13 14:32 auto-format tool_call_after prettier src/foo.ts exit:0"
- Composer 角标提示"auto-format 刚格式化 src/foo.ts"

**结果**：hooks 触发可见，不再是黑盒。

---

### 场景 6：多插件并存贡献态叠加

**初始状态**：已装 debug-cmds（commands:2）+ repo-tools（mcp:1）+ code-review-team（agents:2），都 enabled，repo-tools trusted。

**后端**：Engine.create 装配三个插件的贡献，各自进对应 registry。

**prompt 变化**：
```
## Installed Plugins (contributing)
- debug-cmds: Debug helpers [commands:2]
- repo-tools: Repo analysis [mcp:1]
- code-review-team: Review agents [agents:2]
Use /plugin:<plugin>:<cmd> for commands; agent_spawn type=plugin:<plugin>:<agent> for agents.
```

**使用**：
- 用户问"审查 src/ 下的代码并调试问题" -> agent 可能：spawn `code-review-team:security` 审查 + 调 `/plugin:debug-cmds:inspect` 检查 + 调 `repo-tools__analyze` 看依赖
- 三个插件能力叠加可用，互不干扰

**结果**：多插件贡献态自然叠加，模型按需调用。

---

### 场景 7：场景模式退出回基线

**接场景 3**：用户在 deep-research 场景模式中。

**操作**：用户发 `@plugin:off`。

**后端**：`set_active_plugin(None)` -> 清空 `_active_plugin` -> 工具白名单恢复全量 -> rules 恢复摘要模式 -> components 清单恢复显示。

**prompt 变化**：
```
（## Active Scenario 块消失）
## Installed Plugins (contributing)
- debug-cmds: ... [commands:2]
- repo-tools: ... [mcp:1]
- deep-research: ... [skills:2 rules:1]
- code-review-team: ... [agents:2]
## Plugin Rules (inactive)
- deep-research: <120 字符摘要>
```

**前端**：Composer 场景 badge 消失，回到正常贡献态。

**结果**：退出场景 = 回 Layer A 基线，不是"出厂设置"（所有插件贡献仍可见）。

---

### 场景 8：未 trust 的插件降级

**插件形态**：`auto-format` 含 hooks，已安装未 trust。

**后端**：Engine.create -> `collect_contributions` 发现 `not plugin.trusted` 且有 hooks -> 跳过 hook_entries -> 发 warning。

**prompt 变化**：
```
## Installed Plugins (contributing)
- auto-format: Auto format [hooks:off (untrusted)]
```
（skills/commands/agents/rules 仍贡献，hooks/MCP 摘除）

**前端**：插件页 auto-format 行显示黄色"未信任"badge，hooks 标"未激活"。

**使用**：用户写文件 -> hooks 不触发（没装配）-> 文件未格式化。

**结果**：未 trust 的可执行组件不跑，但声明式组件仍贡献。trust 后新会话生效。

---

### 场景 9：always_apply=False 的 rules（P3 改动）

**插件形态**：`deep-research/` 的 rules 有两个文件：
- `rules/main-flow.md`（always_apply=true）—— 主流程
- `rules/edge-case.md`（always_apply=false）—— 特殊场景补充

**当前行为（要改）**：`always_apply=false` 的 edge-case.md 在 `core.py:719-721` 被直接丢弃，永不生效。

**优化后**：
- **未进场景**：main-flow 摘要进 prompt，edge-case 不出现
- **进场景**（@plugin:deep-research）：main-flow 全文 + **edge-case 全文**都注入 `## Active Scenario`

**prompt 变化（进场景后）**：
```
## Active Scenario: deep-research
### deep-research Rules (authoritative)
#### main-flow.md
<正文>
#### edge-case.md
<正文>
```

**结果**：`always_apply` 真正语义 = "是否进默认贡献目录"，而非"是否生效"。场景模式下所有 rules 都灌全文。

---

### 场景 10：lazy MCP 白名单竞态修复后（P0）

**插件形态**：`repo-tools/` 含 lazy MCP server `repo-analyzer`，已 trust。

**当前 bug 行为**：用户发 `@plugin:repo-tools 分析仓库` ->
1. `set_active_plugin("repo-tools")`
2. `_active_plugin_whitelist()` 调 `_server_tool_names("repo-tools-repo-analyzer")`
3. server 是 lazy 未 spawn -> 返回空集 -> 白名单不含 MCP 工具
4. agent 想调 `repo-tools-repo-analyzer__analyze` -> 不在白名单 -> 工具不可见
5. 用户必须先退出场景、手动触发一次 MCP 调用、再进场景 -- 体验断裂

**P0 修复后**：
1. `set_active_plugin("repo-tools")`
2. `_active_plugin_whitelist()` 按声明匹配：该插件声明的 MCP server 名（`repo-tools-repo-analyzer`）全量放行，不依赖 tool 名预发现
3. agent 调 `repo-tools-repo-analyzer__analyze` -> 在白名单 -> 首次调用触发 lazy spawn -> 工具执行 -> 返回

**结果**：挂载含 lazy MCP 的插件不再有竞态，首次调用即触发 spawn，工具可见可用。

---

## 12. 实施顺序建议

1. **P0**（~20 行）：先修真实 bug，不动语义
2. **P1**（小）：UI/文档命名拆开，让概念清晰
3. **P2**（~80-120 行）：补 Layer B agents 激活，核心价值
4. **P3**（~30 行）：rules 语义澄清
5. **P4**（~50 行，可选）：prompt 更薄，看实际 token 体积决定
6. **P5**（~100 行）：hooks 可观测 + Scenario 隔离

每步独立可验证，不依赖后续步骤。P0-P3 是必做，P4-P5 看优先级。
