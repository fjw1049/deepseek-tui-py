# DeepSeek-TUI Python 重写 — 总审核报告（SUMMARY）

**审核日期：** 2026-05-06
**审核范围：** 原始 Rust 项目 `docs/DeepSeek-TUI-main/` ↔ Python 重构 `src/deepseek_tui/`
**审核目标：** 用户明确要求"百分百复刻"，零简化

---

## 一、整体结论

**不达标。** 当前 Python 重构距离"百分百复刻"差距远超 5%。

| 维度 | Rust 原始 | Python 当前 | 真实 parity |
|---|---:|---:|---:|
| 源代码行数 | ~161,000 | 7,597 | **~5%** |
| 工具数量 | 74 个 | 32 注册（其中 ~24 真实，其余 stub/in-memory） | **~32%（真实）** |
| 模块结构覆盖 | 14 crates + 40+ tui 子模块 | 15 子模块 | **~30%** |
| 行为分支覆盖 | 高（PTY / sandbox / 持久化 / 流式 / 多进程子代理 / cron） | 低（多处 in-memory / stub / NotImplementedError） | **<10%** |

之前的 `ARCHITECTURE_AUDIT.md` 和 `COMPLETION_SUMMARY.md` 给出的"95% parity / 生产就绪"结论是基于**架构脚手架是否搭起**判断的，**不能反映真实行为复刻度**。本审核以源代码逐模块对比为依据，结论与之相反。

### 工程环境的额外发现（来自 MASTER_RECONSTRUCTION_AUDIT.md 真实跑命令）

- ⚠️ 项目目录 **不是 git 仓库**（`git status` 返回 `fatal: not a git repository`）。后续工作建议先 `git init` 并提交基线，否则历次审核与改动无法溯源。
- ⚠️ `.venv/bin/python` 链接已损坏，指向 `/Users/fjw/miniconda3/bin/python3`（非本机路径）。`make check` 在本机直接运行会失败。
- ⚠️ `ruff check src tests` 当前有 **16 项错误**（测试文件未使用 import / async 测试中误调 `pathlib` 同步方法等）。
- ✅ `mypy src` 在隔离 uv 环境下可通过（99 文件）。
- ✅ `pytest tests` 在隔离 uv 环境下：97 passed, 2 skipped。但**这只能说明对象能初始化、stub 能返回、内存状态可读写**，并不证明行为与 Rust 等价。

---

## 二、五阶段审核文件位置

每个阶段都有独立的详尽报告：

| 文件 | 行数 | 内容 |
|---|---:|---|
| [phase_A_protocol_config_secrets_state.md](AUDIT/phase_A_protocol_config_secrets_state.md) | 227 | 协议、配置、密钥、状态层 |
| [phase_B_client_engine_execpolicy.md](AUDIT/phase_B_client_engine_execpolicy.md) | 219 | LLM 客户端、引擎/核心、审批与沙箱 |
| [phase_C_tools.md](AUDIT/phase_C_tools.md) | 269 | 74 个工具完整清单 |
| [phase_D_mcp_lsp_hooks_appserver.md](AUDIT/phase_D_mcp_lsp_hooks_appserver.md) | 367 | MCP、LSP、Hooks、App Server |
| [phase_E_tui_cli_commands_prompts.md](AUDIT/phase_E_tui_cli_commands_prompts.md) | 421 | TUI、CLI、49 个 slash 命令、prompts、sub-managers |
| [MASTER_RECONSTRUCTION_AUDIT.md](AUDIT/MASTER_RECONSTRUCTION_AUDIT.md) | 240 | **补充审计**：跑过 `ruff`/`mypy`/`pytest`，发现 .venv 损坏、ruff 16 项错误、tool name codec 非可逆等运行时问题，五阶段总评 |
| 本文件 SUMMARY.md | — | 总缺口 + 行动计划 + 用户输入清单 |

---

## 三、各阶段 parity 一览

| Phase | 子模块 | Rust LOC | Python LOC | parity |
|---|---|---:|---:|---:|
| A | protocol | 501 | 231 | 46% |
| A | config | ~3,000 | 482 | 16% |
| A | secrets | 677 | 50 | 7% |
| A | state | 1,022 | 612 | 60% |
| B | client | 6,353 | 531 | 8% |
| B | engine / core / 长会话管理 | 20,512 | 543 | 3% |
| B | execpolicy + sandbox + safety | 5,803 | 256 | 4% |
| C | tools (74) | 25,965 | 2,914 | 11% |
| D | MCP | 3,501 | 430 | 28% |
| D | LSP | 1,382 | 483 | 35% |
| D | Hooks | 1,084 | 267 | 25% |
| D | App Server / Runtime | 7,925 | 252 | 3% |
| E | TUI 48 widgets | 47,753 | 481 | 1% |
| E | CLI | 3,405 | 53 | <2% |
| E | 49 slash 命令 | 7,699 | 0 | 0% |
| E | prompts + skills | ~2,070 + 17 文件 | 8 LOC stub | <5% |
| E | top-level sub-managers | ~30,000 | 0 | 0% |

---

## 四、最严重缺口（按优先级）

### 🔴 P0 — 阻断式：缺少这些就不能声称"复刻"

1. **引擎 turn_loop / capacity / compaction**（Phase B）
   - Rust：`core/engine/turn_loop.rs` 1,597 行 + `capacity_flow.rs` 975 行 + `compaction.rs` 2,008 行
   - Python：`engine/turn_loop.py` 83 行（无 capacity、无 compaction）
   - 影响：长对话 OOM；多轮工具调用不可靠；context window 无管理。

2. **沙箱与命令安全**（Phase B）
   - Rust：`sandbox/{seatbelt,landlock}.rs` 821 行 + `command_safety.rs` 1,200 行
   - Python：无 `sandbox/` 模块；`exec_shell` 直接 subprocess，无任何隔离
   - 影响：**严重安全漏洞**，`rm -rf /` 等危险命令无拦截。

3. **持久化任务系统 + 子代理 loop**（Phase C）
   - Rust：`task_manager.rs` 1,800 行 + `tasks.rs` 1,012 行 + `subagent/` 1,200 行 + agent crate 307 行
   - Python：全部 in-memory dict；`agent_spawn` 仅返回元数据，**子代理永不执行**
   - 影响：`task_*`、`pr_attempt_*`、`agent_*` 共 26 个工具实质上是空壳。

4. **App Server HTTP + 28 路由 + SSE 流**（Phase D）
   - Rust：`runtime_api.rs` 2,729 行 + `runtime_threads.rs` 4,413 行
   - Python：所有路由返回 `not_implemented`；HTTP server `raise NotImplementedError`
   - 影响：外部消费者完全不可用；turn 状态机不存在。

5. **49 个 slash 命令 + CLI 22 个子命令**（Phase E）
   - Rust：`commands/` 7,699 行 + `cli/` 3,405 行
   - Python：0 个 slash 命令；CLI 仅 53 行 stub
   - 影响：用户体验完全缺失；只能启动 TUI 主屏。

6. **TUI 顶层编排（ratatui→Textual 架构替换）**（Phase E）
   - Rust：`tui/ui.rs` 7,055 + `tui/app.rs` 4,140 + 47K 行 widget
   - Python：~481 行 9 个简单 widget
   - 影响：approval gate UI、command palette、file mention、流式 transcript、diff 渲染、markdown 渲染等核心交互全部缺失。

7. **30+ top-level sub-managers**（Phase E）
   - `task_manager`、`automation_manager`、`cycle_manager`、`compaction`、`seam_manager`、`session_manager`、`working_set`、`runtime_threads`、`runtime_api`、`network_policy`、`command_safety`、`workspace_trust`、`error_taxonomy` 等 ~30,000 行
   - Python：全部缺失。

8. **协议事件类型完整性**（Phase A）
   - Rust：`EventFrame` 20 个变体、`ThreadRequest` 10 个变体、`Envelope<T>` 包装
   - Python：缺少 IPC 协议 envelope 与多个事件变体
   - 影响：与 Rust 客户端的 IPC 不兼容。

9. **密钥管理优先级反转**（Phase A）
   - Rust：keyring → env → none（正确顺序）
   - Python：env → config → keyring（**顺序反了**）
   - 影响：环境变量泄漏到日志，覆盖了用户在 keyring 里的安全凭据。

10. **状态层时间戳类型不兼容**（Phase A）
    - Rust：`i64` Unix epoch
    - Python：`TEXT` ISO 8601
    - 影响：状态文件二进制不兼容，无法在 Rust/Python 间互通。

11. **DeepSeek tool name codec**（Phase B）
    - Rust：`to_api_tool_name`/`from_api_tool_name`，bare hex escape，62 行
    - Python：缺失
    - 影响：非 ASCII tool name 直接失败。

12. **Registry alphabetical sorting**（Phase C）
    - Rust：`registry.rs` 强制按字母序排（DeepSeek KV prefix cache 稳定性，issue #263）
    - Python：dict 顺序
    - 影响：每次工具变化都会失效 prefix cache，token 成本大增。

13. **Apply_patch fuzzy matching**（Phase C）
    - Rust：1,469 行，含 MAX_FUZZ=50、合并冲突检测
    - Python：朴素字符串替换
    - 影响：上下文偏移时静默失败。

14. **Approval cache fingerprinting**（Phase C）
    - Rust：280 行，按 `apply_patch` 路径、`exec_shell` 前 3 词、`fetch_url` hostname 指纹缓存
    - Python：缺失
    - 影响：每次相同操作都重复弹审批。

15. **17 个 prompt 模板 + skills 子系统**（Phase E）
    - Rust：base.md/base.txt/normal/agent/plan/yolo/compact/cycle_handoff/subagent_output_format + modes/personalities/approvals 子目录 + skills/ 2,070 行
    - Python：`engine/prompts.py` 8 行 stub
    - 影响：模型行为完全偏离 Rust 版本。

### 🟡 P1 — 高优先级（影响核心功能体验）

- HTTP MCP transport（Phase D）
- MCP 工具名 hash 截断（>64 字符）
- MCP stdio server（Python 只有 client）
- Webhook 重试与指数退避（Phase D）
- Hook events 完整集（SessionStart/End、MessageSubmit、ToolCallBefore/After、ModeChange、OnError）+ 条件（ToolName/ToolCategory/Mode/ExitCode/All/Any）（Phase D）
- 长会话管理：cycle_manager、working_set、seam_manager（Phase B）
- runtime_threads / runtime_api（Phase B+D）
- GitHub REST API（取代 gh CLI shell-out）（Phase C）
- Automation cron 调度（Phase C）
- RLM、Remember、Plan、Note、Skill_load、Validate_data、Run_tests、Truncate、User_input、Review、Recall_archive、Revert_turn（Phase C）
- 文件 PDF 提取 + URL HTML→Markdown（Phase C）
- Workspace trust 持久化（Phase B）
- Network policy + 审计日志（Phase B）
- Eval harness（Phase E）
- 命令面板、file mention、file picker、外部编辑器、sidebar、header/footer、键位绑定（Phase E）

### 🟢 P2 — 抛光

- LlmError 细分类、stream idle timeout 配置、连接池复用、mock harness（Phase B）
- Windows AppContainer（Phase B）
- 通知/OSC-8/clipboard、frame rate limiter、transcript cache、onboarding screen（Phase E）
- Localization（i18n 1,863 行）（Phase E）
- 主题（Phase E）
- 个性化 prompt（calm/playful）+ 审批策略解释（Phase E）
- UI 集成测试 harness（3,052 行）（Phase E）

---

## 五、整体工作量估算

| 类别 | 估算 LOC（Python 端） | 估算工时 |
|---|---:|---|
| Phase A 补缺 | ~1,800 | 3–4 周 |
| Phase B 补缺（client+engine+sandbox） | ~27,000 | 14–20 周 |
| Phase C 补缺（74 工具） | ~15,000 | 6–10 周 |
| Phase D 补缺（MCP/LSP/Hooks/AppServer） | ~6,500 | 6–8 周 |
| Phase E 补缺（TUI+CLI+commands+prompts+sub-managers） | ~40,000 | 16–24 周 |
| **合计** | **~90,000** | **45–66 周（1 名全职工程师）** |

按一人全职估，**实现"百分百复刻"约 9–14 个月**。如果引入 2–3 人并行，可压缩到 4–6 个月。

---

## 六、需要你（用户）提供的关键决策与输入

> **状态（2026-05-06 晚）：所有问题已答复，决策已固化。** 下方每个问题保留原文供溯源。

### Q1. TUI 框架是否接受 ratatui→Textual 的架构替换？

Rust 用 ratatui（即时模式）。Python 重构用 Textual（声明式 + async）。两者范式不同，逐行复刻不可能。
- **方案 A**：保留 Textual，承认这是"架构等价"而非"代码逐行复刻"，按 Rust 行为列表对照实现。
- **方案 B**：换成更接近 ratatui 的 Python 库（如 `prompt_toolkit` 直接渲染），代价是已写的 Textual 代码需重写。
- **方案 C**：放弃 Python 端 TUI，只做 headless（CLI/REPL/AppServer），后续再议 TUI。

**👉 需要你定方向。**

### Q2. 沙箱实现路径选哪条？

Rust 在 macOS 用 Seatbelt，在 Linux 用 Landlock，在 Windows 用 AppContainer。Python 不能直接调用这些系统调用。
- **方案 A**：通过 `subprocess` 拉起 `sandbox-exec`（macOS）和 `landlock`（Linux），与 Rust 行为一致。
- **方案 B**：用 Docker / `bubblewrap` 容器化每条 shell 命令。
- **方案 C**：纯 Python `seccomp` 绑定（pylibseccomp，仅 Linux）。

**👉 需要你定方向。**

### Q3. 子代理 runtime 用什么并发模型？

Rust 用 `tokio::spawn` 把每个 sub-agent 跑成独立 task。Python 候选：
- **方案 A**：`asyncio.Task`，单进程内并发（默认）。简单，但不是真隔离。
- **方案 B**：`multiprocessing` 子进程，每个 sub-agent 独立内存空间，更接近 Rust。
- **方案 C**：`subprocess` 拉起子 Python 解释器，与 Rust 完全等价。

**👉 需要你定方向。**

### Q4. App Server HTTP 用 aiohttp 还是 FastAPI？

Rust 用 axum。Python 候选：
- **方案 A**：FastAPI（推荐，OpenAPI、依赖注入、生态好）
- **方案 B**：aiohttp（轻量、纯 async）
- **方案 C**：Starlette（FastAPI 的底层）

**👉 需要你定方向。**

### Q5. 是否要加 SUMMARY 中标识的"协议二进制兼容"？

如果 Python 客户端需要和 Rust 服务端互通（例如运行 Rust app-server 然后 Python 客户端连接），就必须解决：
- 时间戳格式（i64 vs ISO 8601）
- EventFrame 全部 20 变体
- Envelope<T> 包装
- 字节序、字符串编码等细节

**👉 你的需求是只重构成纯 Python 项目（不与 Rust 互通），还是要保持二进制兼容？**

### Q6. 你想要的 prompt 文件是逐字翻译还是完全照搬英文？

Rust 自带 17 个 prompt 模板（base.md 210 行等）。
- **方案 A**：照搬英文原文，Python 加载即用（最快，最接近原行为）。
- **方案 B**：翻译成中文，可能改变模型行为。
- **方案 C**：双语并存。

**👉 需要你定方向。**

### Q7. 是否需要保留旧的 ARCHITECTURE_AUDIT.md / COMPLETION_SUMMARY.md？

它们与本次审核结论冲突（旧报告说"95% parity / 生产就绪"）。
- **方案 A**：保留作为"前期阶段成果"，加备注说明被本次审核修正。
- **方案 B**：归档到 `docs/AUDIT/legacy/` 下。
- **方案 C**：删除。

**👉 需要你定方向。**

### Q8. 数据/凭据资源

补齐过程会需要：
- **DeepSeek API Key** 一份（用于真实流式与定价测试，不需要长期使用）。
- **GitHub Token** 一份（github_* 工具的 REST API 端口）。
- **Linux 机器**（Linux Landlock 沙箱实现需要在 Linux 上写测试，如果你在 macOS 开发需要 CI / 远程 Linux 沙箱）。
- **Test fixtures**：原 Rust 项目里的部分测试数据（如 `crates/tui/tests/fixtures/`）是否允许复制到 Python 项目作为 parity 验证基准？

**👉 需要你确认能提供这些。**

### Q9. CLI 命令名是 `deepseek` 还是 `deepseek-tui`？

Rust 端 binary 名是 `deepseek`。Python 端 `pyproject.toml` 当前的 entry point 名应保持哪一个？两者会互相冲突时怎么处理？（Codex 在阶段 0 提出的待确认项。）

**👉 需要你定方向。**

### Q10. 是否允许引入 Playwright + 浏览器下载？

`web_run` 工具（1,763 行 Rust）需要浏览器自动化。Python 复刻需要 Playwright 或 Selenium 并下载 Chromium/WebKit 二进制（~300 MB）。CI / 开发机磁盘占用与下载策略需要确认。

**👉 需要你定方向。**

### Q11. `finance` 工具的数据源

`finance` 工具是 951 行的金融数据查询。需要明确：保留并指定数据源（哪个第三方 API + 是否你提供 API key），还是从默认 registry 移除并标为"不支持"？前者算复刻，后者不算。

**👉 需要你定方向。**

---

## 六·下. 已锁定决策（2026-05-06）

| 问题 | 决策 |
|---|---|
| Q1 TUI 框架 | **Textual 替代 ratatui，按功能行为等价**。承认架构等价，不追求像素级复刻。 |
| Q2 沙箱实现 | **命令黑名单 + 工作区 cwd 边界 + 环境变量清洗**。暂不引入 Docker，待主体完成后再迭代。 |
| Q3 子代理并发 | **`multiprocessing` 子进程**（方案 B），每个 sub-agent 独立内存空间。 |
| Q4 App Server | **FastAPI**。 |
| Q5 协议二进制兼容 | **不需要**（Python 版独立演进，不与 Rust app-server 互通）。 |
| Q6 prompt 翻译 | **照搬英文**，Python 加载即用。 |
| Q7 旧 AUDIT/COMPLETION 文档 | **已删除**。 |
| Q8 资源凭据 | DeepSeek API Key 已在 `config.toml`；GitHub 仓库 `git@github.com:fjw1049/deepseek-tui-py.git` 已建；Linux 沙箱后端跳过（本地 macOS 开发）。 |
| Q9 CLI 命令名 | **保持 `deepseek-tui`**（避免与未来可能安装的 Rust binary 冲突）。确认中（见下面"尚需确认"）。 |
| Q10 Playwright | 延后（web_run 不是 P0，Stage 3 再决策）。 |
| Q11 finance 数据源 | 延后（finance 列为 P2/可选，Stage 3 再决策）。 |
| **附加决策** Rust 原项目处置 | **保留 `docs/DeepSeek-TUI-main/` 作为 parity 审核参考基线**，不再动。 |
| **附加决策** 开发平台 | **macOS 本地**。Linux Landlock / Windows AppContainer 暂不做。 |

---

## 七、推荐的分阶段补齐计划

下面的顺序是为"最快达成可用 + 然后稳步逼近 100% parity"设计。每阶段建议产出一个可独立 review 的 PR。

> **顺序说明：** Stage 0 是 **Codex 的关键贡献**（见 `CODEX_VS_CLAUDE_DIFF.md`），它把工程基础和虚假完成度文档前置修复，避免在错误验收口径上继续推进。我之前漏列了这一步。

### Stage 0（1 周）：工程环境与文档校准（必须先做）

1. **`git init`** + 提交当前 baseline，保证后续审核与改动可溯源。
2. **修 `.venv`** —— 现在的 venv 链接到不存在的 `/Users/fjw/miniconda3/bin/python3`，`make check` 直接运行会失败。重建为本机 Python。
3. **修 `ruff check` 的 16 项错误**（async 测试中误调 `pathlib` 同步方法等）。
4. **改 `TASKS.md` / `COMPLETION_SUMMARY.md` / `ARCHITECTURE_AUDIT.md`** 中"完成 / 95% / 生产就绪"等失真措辞为真实状态，或归档到 `docs/AUDIT/legacy/`。
5. **建 parity 测试基础设施** —— 后续每补一个模块都需要一个 Rust fixture 对照测试，从 Stage 1 开始就要用。

完成时：工程基础正确、文档不再误导、有了可复用的 parity 测试范式。

### Stage 1（2–3 周）：协议与基础正确性

1. **修复密钥优先级**（`secrets/manager.py` 反向：keyring → env → file → none）
2. **修复时间戳类型**（state 全表改成 `INTEGER` Unix epoch）
3. **DeepSeek tool name codec**（`to_api_tool_name`/`from_api_tool_name`）
4. **Registry 字母序排序**（DeepSeek KV cache 稳定性）
5. **协议 EventFrame 全部变体 + Envelope<T>**
6. **配置 provider capability 矩阵补全**

完成时：基础正确性问题清零，可进入"加功能"阶段。

### Stage 2（4–6 周）：引擎与执行链

1. **engine/turn_loop 完整化**（从 83 行 → ~1,500 行 Python；对应 Rust `turn_loop.rs` 1,597 行）
2. **engine/capacity 全套**（token / step / cost / subagent budget + risk band）
3. **engine/compaction**（消息汇总、working_set 去重）
4. **engine/tool_parser**（tool call JSON 解析、片段重组）
5. **engine/tool_catalog**
6. **session_manager + cycle_manager + seam_manager**
7. **execpolicy 规则解析器 + matcher + policy evaluator**
8. **command_safety**（命令 arity 字典、危险模式检测）
9. **sandbox**（Seatbelt + Landlock 子进程包装）

完成时：长对话与多轮工具能稳定跑、危险命令被拦截。

### Stage 3（4–6 周）：工具系统 74/74

按 Phase C action items 顺序：
1. P0: 持久化 Task 系统、Sub-agent runtime、apply_patch 模糊匹配、PTY shell、approval cache。
2. P1: GitHub REST、automation cron、RLM/remember/plan/note/skill_load/validate_data/run_tests/truncate/user_input、PDF/HTML 提取。
3. P2: web_run（浏览器自动化）、finance、recall_archive、revert_turn。

### Stage 4（4–6 周）：MCP / LSP / Hooks / App Server

1. **App Server HTTP**（FastAPI 或 aiohttp）+ 28 路由 + SSE 流
2. **RuntimeThreadManager 状态机**（thread/turn 持久化、turn steering）
3. **MCP HTTP transport + stdio server + hash 截断**
4. **Hooks 全 7 类事件 + 条件 + webhook 重试**
5. **LSP hooks 集成、post-edit timeout**

### Stage 5（6–8 周）：CLI 与 slash 命令

1. **CLI 22 子命令** + ~25 个全局 flag
2. **slash 命令 dispatcher** + 49 个命令的 P0 子集（15 个）→ 全集
3. **prompt 模板** 17 个文件 + skills 子系统

### Stage 6（8–12 周）：TUI 完整化

1. **顶层 UI 编排**（ui.rs / app.rs 等价 Textual screens）
2. **流式 transcript + chunking + commit_tick**
3. **markdown / diff / approval / tool / subagent 渲染**
4. **command palette + file mention + file picker / file tree**
5. **sidebar / header / footer / status picker / context inspector**
6. **paste / external editor / clipboard / OSC-8 / notifications**
7. **localization、theme、onboarding、help screen**
8. **UI 集成测试（Textual snapshot）**

### Stage 7（2–4 周）：清理与 release

1. 删除 ARCHITECTURE_AUDIT.md / COMPLETION_SUMMARY.md（或归档）
2. 全套 e2e parity 测试（与 Rust mock client 比对事件流）
3. 性能基准（流式延迟、工具并发、内存占用、prefix cache 稳定性）
4. CI/CD、PyPI、Docker、文档

---

## 八、本轮审核的产出与状态

| 项目 | 状态 |
|---|---|
| 审核目录 `docs/AUDIT/` | ✅ 已建立 |
| Phase A 报告 | ✅ 227 行 |
| Phase B 报告 | ✅ 219 行 |
| Phase C 报告 | ✅ 269 行 |
| Phase D 报告 | ✅ 367 行 |
| Phase E 报告 | ✅ 421 行 |
| SUMMARY.md（本文件） | ✅ |
| `src/` 代码改动 | ❌ **本轮不动代码**（按你的选择"只产出审核报告"） |

---

## 九、下一步行动建议（一句话）

回答上面"六、需要你提供的关键决策"中的 8 个问题，然后我会基于你的选择逐阶段补齐 Stage 1。**优先建议从 Stage 1 (协议与基础正确性) 开始**，因为它修复的几处问题（密钥顺序反转、时间戳不兼容、tool name codec、registry 排序）是任何后续工作的基础，且改动量小（~600 行 Python），收益大。

