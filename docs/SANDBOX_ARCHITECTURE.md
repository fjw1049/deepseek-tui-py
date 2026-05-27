# 沙箱架构分析与实施计划

> **状态**：设计稿 / 决策参考（**Seatbelt + L3 升格已部分实施**，见 `HANDOVER.md` §9.5）  
> **日期**：2026-05-27  
> **目的**：汇总 DeepSeek-TUI Rust 参考实现、deepseek-tui-py 现状、Claude Code 对照，以及「哪些工具需要 OS 沙箱、中间文件如何处理、如何兼容」的完整分析，供后续是否投入开发时决策。  
> **关联文档**：[`APPROVAL_SYSTEM_DESIGN.md`](./APPROVAL_SYSTEM_DESIGN.md)（L1/L2/L3 审批分层）、[`HANDOVER.md`](./HANDOVER.md)（Stage 2.7 Seatbelt 跳过记录）

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [术语：三套「沙箱」不要混用](#2-术语三套沙箱不要混用)
3. [Rust 参考实现（DeepSeek-TUI-main）](#3-rust-参考实现deepseek-tui-main)
4. [Python 现状（deepseek-tui-py）](#4-python-现状deepseek-tui-py)
5. [Claude Code 对照](#5-claude-code-对照)
6. [工具级沙箱矩阵（完整）](#6-工具级沙箱矩阵完整)
7. [中间文件与可写路径策略](#7-中间文件与可写路径策略)
8. [审批与沙箱的三层模型（L1/L2/L3）](#8-审批与沙箱的三层模型l1l2l3)
9. [配置项与环境变量](#9-配置项与环境变量)
10. [平台支持与已知限制](#10-平台支持与已知限制)
11. [风险与开放问题](#11-风险与开放问题)
12. [分阶段实施计划](#12-分阶段实施计划)
13. [验收标准与 Parity 清单](#13-验收标准与-parity-清单)
14. [源码索引](#14-源码索引)
15. [历史决策记录](#15-历史决策记录)

---

## 1. 执行摘要

### 1.1 沙箱主要用来干什么

OS 级沙箱（macOS Seatbelt / Linux Landlock / 外部 OpenSandbox）在 DeepSeek 体系中的**唯一核心职责**是：

> **限制 shell 子进程对文件系统与网络的访问**，防止模型通过 `exec_shell` 等命令意外或恶意破坏 workspace 外资源、篡改 `~/.deepseek` 配置、或发起未授权网络连接。

它**不是**文件读写工具的主隔离机制，也**不是** MCP / 子代理 / RLM 的隔离机制。

### 1.2 在什么点接入

```
用户消息 → Engine → ToolContext（含 elevated_sandbox_policy）
                         ↓
              exec_shell / task_shell_* → ShellManager
                         ↓
              CommandSpec + SandboxPolicy → SandboxManager.prepare()
                         ↓
              macOS: sandbox-exec -p "<SBPL>" -- sh -c "..."
              或 OpenSandbox: HTTP 远程执行（替换本地 spawn）
```

**不经过此路径的**：`read_file`、`write_file`、`git_*`、`fetch_url`、hooks、`pdftotext` 子进程、RLM in-process `exec()` 等。

### 1.3 当前 Python 项目 gap（一句话）

- `execpolicy/sandbox.py` 存在但 **从未被 `shell_tools.py` 调用**；
- `config.sandbox_mode` **存储/转发但未在运行时 enforcement**；
- Stage 2.7 Seatbelt **用户已决定跳过**（见 HANDOVER），与 Rust 参考实现存在 intentional gap。

### 1.4 若要做，推荐顺序

| 优先级 | 内容 | 理由 |
|--------|------|------|
| **P0** | 应用层 enforcement（Plan 禁写、read-only 模式、trust 映射） | 无 Seatbelt 也能显著降风险 |
| **P0** | Shell 统一执行网关 | 消除 `create_subprocess_shell` 直连 |
| **P1** | 移植 Rust Seatbelt profile（含 cargo/tmp/.deepseek） | 解决 build 类命令中间文件失败 |
| **P1** | L3 升格 UI + 事件 rename | 沙箱拒绝后可恢复 |
| **P2** | OpenSandbox backend | 企业可选 |
| **P3** | Hook 沙箱、Linux bubblewrap | 非 macOS Handover 范围 |

---

## 2. 术语：三套「沙箱」不要混用

集成或文档中必须区分以下概念，**禁止**用一个 `sandbox_mode` 字段统管全部行为。

### 2.1 三层模型

| 层级 | 名称 | 配置/入口 | 保护对象 | 实现 |
|------|------|-----------|----------|------|
| **L0 产品/合规策略** | `sandbox_mode` | `config.toml` / `DEEPSEEK_SANDBOX_MODE` | 枚举合规、Workbench 展示、requirements 白名单 | 校验 + 应用层 gate（**Rust 运行时 shell 主驱动不是它**） |
| **L1 应用层边界** | workspace / trust / approval | `ToolContext.resolve_path()`、`approval_policy`、execpolicy、network policy | 路径逃逸、工具门控、命令黑名单 | Python 已部分实现 |
| **L2 OS 子进程隔离** | Execution sandbox | `SandboxManager` + Seatbelt | **仅 shell spawn** | Rust 完整；Python stub |

### 2.2 两个不同的 `SandboxPolicy`（Rust 陷阱）

Rust 代码中存在**两个**同名概念：

| 位置 | 含义 |
|------|------|
| `crates/tui/src/sandbox/policy.rs` → `SandboxPolicy` | **真正的执行策略**（read-only / workspace-write / danger-full-access / external-sandbox） |
| `crates/tui/src/tools/spec.rs` → `SandboxPolicy` | **遗留 stub**，仅 `None` 枚举，几乎不用 |

Python 移植时模块命名建议：`ExecutionSandboxPolicy`，避免与 config 的 `sandbox_mode` 混淆。

### 2.3 `ToolCapability.SANDBOXABLE` 的含义

标记为 `SANDBOXABLE` **不等于**「会被 OS sandbox-exec 包裹」。

含义：**与 workspace 边界、审批流程、模式策略协同设计**（例如文件工具 description 写 "sandbox-aware" 指路径策略）。

---

## 3. Rust 参考实现（DeepSeek-TUI-main）

> 源码 vendored 于 `docs/DeepSeek-TUI-main/`（约 161k LOC Rust）。

### 3.1 模块结构

```
crates/tui/src/sandbox/
├── mod.rs          # SandboxManager, CommandSpec, ExecEnv, prepare()
├── policy.rs       # SandboxPolicy 枚举 + get_writable_roots()
├── seatbelt.rs     # macOS SBPL 动态生成（~550 LOC）
├── landlock.rs     # Linux（需 helper，注释称未完全落地）
├── windows.rs      # 进程树 Job Object（未 advertise）
├── backend.rs      # OpenSandbox 抽象
└── opensandbox.rs  # HTTP 远程执行
```

Shell 执行统一入口：

```
crates/tui/src/tools/shell.rs  → ShellManager.execute_with_options_env()
                                      → sandbox_manager.prepare(&spec)
```

### 3.2 `SandboxPolicy` 四种模式

定义：`docs/DeepSeek-TUI-main/crates/tui/src/sandbox/policy.rs`

| 模式 | `should_sandbox()` | 写盘 | 网络 | 说明 |
|------|-------------------|------|------|------|
| `read-only` | **true** | 无 | 否 | Plan 模式 shell |
| `workspace-write` | **true** | cwd + writable_roots + /tmp + TMPDIR | 可配 `network_access` | Agent 默认 |
| `danger-full-access` | **false** | 全盘 | 是 | YOLO |
| `external-sandbox` | **false** | 信任外层容器 | 可配 | 避免 double sandbox |

默认策略：`workspace-write`，无 extra roots，**network_access = false**（但 Agent 模式映射会打开 network，见下节）。

辅助方法：

- `has_full_disk_read_access()`：当前所有策略均允许全盘读
- `get_writable_roots(cwd)`：枚举可写根，并为每个 root 下的 `.deepseek/` 加入 **read-only subpath**

### 3.3 运行时策略来源：**AppMode，不是 config.sandbox_mode**

**关键发现**（集成时必须知道）：

Rust **运行时** shell OS 策略由 UI 模式决定，函数位于：

`docs/DeepSeek-TUI-main/crates/tui/src/core/engine/tool_setup.rs` → `sandbox_policy_for_mode()`

| AppMode | ExecutionSandboxPolicy |
|---------|------------------------|
| **Plan** | `ReadOnly`（#1077：防止 plan 下 `python -c open(...)` 写 workspace） |
| **Agent** | `WorkspaceWrite { writable_roots: [workspace], network_access: true }` |
| **Yolo** | `DangerFullAccess` |

Engine 在 `build_tool_context()` 中设置：

```rust
let policy = sandbox_policy_for_mode(mode, &self.session.workspace);
ctx = ctx.with_elevated_sandbox_policy(policy);
```

`config.sandbox_mode` 的用途（**非上述映射**）：

- `Config::validate()` 校验枚举值
- `apply_requirements()` 对照 `allowed_sandbox_modes` 企业白名单
- 环境变量 `DEEPSEEK_SANDBOX_MODE` 覆盖
- Workbench / 配置 UI 展示与 `danger-full-access` → trust 映射

**结论**：若 Python 仅实现「读 TOML sandbox_mode 就 wrap shell」，与 Rust **不一致**；要对齐需复刻 **AppMode → Policy** 或明确产品决策改变 Rust parity。

### 3.4 Seatbelt 实现要点（macOS）

文件：`docs/DeepSeek-TUI-main/crates/tui/src/sandbox/seatbelt.rs`

**执行方式**：

```
/usr/bin/sandbox-exec -p "<完整 SBPL>" -D WRITABLE_ROOT_0=... -D CARGO_HOME=... -- sh -c "command"
```

**Base policy 允许**（摘要）：

- process-exec / process-fork / signal / mach-lookup
- `/dev/null`、`/dev/urandom`、`/dev/ptmx`、`/dev/ttys*`
- pseudo-tty（PTY shell 需要）
- 全盘 `file-read*`（所有当前策略）
- `DARWIN_USER_CACHE_DIR` read+write

**条件写入**：

- workspace-write：按 `get_writable_roots()` 生成 `(allow file-write* (subpath ...))`，支持 read-only 子路径例外
- read-only：无 write 规则
- danger-full-access / external：`(allow file-write* (regex #"^/"))` 或跳过 wrap

**Cargo 特殊规则（#558）**：

- 始终允许读 `$CARGO_HOME`
- 非 read-only 时允许写 `$CARGO_HOME/registry` 与 `$CARGO_HOME/git`
- 解决 sandbox 内 `cargo build` / `cargo publish` 缓存失败

**网络**：

- `network_access: true` 时追加 `(allow network-outbound/inbound)` 等

**拒绝检测**：

- `seatbelt::detect_denial(exit_code, stderr)` → `ShellResult.sandbox_denied`
- `SandboxManager.denial_message()` 生成用户可读原因（file-write / network）

### 3.5 ShellManager 行为摘要

文件：`docs/DeepSeek-TUI-main/crates/tui/src/tools/shell.rs`

| 能力 | OS 沙箱 |
|------|---------|
| 同步 foreground | 是（经 background polling 实现） |
| background job | 是 |
| PTY (`tty=true`) | 是（Seatbelt 含 pseudo-tty） |
| interactive（inherit TTY） | 是 |
| stdin 注入 | 是 |
| shell_env hook 合并 env | 是（hook 本身无沙箱，见 §3.8） |

**Policy 优先级**：

1. `context.elevated_sandbox_policy`（升格重试）
2. `ShellManager.sandbox_policy`（默认，Engine 创建时多为 default workspace-write）

**输出处理**：

- 内存缓冲 stdout/stderr
- `truncate_with_meta` / `summarize_output` 截断后返回模型
- metadata 含 `sandboxed`、`sandbox_type`、`sandbox_denied`、长度与 omitted 字节

**网络失败 hint**：

- `command_likely_needs_network()` 启发式（curl、git fetch、npm install 等）
- `shell_network_restricted_hint()` 在 policy 禁网且命令像要联网时附加提示

### 3.6 外部沙箱：OpenSandbox

配置：

- `sandbox_backend = "opensandbox"`（或 `open-sandbox` / `open_sandbox`）
- `sandbox_url`（默认 `http://localhost:8080`）
- `sandbox_api_key`

行为（`exec_shell`）：

- **完全替换**本地 `ShellManager` spawn
- **不支持** background / PTY / interactive
- 结果 metadata：`sandbox_type: "opensandbox"`

与 `sandbox_mode = external-sandbox` 的关系：

- **external-sandbox**：跳过本地 OS wrap（`should_sandbox() = false`）
- **opensandbox backend**：远程执行后端，可独立配置

### 3.7 Plan 模式的工具面裁剪

`build_turn_tool_registry_builder()`（同 `tool_setup.rs`）：

- Plan：**不注册** shell 工具、RLM、FIM、apply_patch；仅 read-only 文件/搜索/git/诊断等
- Agent/Yolo：完整 agent 工具（受 feature flag + allow_shell 约束）

这是 **registry 层** 与 **OS 沙箱层** 的双重只读保护。

### 3.8 Hooks：**无 OS 沙箱**

文件：`docs/DeepSeek-TUI-main/crates/tui/src/hooks.rs`

- 所有 hook 事件（SessionStart、ToolCallBefore、ShellEnv 等）通过 `sh -c` / `cmd /C` **直接 spawn**
- `collect_shell_env()` 解析 stdout 的 `KEY=VALUE` 行注入 exec_shell 环境
- Hook 失败不 abort shell，仅 warn + audit（keys only，不记录 values）

**安全 implication**：恶意或过于宽泛的 hook 可在 TUI 进程权限下读写任意路径——与 Claude Code「hook 走 network-only sandbox」不同。

### 3.9 文件 / Git / 网络工具

| 模块 | OS 沙箱 | 机制 |
|------|---------|------|
| `tools/file.rs` | 否 | `context.resolve_path()`；Plan 不注册写工具 |
| `tools/git.rs` | 否 | `Command::new("git")` 直接 subprocess |
| `fetch_url` / `web_search` | 否 | `NetworkPolicyDecider` |
| `read_file` 内 `pdftotext` | 否 | 辅助子进程无 Seatbelt |

### 3.10 RLM

- `crates/tui/src/rlm/`：in-process Python REPL + RPC
- **不走** Seatbelt；有独立的 repl 语义（FINAL()、深度限制）
- Python 侧已实现 in-process `exec()` 沙箱（HANDOVER p3-debt），与 OS sandbox 是不同层

### 3.11 升格流程（L3）

1. Shell 执行 → Seatbelt 拒绝 → `sandbox_denied: true`
2. UI 展示升格选项（设计在 approval 体系）
3. 用户批准 → `EngineHandle.retry_tool_with_policy(id, policy)`
4. 重试时 `elevated_sandbox_policy` 覆盖（例如临时 `WorkspaceWrite { network_access: true }`）

---

## 4. Python 现状（deepseek-tui-py）

### 4.1 已有组件

| 组件 | 路径 | 状态 |
|------|------|------|
| macOS stub | `src/deepseek_tui/execpolicy/sandbox.py` | ~80 行，`sandbox-exec -f` 静态 profile；**未被调用** |
| Shell 执行 | `src/deepseek_tui/tools/shell_tools.py` | `asyncio.create_subprocess_shell` **直连** |
| 路径边界 | `src/deepseek_tui/tools/context.py` | `resolve_path()` 对齐 Rust PathEscape |
| 命令安全 | `src/deepseek_tui/execpolicy/command_safety.py` | 11 级管道 + SafetyLevel |
| ExecPolicy | `src/deepseek_tui/execpolicy/policy.py` | FORBIDDEN/PROMPT/ALLOW；已接 ExecShellTool |
| 配置 | `src/deepseek_tui/config/models.py` | `sandbox_mode` 默认 `workspace-write` |
| Plan registry | `src/deepseek_tui/tools/builder.py` | `mode != "plan"` 时不注册 shell/写工具（**部分对齐 Rust**） |
| 审批 L1 | `docs/APPROVAL_SYSTEM_DESIGN.md` + 实现 | L3 **未实现** |
| 错误事件 | `SandboxDeniedEvent` | **Misnamed**：实为 L1 approval deny，非 OS violation |

### 4.2 配置字段（已接受 TOML，行为未全接）

`Config` 中与沙箱相关：

```python
sandbox_mode: str = "workspace-write"          # 未驱动 OS wrap
# Rust 还有（Python Config 需确认是否已加全）：
# sandbox_backend, sandbox_url, sandbox_api_key
```

`NetworkPolicyConfig`：Stage 2.7 注释称 **接受 TOML 但未完全 wired 到 ExecPolicyEngine**。

### 4.3 HANDOVER 中的 intentional 跳过

> Stage 2.7 `execpolicy/sandbox/seatbelt.py` — **已跳过**（2026-05-07）  
> 原因：macOS Seatbelt OS 级隔离不做；命令黑名单 + cwd 边界 + env 清洗已足够

与 Rust 参考实现 **刻意不对齐**，本计划若采纳将 **推翻** 该决策，需用户重新批准。

### 4.4 Python stub 与 Rust 的差距

| 项 | Python stub | Rust Seatbelt |
|----|-------------|---------------|
| Profile 传递 | `-f` 临时文件 | `-p` inline SBPL |
| 可写根 | 手动 `allowed_write_paths` | 动态 WRITABLE_ROOT_N + .deepseek RO |
| /tmp / TMPDIR | 未处理 | 默认允许 |
| Cargo home | 未处理 | #558 专用规则 |
| Network | 未处理 | 条件 network policy |
| PTY | 未验证 | base policy 含 pseudo-tty |
| Denial 检测 | 无 | `detect_denial()` |

**结论**：现有 stub **不能** 直接启用；应移植 Rust 逻辑或接 Claude SRT adapter。

---

## 5. Claude Code 对照

> 源码：`claude-code-main`（Anthropic 官方 CLI 反编译/恢复树）

### 5.1 架构

| 组件 | 路径 |
|------|------|
| 适配层 | `src/utils/sandbox/sandbox-adapter.ts` → `SandboxManager` |
| 运行时 | npm `@anthropic-ai/sandbox-runtime` |
| Bash 决策 | `packages/builtin-tools/src/tools/BashTool/shouldUseSandbox.ts` |
| 执行 wrap | `src/utils/Shell.ts` → `wrapWithSandbox()` |
| 设置 | `src/entrypoints/sandboxTypes.ts` |
| 文档 | `docs/safety/sandbox.mdx` |

### 5.2 与 DeepSeek 的关键差异

| 维度 | Claude Code | DeepSeek Rust |
|------|-------------|---------------|
| **OS 沙箱范围** | Bash + PowerShell + **Hooks（network-only profile）** | **仅 shell 工具路径** |
| **策略驱动** | `settings.sandbox.enabled` + 多项子设置 | **AppMode** → `sandbox_policy_for_mode` |
| **文件工具** | 应用层 permission + path | `resolve_path` + Plan registry 裁剪 |
| **审批联动** | `autoAllowBashIfSandboxed` | execpolicy + L1；L3 升格单独事件 |
| **Linux** | bubblewrap + seccomp | Landlock（不完整） |
| **清理** | `cleanupAfterCommand()` + bare-git scrub | 依赖 profile；无等价 cleanup hook |
| **Windows** | 不支持 native sandbox | 不支持（Job Object 计划中） |

### 5.3 可借鉴点

1. **统一 Shell 网关**：所有 spawn 经一层 `prepare()`，Python 应对齐 `ShellManager` 模式。
2. **Hook 最小沙箱**：Claude 对 hook 用 network-only sandbox；DeepSeek hook 目前是缺口。
3. **Settings 热更新**：Claude `SandboxManager.updateConfig()`；DeepSeek 可映射到 mode/config 变更时刷新 policy。
4. **SRT 作为可选后端**：不必重写 SBPL，可用 adapter 将 `ExecutionSandboxPolicy` 转为 SRT config（需评估与 Rust parity 差异）。

---

## 6. 工具级沙箱矩阵（完整）

图例：

- **OS** = 是否经 `SandboxManager.prepare()` / sandbox-exec
- **App** = 应用层（resolve_path / registry / approval / network policy）
- **N/A** = 不适用

### 6.1 Shell 类（OS 沙箱 = 是，除非 YOLO / external / OpenSandbox 替换）

| 工具 | OS | App | Rust | Python 现状 |
|------|----|-----|------|-------------|
| `exec_shell` | 是* | approval + execpolicy + command_safety | 完整 | 无 OS |
| `exec_shell_wait` | 是* | 同上 | 完整 | 无 OS |
| `exec_shell_interact` | 是* | 同上 | 完整 | 无 OS |
| `exec_shell_cancel` | 是* | 同上 | 完整 | 无 OS |
| `task_shell_start` | 是* | task + shell | 委托 ExecShell | 无 OS |
| `task_shell_wait` | 是* | task | 同上 | 无 OS |
| `run_tests` | 是* | 若内部 shell | 视实现 | 视实现 |

\* Agent/Plan 下为是；YOLO / external-sandbox 为否；OpenSandbox backend 为远程执行。

### 6.2 文件类（OS = 否，App = resolve_path + Plan 裁剪）

| 工具 | OS | App | Plan 模式 |
|------|----|-----|-----------|
| `read_file` | 否 | resolve_path | 可用 |
| `list_dir` | 否 | resolve_path | 可用 |
| `write_file` | 否 | resolve_path + L1 审批 | **不注册** |
| `edit_file` | 否 | 同上 | **不注册** |
| `apply_patch` | 否 | 同上 + 原生 patch | **不注册** |
| `grep_files` / `file_search` | 否 | resolve_path / workspace | 可用 |

### 6.3 Git 类（OS = 否，直接 git subprocess）

| 工具 | 说明 |
|------|------|
| `git_status` / `git_diff` / `git_log` / `git_show` / `git_blame` | Rust `Command::new("git")`，无 Seatbelt |
| `revert_turn` | Python 实现用 git checkout；同样无 OS 沙箱 |

### 6.4 网络类（OS = 否，NetworkPolicyDecider）

| 工具 | 审批（设计） |
|------|--------------|
| `fetch_url` | L1 要审（P3） |
| `web_search` / `web_run` | L1 不审（P2） |

### 6.5 MCP 类

| 工具 | OS | App |
|------|----|-----|
| `list_mcp_resources` 等读 | 否 | MCP 客户端 + 读不审 |
| MCP 动态写工具 | 否 | 写要审 |

### 6.6 子代理 / Task / Automation

| 工具 | OS | 隔离模型 |
|------|----|----------|
| `agent_*` / `delegate_*` | 否 | 子 Engine + 独立 ToolContext |
| `task_*` / `pr_attempt_*` | 否 | TaskManager 持久化 + 可选 shell |
| `automation_*` | 否 | AutomationManager 调度 |

### 6.7 知识 / 特殊

| 工具 | OS | 说明 |
|------|----|------|
| `rlm` / `rlm_query` | 否 | in-process REPL 沙箱（Python 已实现 repl 层） |
| `remember` / `recall_archive` | 否 | memory 文件路径 + trust |
| `multi_tool_use.parallel` | 否 | 只读子工具并行 |
| `request_user_input` | 否 | UI 阻塞，非 shell |
| `review` | 否 | LLM 子调用 |
| `validate_data` / `run_tests` | 否/是* | 纯本地或经 shell |
| `revert_turn` | 否 | git + snapshot |

### 6.8 Hooks（Rust：OS = 否 — 风险点）

| 事件 | 行为 |
|------|------|
| SessionStart/End, ToolCallBefore/After, MessageSubmit, ModeChange, OnError | 直接 shell |
| ShellEnv | 同步执行，stdout → env 注入 exec_shell |

### 6.9 `ToolCapability.SANDBOXABLE` 标记（Python registry）

标记了 `SANDBOXABLE` 的工具（表示 sandbox-aware，**非 OS wrap 列表**）：

- `ExecShellTool` 及 shell 系列
- `GitStatusTool` 等 git 工具
- 文件工具（Rust 侧）

---

## 7. 中间文件与可写路径策略

### 7.1 OS 沙箱内的磁盘写入规则（workspace-write）

命令行工具产生的中间文件（编译产物、临时下载、cache）必须落在允许路径内，否则 Seatbelt 拒绝（`sandbox_denied`）。

**默认可写根**（`SandboxPolicy.get_writable_roots(cwd)`）：

| 路径 | 用途 |
|------|------|
| **workspace cwd**（canonicalized） | 项目源码、build 输出 |
| **`writable_roots`**（config 扩展） | 额外挂载目录 |
| **`/tmp`** | 临时文件、socket（`exclude_slash_tmp` 可关） |
| **`$TMPDIR`** | macOS 用户 temp |
| **`$DARWIN_USER_CACHE_DIR`** | 工具缓存（Seatbelt 硬编码 allow） |
| **`$CARGO_HOME/registry` + `/git`** | cargo 缓存（非 read-only 策略） |

**可写根内的只读子路径**：

| 路径 | 原因 |
|------|------|
| `{writable_root}/.deepseek/` | 防止 shell 篡改 skills/config/settings |

### 7.2 内存中间态（不落盘）

| 数据 | 处理 |
|------|------|
| shell stdout/stderr | 进程内缓冲 → truncate → 返回模型 |
| background job tail | ShellManager 内存表 |
| workshop 大输出 | LargeOutputRouter 内存 + 可选 promote |
| approval 展示 | `build_approval_presentation()` 一次生成 |

### 7.3 Engine 管理的持久化中间产物（与 OS 沙箱独立）

| 产物 | 机制 | 路径 |
|------|------|------|
| Side-git **snapshots** (#137) | turn 前后 snapshot | workspace 旁 git repo |
| **Cycle archive** | 超上下文阈值 | session 目录 JSONL |
| **Task artifacts** | TaskManager | task data dir |
| **Session JSON** | auto-persist | `~/.deepseek/sessions/` |
| **Tool snapshot undo** | Engine pre-tool snapshot | git/side snapshot |
| **Compaction summary** | LLM 摘要 | system prompt 块 |

这些路径**不自动**受 Seatbelt 保护；若 shell 需写入 task data dir，应把该目录加入 `writable_roots` 或改用文件工具。

### 7.4 常见失败场景与对策

| 场景 | 现象 | 对策 |
|------|------|------|
| `npm install` 写 global cache | sandbox_denied | 允许 cache 路径或引导 `--cache .npm` 在 workspace |
| `cargo build` 首次 | 需写 ~/.cargo | Rust 已 allow registry/git |
| 写 `/var/folders/...`（TMPDIR 外） | denied | 使用 `/tmp` 或 workspace `.tmp/` |
| 改 `.deepseek/config.toml` via shell | denied（预期） | 应用层 read-only subpath |
| Hook 写任意路径 | **可能成功**（无沙箱） | Phase 5 hook 加固 |

### 7.5 清理策略

| 系统 | 清理 |
|------|------|
| Claude Code | `cleanupAfterCommand()` + bare-git scrub |
| DeepSeek Rust | 无统一 post-command cleanup；依赖 OS profile + 进程退出 |
| Python 建议 | Phase 4 可选：workspace 内 temp 目录 best-effort 清理；不清理 /tmp |

---

## 8. 审批与沙箱的三层模型（L1/L2/L3）

详见 [`APPROVAL_SYSTEM_DESIGN.md`](./APPROVAL_SYSTEM_DESIGN.md)。沙箱相关摘要：

```
┌─────────────────────────────────────────────────────────────┐
│ L1 工具门控  needs_tool_approval(tool, policy)              │
│     → ApprovalRequiredEvent → UI 卡片                        │
├─────────────────────────────────────────────────────────────┤
│ L2 命令/网络策略  exec_policy / network_policy              │
│     → 合并进 L1 或专用 ExecApproval                         │
├─────────────────────────────────────────────────────────────┤
│ L3 沙箱升格  OS sandbox_denied → ElevationRequired          │
│     → 独立「权限升格」卡（阶段 C，未实现）                    │
└─────────────────────────────────────────────────────────────┘
```

**事件命名修复（计划）**：

| 现名 | 应改为 | 语义 |
|------|--------|------|
| `SandboxDeniedEvent` | `ApprovalDeniedEvent` | L1 用户拒绝 |
| （缺失） | `SandboxViolationEvent` | OS Seatbelt 拒绝 |
| （缺失） | `ElevationRequiredEvent` | L3 请求升格 |

**Rust 升格 API**：`EngineHandle.retry_tool_with_policy(id, SandboxPolicy)`。

---

## 9. 配置项与环境变量

### 9.1 Rust / Python 共享概念

| 键 | 环境变量 | 用途 |
|----|----------|------|
| `sandbox_mode` | `DEEPSEEK_SANDBOX_MODE` | 合规枚举（见 §2.1 L0） |
| `sandbox_backend` | `DEEPSEEK_SANDBOX_BACKEND` | `none` / `opensandbox` |
| `sandbox_url` | `DEEPSEEK_SANDBOX_URL` | OpenSandbox base URL |
| `sandbox_api_key` | `DEEPSEEK_SANDBOX_API_KEY` | Bearer token |
| `allow_shell` | `DEEPSEEK_ALLOW_SHELL` | 是否暴露 shell 工具 |
| `approval_policy` | `DEEPSEEK_APPROVAL_POLICY` | L1 门控 |
| `yolo` | `DEEPSEEK_YOLO` | 信任模式 |

### 9.2 requirements 文件约束

Rust `RequirementsFile.allowed_sandbox_modes`：企业部署可限制用户可选的 `sandbox_mode`。

### 9.3 Workbench 映射（已知）

- `danger-full-access` → `trust_mode`（仅 Workbench 层，需与 Engine trust 同步验证）

---

## 10. 平台支持与已知限制

| 平台 | DeepSeek Rust | Python HANDOVER | Claude Code |
|------|---------------|-----------------|-------------|
| **macOS** | Seatbelt 完整 | Seatbelt **跳过** | sandbox-exec |
| **Linux** | Landlock 注释（需 helper） | 跳过 | bubblewrap |
| **Windows** | Job Object 未 advertise | 跳过 | 不支持 |
| **WSL2** | — | — | bubblewrap |

**PTY + sandbox**：Rust Seatbelt base policy 含 pseudo-tty；Python 已有 PTY 实现，接 Seatbelt 后需集成测试。

**OpenSandbox**：无 PTY/background/interactive。

---

## 11. 风险与开放问题

### 11.1 产品决策（实施前必须回答）

1. **是否推翻 Stage 2.7「不做 Seatbelt」决策？** 本计划 P1 需要用户重新批准。
2. **`config.sandbox_mode` 是否应覆盖 AppMode 映射？** Rust 当前 **不覆盖**；若 Python 覆盖则 non-parity。
3. **Parity 目标**：100% Rust 行为 vs「macOS 黑名单 + cwd 足够」？
4. **Hook 是否加沙箱？** Rust 无；Claude 有 network-only；DeepSeek Python 若不加则继承风险。

### 11.2 技术风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| Seatbelt profile 过严 | 正常 dev 命令失败 | 对齐 Rust cargo/tmp/cache 规则 + L3 升格 |
| Seatbelt profile 过松 | `.deepseek` 被 shell 篡改 | read-only subpath 必须移植 |
| Hook 无隔离 | hook 可 exfiltrate | 文档警告 + 可选 sandbox |
| `sandbox_mode` 与 mode 双源 | 用户困惑 | UI 展示 effective policy |
| Linux 无实现 | CI/Linux 用户无 OS 沙箱 | 应用层 gate 仍有效；或接 bubblewrap |
| OpenSandbox 与本地混用 | 双重重试逻辑复杂 | backend 互斥 |

### 11.3 开放问题

- Rust `config.sandbox_mode` 未来是否会 wired 到 runtime？（当前仅 validate/requirements）
- Python `NetworkPolicyConfig` 何时 fully wire 到 fetch/exec？
- RLM repl 沙箱与 OS sandbox 的文档边界是否要在 prompt 里说明？

---

## 12. 分阶段实施计划

> **本计划未排期**；估算供决策参考。每阶段须满足 HANDOVER **原则 B**（无孤岛）+ 原则 A（真实 API 路径需集成测）。

### Phase 0 — 文档与术语（1–2 天）

**产出**：

- 本文档（已完成）
- 在 `HANDOVER.md` 集成债区增加链接（可选）
- 事件 rename RFC（`SandboxDeniedEvent` → 拆分）

**不做代码**。

---

### Phase 1 — 应用层 enforcement（3–5 天）

**目标**：无 Seatbelt 也能对齐 Rust **registry + mode** 层保护。

| 任务 | 细节 |
|------|------|
| Plan 模式 | 确认 `build_default_registry(mode="plan")` 与 Engine mode 同步；禁止写工具 |
| `read-only` sandbox_mode | 拒绝 write/edit/patch/shell（或 shell 只读 policy 预检） |
| `danger-full-access` | 映射 `trust_mode` + Engine + Workbench 一致 |
| `external-sandbox` | 跳过本地 wrap 标志位（即使 Phase 2 未做 Seatbelt 也先设语义） |
| `resolve_path` 强化 | read-only 模式下文件工具 double-check |

**验收**：

- 单元测试：Plan 下 registry 无 shell/write
- 集成测试：mode=plan 时 write_file 不可用

---

### Phase 2 — Shell 统一网关 + SandboxManager 骨架（1–2 周）

**目标**：消除 `create_subprocess_shell` 直连；macOS 可选启用 Seatbelt。

**新建模块**（建议路径）：

```
src/deepseek_tui/sandbox/
├── policy.py       # 移植 SandboxPolicy + WritableRoot
├── manager.py      # prepare() / was_denied() / denial_message()
├── seatbelt.py     # 移植 seatbelt.rs SBPL 生成
└── types.py        # CommandSpec, ExecEnv, SandboxType
```

| 任务 | 细节 |
|------|------|
| `ShellExecutionGateway` | 唯一 spawn 入口；`shell_tools.py` 全部改道 |
| `prepare()` | Agent/Plan → 对应 policy（**AppMode 映射**，见 §3.3） |
| Seatbelt macOS | `-p` inline policy，非 stub 的 `-f` |
| Denial 检测 | 移植 `detect_denial` + metadata |
| Env 注入 | 保留 `_shell_env_from_hooks` 合并逻辑 |

**验收**：

- macOS 集成测：`echo ok` sandboxed 成功；写 `/etc/hosts` 失败且 `sandbox_denied`
- workspace 内 `touch foo` 成功；touch `.deepseek/config.toml` 失败

**依赖**：Phase 0 术语；**推翻** HANDOVER Stage 2.7 跳过决策。

---

### Phase 3 — 审批 / execpolicy / L3 联动（1 周）

| 任务 | 细节 |
|------|------|
| L2 收敛 | exec_shell PROMPT 必须走 L1，禁止静默 ToolResult |
| L3 UI | `ElevationRequiredEvent` + 升格选项（network / writable root） |
| Retry | `retry_tool_with_policy` 等价 API |
| 网络 hint | 移植 `command_likely_needs_network` |
| 事件 rename | 修正 `SandboxDeniedEvent` 语义 |

**验收**：

- 模拟 sandbox_denied → 升格 UI → 重试成功
- SSE / Workbench 契约更新（若暴露 L3 事件）

---

### Phase 4 — 中间文件与可写根完善（3–5 天）

| 任务 | 细节 |
|------|------|
| cargo/tmp/cache 规则 | 完整移植 seatbelt.rs #558 |
| `writable_roots` config | 支持 TOML 扩展根 |
| Task data dir | 若 task shell 写 artifacts，文档化或 auto-add root |
| `/doctor` 或启动 log | 打印 effective writable roots |
| 可选 cleanup | workspace `.tmp/` best-effort |

---

### Phase 5 — 外部与次要路径（1–2 周，可选）

| 任务 | 细节 |
|------|------|
| OpenSandbox backend | 移植 `backend.rs` + `opensandbox.rs` |
| PTY + sandbox 集成测 | macOS 必做 |
| Hook 沙箱 | network-only 或禁止写 workspace 外（**non-Rust parity**） |
| Claude SRT adapter | 评估替代自研 SBPL |

---

### Phase 6 — Workbench / 配置 UX（3–5 天，可选）

| 任务 | 细节 |
|------|------|
| 双字段展示 | `sandbox_mode`（合规）vs `effective_os_policy`（来自 mode） |
| 升格 UI | Workbench 权限升格卡 |
| settings 同步 | mode 切换刷新 policy |

---

### 不做 / 延后（除非需求变更）

- Linux Landlock 完整 helper（HANDOVER：跳过）
- Windows Job Object
- 100% Claude Code sandbox-runtime 行为克隆

---

## 13. 验收标准与 Parity 清单

### 13.1 核心 Parity（若宣称 Rust 对齐）

- [ ] Plan 模式：无 shell 工具；shell policy ReadOnly
- [ ] Agent 模式：WorkspaceWrite + network_access true
- [ ] Yolo：DangerFullAccess，无 sandbox-exec
- [ ] `.deepseek/` 在 workspace 内 shell 只读
- [ ] `/tmp` + `$TMPDIR` 可写（默认）
- [ ] `cargo build` 在 sandbox 内可运行（cache 规则）
- [ ] `sandbox_denied` metadata + L3 升格重试
- [ ] OpenSandbox：替换本地 spawn，限制 background/PTY
- [ ] git/file/network 工具 **不** 经 OS sandbox
- [ ] hooks **不** 经 OS sandbox（与 Rust 一致）

### 13.2 安全回归测试建议

```bash
# 示例场景（macOS + Seatbelt 启用后）
# 1. workspace 内写文件 — 应成功
# 2. workspace 外写 — 应 sandbox_denied
# 3. .deepseek 写 — 应 denied
# 4. curl example.com — Plan denied / Agent allowed
# 5. npm install — 应成功（cache 在允许路径）
```

### 13.3 与现有门禁关系

- 日常：`pytest tests/contract` + `tests/test_tui_smoke.py`
- 新增：`tests/integration/test_sandbox_*.py`（macOS opt-in，无 Seatbelt 环境 skip）
- `make check` / pre-commit 不应假设 Seatbelt 可用

---

## 14. 源码索引

### 14.1 Rust 参考（`docs/DeepSeek-TUI-main/`）

| 主题 | 路径 |
|------|------|
| SandboxPolicy | `crates/tui/src/sandbox/policy.rs` |
| SandboxManager | `crates/tui/src/sandbox/mod.rs` |
| Seatbelt SBPL | `crates/tui/src/sandbox/seatbelt.rs` |
| OpenSandbox | `crates/tui/src/sandbox/backend.rs`, `opensandbox.rs` |
| Shell 执行 | `crates/tui/src/tools/shell.rs` |
| Mode → Policy | `crates/tui/src/core/engine/tool_setup.rs` |
| ToolContext 构建 | `crates/tui/src/core/engine.rs` → `build_tool_context()` |
| Plan registry | `crates/tui/src/core/engine/tool_setup.rs` → `build_turn_tool_registry_builder()` |
| 文件工具 | `crates/tui/src/tools/file.rs` |
| Git 工具 | `crates/tui/src/tools/git.rs` |
| Hooks | `crates/tui/src/hooks.rs` |
| Config | `crates/tui/src/config.rs`（`sandbox_mode` validate, requirements） |
| ToolContext 类型 | `crates/tui/src/tools/spec.rs` |

### 14.2 Python 实现

| 主题 | 路径 |
|------|------|
| Stub sandbox | `src/deepseek_tui/execpolicy/sandbox.py` |
| Shell 工具 | `src/deepseek_tui/tools/shell_tools.py` |
| ToolContext | `src/deepseek_tui/tools/context.py` |
| Registry / Plan | `src/deepseek_tui/tools/builder.py` |
| Config | `src/deepseek_tui/config/models.py` |
| 审批设计 | `docs/APPROVAL_SYSTEM_DESIGN.md` |
| HANDOVER | `docs/HANDOVER.md` |

### 14.3 Claude Code 参考（外部）

| 主题 | 路径 |
|------|------|
| SandboxManager | `src/utils/sandbox/sandbox-adapter.ts` |
| shouldUseSandbox | `packages/builtin-tools/src/tools/BashTool/shouldUseSandbox.ts` |
| Shell wrap | `src/utils/Shell.ts` |
| 设置类型 | `src/entrypoints/sandboxTypes.ts` |
| 文档 | `docs/safety/sandbox.mdx` |

---

## 15. 历史决策记录

| 日期 | 决策 | 来源 |
|------|------|------|
| 2026-05-07 | Stage 2.7 Seatbelt **跳过**；macOS 用黑名单 + cwd + env 清洗 | `HANDOVER.md` §Stage 2 |
| 2026-05-07 | 子代理用 asyncio 非 multiprocessing | `HANDOVER.md` |
| 2026-05-27 | 审批 L1 设计锁定；L3 沙箱升格阶段 C | `APPROVAL_SYSTEM_DESIGN.md` |
| 2026-05-27 | 本文档：完整沙箱分析 + 分阶段计划（**待用户决定是否实施**） | 本文件 |

---

## 附录 A：架构图

```
                    ┌─────────────────────────────────────┐
                    │           用户 / Workbench           │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  Config: sandbox_mode (L0 合规)      │
                    │          approval_policy             │
                    │          allow_shell / yolo          │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  Engine: AppMode → ExecutionPolicy   │
                    │          build_tool_context()        │
                    └─────────────────┬───────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
          ▼                           ▼                           ▼
   ┌─────────────┐           ┌─────────────┐           ┌─────────────┐
   │ 文件/搜索   │           │  shell 类   │           │ 网络/MCP    │
   │ resolve_path│           │ ShellManager│           │ net policy  │
   │ Plan 裁剪   │           │      ↓      │           │ MCP client  │
   └─────────────┘           │ SandboxMgr  │           └─────────────┘
                             │      ↓      │
                             │ sandbox-exec│──────► OpenSandbox HTTP
                             └─────────────┘
                                      │
                             ┌────────▼────────┐
                             │ 中间文件必须在   │
                             │ writable_roots  │
                             │ + /tmp + cargo  │
                             └─────────────────┘
```

---

## 附录 B：若选择「不做 Seatbelt」的最小加固清单

若维持 HANDOVER 2026-05-07 决策，仍建议至少完成 **Phase 1**：

1. Plan registry 与 mode 严格同步  
2. `command_safety` + execpolicy + L1 审批保持启用  
3. `resolve_path` 拒绝 workspace 逃逸  
4. 文档明确：**无 OS 沙箱**，hook/shell 同 TUI 进程用户权限  
5. 修正 `SandboxDeniedEvent` 命名，避免 L1/L3 混淆  

此路径与 Rust 参考 **不对齐**，但成本最低。

---

*文档结束 — 实施前请在本文件 §11.1 产品决策处打勾确认。*
