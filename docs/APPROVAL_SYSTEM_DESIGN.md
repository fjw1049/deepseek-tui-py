# 审批系统设计（阶段 A 规格）

> **状态**：设计稿 v2 + **已实现**（见 §15）；本文档兼作规格与实现索引。
>
> **目标**：解决「审批弹出来看不懂、不知道在审什么」——先统一**门控规则**与**展示模型**，再改 Engine / SSE / Workbench。
>
> **参考**：`deepseek/DeepSeek-TUI-main`（Rust TUI + runtime）、`deepseek/DeepSeek-GUI-master`（原 GUI）。

---

## 1. 设计原则

1. **单一事实来源**：是否审批由 `ToolSpec.approval_requirement()` + 全局 `approval_policy` 决定；展示内容由 `build_approval_presentation()` 一次生成，Engine / SSE / pending API / UI 共用。
2. **用户决策最小信息集**：每张审批卡必须回答——**做什么、影响哪里、风险档位、能否看详情**。
3. **分层不混淆**：工具门控（L1）、Shell/网络策略（L2）、沙箱升格（L3）用不同事件或明确标签，避免一张卡混三种语义。
4. **与 Rust parity 可追踪**：类别 / impacts / risk / approval_key 对齐 `tui/approval.rs`；门控对齐 `turn_loop.rs` + `tools/spec.rs`。

---

## 2. 产品原则

### 2.1 v1 基线决策（2026-05-27 锁定，实现默认遵循）

在未另行批注前，实现与测试均按此表执行：

| # | 决策 | v1 取值 | Rust 对照 |
|---|------|---------|-----------|
| P1 | 只读（`read_file` / `grep` / `list_dir` 等） | **不审** | `ToolCategory::Safe` → Benign |
| P2 | `web_search` / `web_run` | **不审** | Network benign |
| P3 | `fetch_url` | **要审**；域白名单走 L2，不在 v1 | Destructive |
| P4 | `write_file` / `edit_file` / `apply_patch` | **要审** + diff/路径预览 | 写盘 |
| P5 | `exec_shell*` | **要审** + command/cwd；危险命令 **DANGEROUS** 标签 | Shell → Destructive |
| P6–P7 | MCP 读 / 写 | 读不审 / 写要审 | `McpRead` / `McpAction` |
| P8 | 子代理、task、automation、`rlm` | **要审** | `Required` |
| P9 | Remember | **approval_key** 指纹 | `approval_cache.py` |
| P10 | 二次确认 | **Workbench + TUI** | Rust 双键 |
| — | `untrusted` | **v1 等同 `on-request`** | A3 再区分 |
| — | SSE | **双写** `risk_level` + `risk` | 不 breaking |

---

## 3. 三层模型（职责边界）

```
┌─────────────────────────────────────────────────────────────┐
│ L1 工具门控  needs_tool_approval(tool, policy)              │
│     → ApprovalRequiredEvent → UI 卡片                        │
├─────────────────────────────────────────────────────────────┤
│ L2 命令/网络策略  exec_policy / network_policy（主要在 shell）│
│     → 可合并进 L1 同一张卡（推荐），或 ExecApproval 专用事件  │
├─────────────────────────────────────────────────────────────┤
│ L3 沙箱升格  SandboxDenied → ElevationRequired              │
│     → 独立「权限升格」卡（阶段 C）                            │
└─────────────────────────────────────────────────────────────┘
```

**阶段 A 范围**：只做 **L1 门控 + L1 展示**；L2 仅规定「shell 的 PROMPT 不得再悄悄返回 ToolResult」，必须走 L1 或显式失败。

**沙箱 OS 隔离、工具矩阵、中间文件策略、分阶段实施计划**（L3 升格的技术上下文）见 **[`SANDBOX_ARCHITECTURE.md`](./SANDBOX_ARCHITECTURE.md)**。

---

## 4. 门控规则（`tools/approval_gate.py`）

### 4.1 主函数（伪代码）

```python
def needs_tool_approval(tool: ToolSpec, policy: str) -> bool:
    req = tool.approval_requirement()  # AUTO | SUGGEST | REQUIRED

    if policy in ("auto", "never-ask", "yolo"):
        return False
    if policy == "never":
        return req != ApprovalRequirement.AUTO  # 高敏工具直接 blocked，见 4.3

    # on-request / suggest / untrusted（见 4.2）
    if req == ApprovalRequirement.REQUIRED:
        return True
    if req == ApprovalRequirement.SUGGEST:
        return policy in ("on-request", "suggest", "untrusted", "never")  # never 走 deny 分支
    return False  # AUTO
```

**MCP 动态工具**（无 registry ToolSpec）：

```python
if is_mcp_tool(name):
    return not mcp_tool_is_read_only(name)
```

**`multi_tool_use.parallel`**：按子 call 逐个判断；batch 并行条件用 `plan.approval_required`（来自上式），**禁止**只查 `REQUIRES_APPROVAL`。

### 4.2 `approval_policy` 语义表（与 Workbench 设置对齐）

| 设置值 | 行为 |
|--------|------|
| `auto` | 不弹 L1；审计日志可记 auto_approve |
| `on-request` | `SUGGEST` + `REQUIRED` 弹窗 |
| `suggest` | 同 `on-request`（别名）；UI 文案可写「建议确认」 |
| `untrusted` | **阶段 B**：仅 `REQUIRED` + 未信任命令弹窗；`SUGGEST` 可自动放行（需 trusted prefix 表） |
| `never` | 不弹窗；`REQUIRED`/`SUGGEST` → **拒绝执行**（非静默执行） |

当前 bug：`untrusted` / `suggest` 写入 config 但 `ExecPolicyEngine` 未区分 → 本表为**目标行为**。

### 4.3 工具门控清单（默认 registry，agent 模式）

| 门控 | 工具（代表） | `approval_requirement` | 当前 Python 实际 |
|------|-------------|------------------------|------------------|
| 否 | `read_file`, `list_dir`, `grep_files`, `git_*`（读）, `web_search`, todo 读 | AUTO（cap 只读） | 多数 OK |
| 否 | 只读 MCP | —（动态只读） | OK |
| **是** | `write_file`, `edit_file`, `apply_patch` | SUGGEST（应显式 override） | 会审，但展示差 |
| **是** | `exec_shell*` | 默认 REQUIRED（cap ExecutesCode） | 会审 |
| **应审未审** | `fetch_url` | 应为 SUGGEST/REQUIRED | **常不审**（NETWORK→LOW） |
| **是** | `agent_*`, `delegate_*`, `task_create`, `automation_*`, `rlm`, `revert_turn`… | REQUIRED | 会审 |
| 策略 | `request_user_input` | 不走 L1，走 `user_input.required` | 独立 |

**实现前动作**：为 `FetchUrlTool` 增加 `approval_requirement() -> SUGGEST`（或 REQUIRED），与 P3 一致。

### 4.4 `ToolSpec.approval_requirement` 默认推导（对齐 Rust）

保持 `base.py` 默认实现与 Rust `spec.rs` 一致：

- `EXECUTES_CODE` → `REQUIRED`
- `WRITES_FILES` → `SUGGEST`
- 否则 → `AUTO`

子类 override 仅用于例外（如 `fetch_url` 只有 READ_ONLY+NETWORK 但仍需 SUGGEST）。

---

## 5. 展示模型：`ApprovalPresentation`

Engine 在 `_handle_approval_flow` **之前**构造，写入 `ApprovalRequiredEvent`，并刷到 SSE / `PendingApprovalRecord`。

### 5.1 数据结构

```typescript
// 逻辑类型；Python 用 dataclass / TypedDict 即可
type ApprovalCategory =
  | "safe"           // 只读（一般不应出现）
  | "file_write"
  | "shell"
  | "network"
  | "mcp_read"
  | "mcp_action"
  | "subagent"
  | "task"
  | "automation"
  | "unknown"

type ApprovalRisk = "benign" | "destructive"

type ApprovalPresentation = {
  id: string                    // tool_call_id
  tool_name: string
  category: ApprovalCategory
  risk: ApprovalRisk
  title: string                 // 一行标题，locale 可扩展
  impacts: string[]             // 要点列表，2–6 条
  primary_preview: string | null // 主预览区：command / diff / prompt
  params_excerpt: string | null  // 截断 JSON，可选
  approval_key: string          // 展示「记住本会话」范围
  description: string           // 兼容旧字段 = title 或 impacts 首条
  input_summary: string         // 兼容旧字段 = primary_preview 单行版
  risk_level: string            // 兼容：benign→low, destructive→high
}
```

### 5.2 构建管线

```
tool_name + arguments (+ tool.description)
    → classify_category(tool_name)      # 移植 approval.rs get_tool_category
    → classify_risk(name, category, args)
    → build_impacts(name, category, args)
    → build_primary_preview(name, category, args)  # 含 patch diff 生成
    → build_approval_key(name, args)               # 已有 approval_cache
    → localize(title, impacts)                     # 阶段 B i18n
```

**禁止**把 `reason="tool has medium risk level"` 作为用户可见主文案；`reason` 仅保留给日志/审计。

### 5.3 按类别的 `primary_preview` 规则

| category | 优先字段 | 预览形式 | 最大长度建议 |
|----------|----------|----------|--------------|
| `file_write` | path, content / search+replace | 单文件：`path` + 行数；`edit_file`：search/replace 各 20 行；`apply_patch`：**unified diff**（必做） | diff 最多 120 行 |
| `shell` | command, cwd | `command` 全文 + `cwd` | command 2KB |
| `network` | url / query | 完整 URL 或 query | 512 |
| `mcp_action` | 解析 server 名 + 关键 arg | `Server: X` + 首参 | — |
| `subagent` | prompt / objective | prompt 前 30 行 + model + flags | — |
| `task` / `automation` | prompt / schedule | 任务描述 + cron/interval | — |
| `unknown` | 任意主键 | `params_excerpt` JSON pretty | 2KB |

### 5.4 展示示例（用户应看到什么）

**write_file**

```
标题: 请求写入工作区文件
影响:
  - 会写入工作区或已批准范围内的文件。
  - 写入：src/foo.py（约 1.2 KB）
预览:
  path: src/foo.py
  content: (首 15 行) ...
记住: tool:write_file  （或更细 fingerprint，见 approval_key）
风险: DESTRUCTIVE — 需二次确认
```

**apply_patch**

```
标题: 请求应用补丁
影响:
  - 会修改 2 个文件。
  - src/a.py, tests/b.py
预览:
  --- unified diff ---  （与 Rust maybe_add_patch_preview 同级信息）
风险: DESTRUCTIVE
```

**exec_shell**

```
标题: 请求执行 shell 命令
影响:
  - 执行 shell 命令。
  - 命令：npm test -- --coverage
  - 工作目录：/Users/.../project
风险: DESTRUCTIVE
```

**agent_spawn**（当前最易「看不懂」）

```
标题: 请求启动子代理
影响:
  - 子代理将在工作区内自主调用工具（可能写文件、执行命令）。
  - 任务：审查 auth 模块并列出 3 个安全风险
  - 类型：review · 模型：deepseek-chat · allow_shell：是
风险: DESTRUCTIVE
```

**fetch_url**（修门控后）

```
标题: 请求获取远程内容
影响:
  - 可能访问网络并拉取任意 URL 内容。
  - 目标：https://example.com/api
风险: DESTRUCTIVE
```

**MCP 写操作**

```
标题: 请求调用 MCP 操作
影响:
  - 可能改变远程服务状态。
  - 服务器：linear
  - 工具：mcp_linear_save_issue
预览: { "title": "...", ... }  （截断）
```

---

## 6. 协议变更（SSE / HTTP）

### 6.1 `approval.required` payload（目标）

在 [contracts/sse-event.schema.json](../contracts/sse-event.schema.json) 中扩展 **required 不变**，新增 **recommended** 字段（向后兼容）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id`, `approval_id`, `tool_name` | string | ✓ | 不变 |
| `description` | string | | `title` 或兼容旧 GUI |
| `input_summary` | string | | `primary_preview` 单行回退 |
| `risk_level` | string | | `low`/`high` 或 `benign`/`destructive` |
| `category` | string | | 见 §5.1 |
| `risk` | string | | `benign` \| `destructive` |
| `title` | string | | 新：卡片主标题 |
| `impacts` | string[] | | 新：要点列表 |
| `primary_preview` | string | | 新：主预览（可含 diff） |
| `params_excerpt` | string | | 新：展开详情 |
| `approval_key` | string | | 新：记住范围提示 |

### 6.2 `GET /v1/approvals/pending`

`PendingApprovalRecord` 存完整 `ApprovalPresentation`（或等价 dict），避免线程切换后只剩 `tool_name` + 空 description。

### 6.3 `POST /v1/approvals/{id}`

| decision | 含义 |
|----------|------|
| `allow` | 单次批准 |
| `allow` + `remember: true` | `APPROVED_SESSION` + `approval_cache` |
| `deny` | 拒绝 |
| （阶段 B）`abort` | 中止整轮 turn |

---

## 7. UI 线框（Workbench 审批卡）

### 7.1 布局（Destructive）

```
┌──────────────────────────────────────────────────────────┐
│ ⚠ 需要确认                                    [DESTRUCTIVE] │
│ 工具: exec_shell                                          │
├──────────────────────────────────────────────────────────┤
│ 请求执行 shell 命令                                        │  ← title
│                                                           │
│ 影响                                                      │
│   • 执行 shell 命令。                                      │  ← impacts[]
│   • 命令：npm test ...                                     │
│   • 工作目录：/path/to/project                             │
│                                                           │
│ ┌─ 预览 ─────────────────────────────────────────────┐  │
│ │ npm test -- --coverage                              │  │  ← primary_preview
│ └───────────────────────────────────────────────────┘  │
│                                    [查看完整参数 ▾]      │  ← params_excerpt
├──────────────────────────────────────────────────────────┤
│ 记住本会话将放行：shell:npm test …（见 approval_key）     │  ← 仅 hover/小字
│                                                           │
│  [拒绝]  [允许本次]  [允许并记住]     [审批设置]            │
│                                                           │
│  （首次点「允许本次」→ 显示：请再点一次确认）               │  ← 二次确认
└──────────────────────────────────────────────────────────┘
```

### 7.2 布局（Benign — 若出现）

- 无二次确认；`Allow` 一次生效。
- 徽章 `[REVIEW]` 而非 `[DESTRUCTIVE]`。

### 7.3 字段映射（现有 Workbench → 目标）

| 现有 block 字段 | 目标来源 |
|-----------------|----------|
| `toolName` | `tool_name` |
| `summary` | `title` + impacts 合并（勿再用 risk reason） |
| `inputSummary` | `primary_preview` |
| `riskLevel` | `risk` / `risk_level` |

### 7.4 审批卡验收清单（手验必过）

- [ ] 用户**不展开参数**也能判断 Allow/Deny
- [ ] `apply_patch` 必见 **diff 或文件列表**
- [ ] `exec_shell` 必见 **完整 command + cwd**
- [ ] 子代理必见 **prompt/目标 + 权限标志**
- [ ] `fetch_url` 必见 **完整 URL**
- [ ] 不允许主文案仅为 `tool has medium risk level`
- [ ] Destructive：误点一次 Allow **不会**立即提交
- [ ] 「记住」文案说明 **approval_key**，不是「此工具永远允许」

---

## 8. 模块改动地图（实现时用，现在仅记账）

| 模块 | 改动 |
|------|------|
| `tools/approval_present.py`（新） | `classify_*`, `build_impacts`, `build_primary_preview` |
| `execpolicy/engine.py` | 瘦身为 policy 模式；或 `needs_tool_approval` 迁到 `tools/approval_gate.py` |
| `engine/engine.py` | 门控改用 `approval_requirement`；`_handle_approval_flow` 前 build presentation |
| `engine/engine.py` 并行 plan | `approval_required` 与门控一致 |
| `app_server/thread_manager.py` | SSE 发全量 presentation |
| `approval_bridge.py` | pending meta 存 presentation |
| `contracts/sse-event.schema.json` | 新字段 |
| `packages/workbench/.../MessageTimeline.tsx` | 分模板渲染 + 二次确认 |
| `tui/widgets/approval.py` | impacts + diff（可选阶段 B） |

---

## 9. 分阶段交付（回顾）

| 阶段 | 内容 | 验收 |
|------|------|------|
| **A0 评审** | 本文档 + 你确认 P1–P10 | 签字产品表 |
| **A1 门控** | `needs_tool_approval` + fetch_url 修复 + 并行 plan | contract + 单测：该审必审、不该审不审 |
| **A2 展示** | `ApprovalPresentation` + SSE/pending | 手验清单 §7.4 全绿 |
| **A3 策略** | `untrusted` / `never` 语义 | `test_exec_policy_config` 扩展 |
| **B UI** | Workbench 模板 + 二次确认 + diff 视图 | `WORKBENCH_APPROVAL_MANUAL_TEST` 扩展用例 |
| **C L2/L3** | Shell 策略合并、Elevation | 与 Rust execpolicy 对齐 |

---

## 10. 后续可变更项（非 v1 阻塞）

| 项 | 说明 |
|----|------|
| 域白名单免审 `fetch_url` | 用 L2 `network_policy` + `unless_trusted`，不改 L1 Auto |
| `untrusted` 真语义 | A3：仅 `REQUIRED` + 非 trusted prefix 弹窗 |
| TUI 双键确认 | 与 Workbench parity |
| `abort` 决策 | POST body 增 `abort`，中止整轮 |

---

## 11. 测试规格

> 实现阶段按表加测试；**当前仅规格，不提交测试代码**。

### 11.1 单元测试 — `tests/test_approval_gate.py`（新建）

测试对象：`needs_tool_approval(tool, policy)` + `needs_mcp_approval(name)`（拟 `src/deepseek_tui/tools/approval_gate.py`）。

| ID | policy | 工具 / 条件 | 期望 `needs_approval` |
|----|--------|-------------|----------------------|
| G-01 | `auto` | `write_file` | false |
| G-02 | `on-request` | `read_file` | false |
| G-03 | `on-request` | `write_file` (SUGGEST) | true |
| G-04 | `on-request` | `exec_shell` (REQUIRED) | true |
| G-05 | `on-request` | `fetch_url`（override SUGGEST 后） | true |
| G-06 | `on-request` | `web_search` | false |
| G-07 | `on-request` | `agent_spawn` (REQUIRED) | true |
| G-08 | `never` | `write_file` | true → 引擎路径 **blocked**（非弹窗） |
| G-09 | `never` | `read_file` | false |
| G-10 | `on-request` | MCP `list_mcp_tools`（只读） | false |
| G-11 | `on-request` | MCP `mcp_foo_write`（非只读） | true |
| G-12 | `suggest` | `edit_file` | true（与 on-request 同 v1） |
| G-13 | `untrusted` | `write_file` | true（v1 等同 on-request） |

**并行 plan 辅助**（可同文件或 `test_engine_dispatch.py`）：

| ID | batch | 期望 `should_parallelize` |
|----|-------|---------------------------|
| P-01 | `read_file` + `read_file` | true |
| P-02 | `read_file` + `write_file` | false（写或 approval） |
| P-03 | `read_file` + `agent_spawn` | false |

### 11.2 单元测试 — `tests/test_approval_presentation.py`（新建）

测试对象：`build_approval_presentation(tool_name, args, description?)`。

| ID | tool | args 要点 | 断言 |
|----|------|-----------|------|
| PR-01 | `write_file` | path + content | `category=file_write`, `risk=destructive`, impacts 含 path, preview 非空 |
| PR-02 | `apply_patch` | patch 含 `---`/`+++` | `primary_preview` 含 diff 或文件列表 |
| PR-03 | `exec_shell` | command + cwd | impacts 含 command 与 cwd |
| PR-04 | `fetch_url` | url | impacts 含完整 url；`title` 非 "medium risk" |
| PR-05 | `agent_spawn` | prompt, allow_shell | impacts 含 prompt 片段与 allow_shell |
| PR-06 | `mcp_linear_save` | — | `category=mcp_action`, impacts 含 server 提示 |
| PR-07 | 任意 | — | `approval_key` 与 `build_approval_key()` 一致 |
| PR-08 | `exec_shell` | `rm -rf /` | impacts 或 badge 含 DANGEROUS（展示层，v1） |
| PR-09 | `read_file` | path | 若被调用：不应出现（门控不测此文件） |

**禁止断言**：`reason == "tool has medium risk level"` 作为 `title` / `description` 主文案。

### 11.3 Contract 测试 — 扩展现有文件

#### `tests/contract/test_contract_schemas.py`

| ID | 变更 | 断言 |
|----|------|------|
| C-01 | `approval.required` payload | required 仍为 `id`, `approval_id`, `tool_name` |
| C-02 | 新增 optional | schema `properties` 含 `title`, `impacts`, `primary_preview`, `category`, `risk`, `approval_key` |

#### `tests/contract/test_turn_approval_integration.py`

| ID | 场景 | 断言 |
|----|------|------|
| I-01 | 现有 monitor + SSE | 保持通过 |
| I-02 | `ApprovalRequiredEvent` 带 presentation 字段 | payload 含 `impacts`（数组）、`title` 非空 |
| I-03 | `input_summary` 兼容 | 等于 `primary_preview` 截断或同源 |

#### `tests/contract/test_approvals.py`

| ID | 场景 | 断言 |
|----|------|------|
| H-01 | pending list | `GET /v1/approvals/pending` 项含 `title` 或 `impacts`（实现后） |
| H-02 | remember | 现有 `APPROVED_SESSION` 保持 |

#### `tests/contract/test_exec_policy_config.py`

| ID | 场景 | 断言 |
|----|------|------|
| E-01 | `never` + `write_file` | 拒绝而非静默执行（与 G-08 一致） |
| E-02 | `auto` | 不经过 HttpApprovalHandler 阻塞 |

### 11.4 集成 / 手验对照

| 自动化 ID | 手验用例（见 `WORKBENCH_APPROVAL_MANUAL_TEST.md`） |
|-----------|--------------------------------------------------|
| PR-01, G-03 | A 写文件 |
| G-08, B | B Deny |
| I-01, C1 | C SSE |
| PR-02 | E apply_patch diff |
| PR-03 | F exec_shell |
| PR-04, G-05 | G fetch_url |
| PR-05, G-07 | H subagent |
| P10 | I 二次确认 |
| H-01 | D2 pending 恢复 |

---

## 12. 实现顺序（单 PR 可拆多 commit）

```
Commit 1 — approval_gate.py + test_approval_gate.py
          needs_tool_approval, MCP 分支, FetchUrlTool.approval_requirement override
          engine 门控改调 gate；并行 plan.approval_required 修复

Commit 2 — approval_present.py + test_approval_presentation.py
          build_approval_presentation；engine _handle_approval_flow 填入 request

Commit 3 — thread_manager SSE + approval_bridge pending 全字段
          contracts/sse-event.schema.json 扩展 optional 字段

Commit 4 — Workbench MessageTimeline 分模板 + 二次确认 + i18n 键
          WORKBENCH_APPROVAL_MANUAL_TEST 用例 E–I

Commit 5 — TUI ApprovalDialog impacts（可选，可与 4 并行）
```

**依赖**：1 → 2 → 3 → 4；5 独立。

**每个 commit 的 verify**：

| Commit | 命令 |
|--------|------|
| 1 | `pytest tests/test_approval_gate.py -q` |
| 2 | `pytest tests/test_approval_presentation.py -q` |
| 3 | `pytest tests/contract/test_contract_schemas.py tests/contract/test_turn_approval_integration.py tests/contract/test_approvals.py -q` |
| 4 | 手验 E–I + 原 A–D |
| 5 | `pytest tests/test_tui_smoke.py -q`（若有） |

---

## 13. `ApprovalPresentation` Python 形状（实现参考）

```python
@dataclass(slots=True)
class ApprovalPresentation:
    id: str
    tool_name: str
    category: str          # file_write | shell | ...
    risk: str              # benign | destructive
    title: str
    impacts: list[str]
    primary_preview: str | None
    params_excerpt: str | None
    approval_key: str

    def to_sse_payload(self) -> dict[str, object]:
        """向后兼容：填充 description / input_summary / risk_level。"""
        risk_level = "low" if self.risk == "benign" else "high"
        return {
            "id": self.id,
            "approval_id": self.id,
            "tool_name": self.tool_name,
            "title": self.title,
            "description": self.title,
            "impacts": self.impacts,
            "primary_preview": self.primary_preview,
            "input_summary": (self.primary_preview or "")[:500],
            "category": self.category,
            "risk": self.risk,
            "risk_level": risk_level,
            "approval_key": self.approval_key,
            "params_excerpt": self.params_excerpt,
        }
```

`ApprovalRequest` 可暂保留；长期由 `ApprovalPresentation` 替代或包装。

---

## 14. 参考文件索引

| 主题 | 路径 |
|------|------|
| Rust 展示 + 分类 | `deepseek/DeepSeek-TUI-main/crates/tui/src/tui/approval.rs` |
| Rust 门控 | `deepseek/DeepSeek-TUI-main/crates/tui/src/core/engine/turn_loop.rs` |
| Rust UI 绑定 | `deepseek/DeepSeek-TUI-main/crates/tui/src/tui/ui.rs` (~1354) |
| 指纹缓存 | `src/deepseek_tui/execpolicy/approval_cache.py` |
| 当前门控 | `src/deepseek_tui/tools/approval_gate.py` |
| 当前 SSE | `src/deepseek_tui/app_server/thread_manager.py` (~1102) |
| Workbench 卡片 | `packages/workbench/.../MessageTimeline.tsx` (~2047) |
| 手验 | `docs/WORKBENCH_APPROVAL_MANUAL_TEST.md` |
| 测试规格 | 本文 §11 |

---

## 15. 实现进度（2026-05-27）

| Commit | 状态 | 说明 |
|--------|------|------|
| 1 门控 | ✅ | `tools/approval_gate.py`，`fetch_url` SUGGEST，`base.approval_requirement` 默认推导，engine + 并行 plan |
| 2 展示 | ✅ | `tools/approval_present.py`，`ApprovalRequest` 扩展字段，SSE/pending 全量 |
| 3 Contract | ✅ | `contracts/sse-event.schema.json` optional 字段 |
| 4 Workbench UI | ✅ | `ApprovalBubble`：impacts + destructive 徽章 + **二次确认** |
| 5 TUI | ✅ | `ApprovalDialog`：impacts/preview + destructive 双次 Approve |

**统一测试**：

```bash
PYTHONPATH=src pytest \
  tests/test_approval_gate.py \
  tests/test_approval_presentation.py \
  tests/test_approval_system.py \
  tests/contract/test_approvals.py \
  tests/contract/test_contract_schemas.py \
  tests/contract/test_turn_approval_integration.py \
  tests/contract/test_exec_policy_config.py -q
```

---

*文档版本：2026-05-27 · 设计稿 v2 + 实现记录*
