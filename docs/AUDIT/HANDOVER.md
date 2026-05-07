# DeepSeek-TUI Python 重构 — 接手指南 / HANDOVER

> 本文档是为**跨平台、跨对话、跨 AI 工具**继续这个项目而写的。读完这一份你就能接手。
>
> 最后更新：Stage 1.5 完成（2026-05-06）。

---

## 一、项目是什么

**源**：`docs/DeepSeek-TUI-main/`——一个 Rust 写的终端 AI Agent，大约 **161,000 行 Rust**，14 个 crates，包含 TUI、LLM client、engine、74 个工具、MCP/LSP/Hooks/App Server、49 个 slash 命令等。

**目标**：用 **Python** 做**百分百行为复刻**（架构和 UI 允许等价替换，但语义/行为必须一致）。

**仓库**：`git@github.com:fjw1049/deepseek-tui-py.git`

**关键约束**（这些是用户明确拍板的决策，接手时别动）：

| 决策 | 选择 |
|---|---|
| TUI 框架 | Textual 替代 ratatui，按功能行为等价 |
| 沙箱 | macOS 本地 + 命令黑名单 + cwd 边界 + env 清洗；暂不 Docker |
| 子代理并发 | `asyncio.Task` + child cancellation token（2026-05-07 翻案：Rust 用 tokio 协程，LLM 调用 IO bound，GIL 非瓶颈；multiprocessing 要重建 DeepSeekClient/ToolRegistry/ToolContext，工作量涨 2× 且 parity 测试都要改） |
| App Server HTTP | FastAPI |
| prompt | 照搬英文原文 |
| 协议二进制兼容 Rust | **不需要**（独立演进）—— 但 Stage 1.4 还是把 JSON shape 对齐了，因为这对多工具间接入更友好 |
| Rust 原项目 | 保留作 parity 参考基线 |
| 开发平台 | macOS 本地；跳过 Linux Landlock / Windows AppContainer |
| CLI binary | `deepseek-tui`（避免与 Rust `deepseek` 冲突） |

---

## 二、项目当前状态（2026-05-07）

### 已完成

| Stage | Commit | 核心产出 | 测试增量 |
|---|---|---|---:|
| 0 | `b9ab4c9` | git init + venv + ruff + parity 脚手架 | 99 passed |
| 1.1 | `c15acc3` | DeepSeek tool-name codec（可逆编码 + bare hex 容错） | +30 |
| 1.2 | `21d9ebd` | secrets 优先级反转 keyring→env→config + NVIDIA 别名链 + FileKeyringStore | +22 |
| 1.3 | `7a42e8e` | ToolRegistry 16 个方法补齐 + ApprovalRequirement + cache_control | +22 |
| 1.4 | `a7d3b82` | protocol IPC：Envelope/EventFrame×21/ThreadRequest×10/AppRequest×7/ToolPayload/ReviewDecision 等，Rust JSON parity | +72 |
| 1.5 | `8df5331` | provider_registry：ApiProvider×7 / ProviderKind×5 / ProviderCapability / context_window 含 NNNk hint | +77 |
| 2.1 | `dd78a8f` | engine/turn_loop 完整化（1,500 行）+ context checkpoint + tool_setup + capacity 状态机 | +13 |
| 2.2 | `afa2da4` | engine/capacity 容量控制系统（~750 行）+ GuardrailAction + RiskBand + cooldown | +17 |
| 2.3 | `500c4b4` | engine/compaction 消息汇总（~450 行）+ working_set 去重 + 智能 pin + LLM 总结 | +23 |
| 2.4 | `fd8ac3c` | engine/tool_parser 文本工具解析 + 流片段重组（~470 行）+ 5 种格式 + 智能 fallback | +25 |
| 2.5 | `f5fa794` | execpolicy 集成：Policy 绑定 ToolContext + exec_shell Decision 检查（FORBIDDEN/PROMPT） | +0 |
| 2.6 | `b3b0d83` | command_safety 分析：SafetyLevel×4 + COMMAND_ARITY 163 前缀 + 11 级检查管道 + 危险模式检测 | +24 |
| 3.1 | `c8c72e1` | durable Task 系统：TaskManager（~700 行）+ JSON 文件持久化 + 重启恢复（Running→Queued）+ 11 工具接通 | +33 |
| 3.2 | `3cbf9a9` | Sub-agent runtime：SubAgentManager（~600 行）+ Mailbox（9 种消息 + 单调 seq）+ asyncio.Task 调度 + 重启恢复（Running→Interrupted）+ 10 工具接通 | +42 |
| 3.3 | `7456887` | apply_patch 原生实现：patch_engine.py（~400 行）+ MAX_FUZZ=50 模糊匹配 + 累积偏移 + create/delete via /dev/null + 重写 ApplyPatchTool 不再外调 `patch` 命令 | +27 |
| 3.4 | `7456887` | PTY shell：stdlib `pty.openpty()` + `os.fork()` 模式 + exec_shell `pty=true` 参数 + Wait/Interact/Cancel 兼容 PTY 句柄 + 解除 task_shell_start/wait 空壳（artifacts 记录到 TaskRecord） | +6 (PTY) +2 (task shell) |
| 3-int | `dca3816` | **集成**：tasks feature flag + builder 注册 53 工具 + `create_tool_runtime`/`ToolRuntime` 一站式装配 + `Engine.create()` 工厂方法 | +7 |
| 4.1 | `6f7c630` | **App Server**：FastAPI + uvicorn 7 路由（healthz/thread/app/prompt/tool/jobs/mcp/startup）+ AppRuntime 单例共享 + ThreadStore（内存）+ 更新后的 stdio JSON-RPC 走同一 AppRuntime + `deepseek-tui serve` CLI 子命令 | +19 |
| 4.1.x | `23a5712` | **/prompt Rust parity**：handle_prompt emit ResponseStart/Delta/End 3-frame 序列 + /prompt/stream SSE 路由 + SseStream event: data: 双字段框 | +4 |
| 4.2 | `1ccd563` | **Hooks 集成**：HooksConfig + _build_hook_dispatcher + AppRuntime 挂 dispatcher + handle_prompt/stream_prompt/handle_tool/jobs 各自 emit 对应 HookEvent + 修 WebhookHookSink dead code + retry 200ms×N 对齐 Rust | +14 |
| 4.3 | `61a4901` | **MCP SSE/HTTP transport**：McpTransport 抽象（stdio + SSE）+ McpClient 重构走 transport + pending-id map 并发支持 + ToolRuntime 挂 McpManager + Config 自动加载 mcp.json + AppRuntime.mcp_startup 真实 per-server 状态 | +12 |
| 4.4 | `22438d2` | **LSP post-edit hook 接通 engine**：edited_paths_for_tool / parse_patch_paths + Config.lsp + ToolRuntime 挂 LspManager + Engine.pending_lsp_blocks + _run_post_edit_lsp_hook + flush 注入 synthetic user message | +22 |
| 4.1.nn | `234dbe9` | **/prompt/stream 接真实 Engine**：engine_event_to_sse 桥接 12 种 EngineEvent + AppRuntime.stream_prompt 可注入 LLMClient → 驱动 Engine → 产生真实 SSE 事件流；含真实 DeepSeek API 集成测（config.toml api_key 自动 opt-in） | +9 |
| 3.next.1 | `1d97997` | **approval cache 指纹**：ApprovalKey/Cache/Status + build_approval_key（patch: 路径 hash / shell: classify_command / net: host / tool:\*）+ Engine 集成（session grant 绕过 handler）+ classify_command 修正 Rust parity（剥 flags；未匹配返 positional[0]） | +17 |
| **累计** | | | **665 passed, 2 skipped** |

### 五阶段缺口审核（`docs/AUDIT/`）

五份详尽审核 + 一份 SUMMARY + 一份 Codex vs Claude 差异对比，2,382 行。**接手时必读 `SUMMARY.md` 第七节（Stage 0–7 路线图）**。

### make check

```
make check  # = ruff + mypy + pytest
# 全绿：ruff / mypy 0 errors，pytest 322 passed, 2 skipped
```

### 关键已修 bug

1. `.venv/bin/python` 曾指向另一台机器的 `/Users/fjw/miniconda3/...`——已用 `/opt/homebrew/bin/python3.12` 重建。
2. ruff 16 项错误（未用 import / async 测试误调 `pathlib`）——已清零。
3. 密钥优先级反了（env 优先于 keyring，违反 Rust 安全规则）。
4. Tool name 不可逆（`multi_tool_use.parallel` 会被毁成 `multi_tool_use_parallel`）。

---

## 三、接下来要做什么（路线图）

按 `docs/AUDIT/SUMMARY.md` 第七节，剩余 Stage 2–7，合计 29–42 周（一名全职）。

### Stage 2（4–6 周）：engine 核心 + execpolicy

**P0 任务**（按顺序）：

1. `engine/turn_loop.py` 从 83 行 → ~1,500 行
   - **读** `crates/tui/src/core/engine/turn_loop.rs`（1,597 行）
   - 事件循环、tool polling、approval gate、capacity checkpoints
2. `engine/capacity.py` 新建 ~750 行
   - **读** `crates/tui/src/core/capacity.rs`（784）+ `capacity_flow.rs`（975）
   - token / step / cost / subagent budget + risk band + GuardrailAction
3. `engine/compaction.py` 新建 ~1,800 行
   - **读** `crates/tui/src/compaction.rs`（2,008 行）
   - 消息汇总 + working_set 去重 + cache-breakpoint
4. `engine/tool_parser.py` 新建
   - **读** `crates/tui/src/core/tool_parser.rs`（510）
   - 流式工具调用片段重组
5. `execpolicy/` 整套重写
   - **读** `crates/tui/src/execpolicy/{parser,matcher,policy,rules,amend,rule,decision,error}.rs`（~1,286 行）
6. `execpolicy/command_safety.py` 新建 ~1,000 行
   - **读** `crates/tui/src/command_safety.rs`（~1,200 行）
   - 163 命令 arity 字典 + 危险模式（`rm -rf`, `dd`, `format` 等）
7. ~~`execpolicy/sandbox/seatbelt.py`~~ — **已跳过**（2026-05-07 用户决定）
   - 原因：macOS Seatbelt OS 级隔离不做；命令黑名单 + cwd 边界 + env 清洗已足够
   - 详见集成债清单（第九节）

### Stage 3（4–6 周）：74 工具补齐

按 `docs/AUDIT/phase_C_tools.md` 的 inventory 表逐行推进。

**Stage 3 本次窗口只做这 4 个核心 P0**（用户 2026-05-07 决定）：

1. ~~durable Task 系统~~ ✅ **Stage 3.1 已完成**（commit `c8c72e1`）—— 实际用 JSON 文件持久化，不是 SQLite
2. **Sub-agent runtime**（用 `asyncio.Task` + child CancellationToken，与 Rust tokio 协程对齐；**不**用 multiprocessing，2026-05-07 翻案）
3. **apply_patch 模糊匹配**（Rust `MAX_FUZZ=50` + 合并冲突检测）
4. **PTY shell**（用 `ptyprocess` 或 `pexpect`；不集成 Seatbelt，见第九节集成债）

**以下工具延后到 Stage 3.next**（核心逻辑跑通后再做）：

5. ~~approval cache 指纹~~（延后）
6. ~~web_run / Playwright~~（延后）
7. ~~RLM / Remember / Plan / Skill / Validate_data / Test_runner / Truncate / Request_user_input 等~~（延后）

### Stage 4（4–6 周）：MCP / LSP / Hooks / App Server

1. **FastAPI App Server + 28 路由**（`docs/AUDIT/phase_D_...md` 有完整路由表）
2. **RuntimeThreadManager**（Rust `runtime_threads.rs` 4,413 行）
3. **SSE 流**（turn.started / message.delta / tool.progress / approval.required / turn.completed）
4. **MCP HTTP transport + stdio server**
5. **Hooks 7 类事件 + 条件 + webhook 重试**（Rust `hooks.rs` 914 行）

### Stage 5（6–8 周）：CLI + slash 命令 + prompts

1. **22 个 CLI 子命令**（`doctor / models / sessions / resume / fork / init / setup / exec / review / apply / eval / mcp / features / serve / completions / login / logout / auth / config / model / thread / sandbox / app-server / metrics / update`）
2. **49 个 slash 命令**（`docs/AUDIT/phase_E_...md` 有完整表）
3. **17 个 prompt 模板**（从 `crates/tui/src/prompts/` 直接复制 `.md` / `.txt` 文件到 Python 项目）
4. **skills 子系统**（Rust 2,070 行）

### Stage 6（8–12 周）：TUI 完整化

按 Phase E 审核，48 个 ratatui widget → Textual 等价实现。P0：

1. `tui/ui.rs` 顶层编排（7,055 行）→ Textual App screens
2. `tui/app.rs` 事件循环（4,140 行）
3. 流式 transcript + chunking + commit_tick
4. Markdown / diff 渲染
5. approval gate UI
6. command palette + file mention + file picker

### Stage 7（2–4 周）：收尾

1. e2e parity 测试（与 Rust mock client 事件流比对）
2. 性能基准
3. CI/CD、PyPI、Docker

---

## 四、**工作方法论**：任何 AI 接手都按这个流程走

这是我和用户对齐后的**协作模式**，严格执行可以避免 90% 的返工：

### 步骤 0 — 心态：遇到问题不许随意简化（2026-05-06 用户要求）

> 用户原话："简化流程一定是遇到问题一定要告知我为什么要简化，可以做哪些替代方案，而不是遇到问题一味的简化。"

**硬约束：任何"简化"（stub / 跳过 / 降级 / `NotImplementedError` / 返回硬编码值）都必须先经过以下流程。禁止隐式简化。**

遇到一个难点（Rust 行为复杂 / 依赖库不存在 / 时间不够 / 不确定怎么做）时：

1. **停下写代码**。不要自作主张用 stub 糊过去。
2. **向用户说明**（用 `AskUserQuestion` 工具）：
   - **为什么卡住**：哪个 Rust 行为难复刻？缺什么依赖？边界不清楚在哪？
   - **至少 2 个替代方案**：每个方案的代价 + 后果 + 什么时候能补回"百分百"。
   - **推荐哪个**：说清楚你的推荐理由，但**不替用户决定**。
3. **用户决策后**写代码，并在 **commit message + 代码注释**里写清楚"本处是简化，原因 X，用户于日期 Y 批准方案 Z，补齐计划 W"。
4. **简化项必须进集成债清单（第九节）**。无论用户选哪个方案，只要当前不是"百分百 Rust 行为"，就记一条 `⬜ <stage>.simplified: <feature>`，写清楚"还需做什么才能恢复完整行为"。

**反例**（禁止）：
- ❌ "Rust 用了 Starlark crate，Python 没有，我直接跳过了 policy parser，返回空 Policy"
- ❌ "这个字段 Rust 是 i64 timestamp，改起来麻烦，我留 str 了"
- ❌ "web_run 需要 Playwright，先返 NotImplementedError 吧"

**正例**（按流程）：
- ✅ "Rust 用 Starlark DSL，Python 没现成库。我用 AskUserQuestion 给了 3 方案：手写 mini-parser / 引入 starlark-python 包 / 只支持 TOML 子集。用户选 1。我实现了 mini-parser 覆盖 `prefix_rule(...)` 语法，注释里写清楚了不支持 `def/if/for/import`，集成债清单里留了一条 `⬜ 2.1.simplified: full Starlark grammar (currently mini-subset)`。"

### 步骤 1 — 读 Rust 源，提炼行为清单

**不要**看到 Rust 代码就直接翻译。先：

1. `wc -l` 看文件规模
2. `grep -nE '^pub (fn|struct|enum)' <file>` 列出所有 public 符号
3. 对每个 P0 符号完整 `Read` 一次
4. **一定要找测试文件**（`tests/*.rs` 或 `#[cfg(test)] mod tests`）——Rust 的测试就是最权威的行为规范

### 步骤 2 — 给用户**行为清单 + 决策点**

发给用户前按这个结构写：

```markdown
## Stage X.Y — <功能名> 行为清单

### 🎯 目标
<一句话>

### 📊 Rust 里有什么
- 类型 / 函数 / 常量清单（带 Rust 文件:行号引用）
- 关键魔数 / 阈值

### 🐍 Python 现状
- 哪些已实现、哪些缺失、哪些不兼容

### 📋 我打算怎么改
- 要新增 / 修改的文件清单
- 旧 API 怎么兼容（还是直接破坏）

### ⚠️ 需要你决策的点
- 用 AskUserQuestion 工具列出 1-3 个关键选择
```

**用户确认后再动手写代码**。这是最重要的一条。

### 步骤 3 — 写实现

三个原则：

1. **Rust 文件:行号注释**：每个新建的 Python 文件顶部要写 "Mirrors `crates/.../foo.rs:xxx-yyy`"，每个关键函数要写对应的 Rust 行号。
2. **保留旧 API 兼容**：重写某个模块时，**旧的 public 函数名 / 参数 / 返回类型都保留**，内部委托到新实现。避免级联改动。
3. **不要加代码注释解释代码在做什么**（`CLAUDE.md` 的指示）。只在解释"为什么"时写注释。

### 步骤 4 — 写 parity 测试

测试放 `tests/parity/phase_{a-e}/test_<feature>.py`。分两类：

1. **直接移植 Rust `#[test]`**——每个 Rust 测试对应一个 Python 测试，测试名前加 `test_`，函数体翻译。测试 docstring 里写 "Mirror of Rust `<test_name>` (path:line)"。
2. **Python 补充边界测试**——Rust 原本没覆盖但明显值得测的 edge case。

### 步骤 5 — 验证 + 提交

每个 stage 必做三项：

```bash
PYTHONPATH=src .venv/bin/python -m ruff check src tests
PYTHONPATH=src .venv/bin/python -m mypy src
PYTHONPATH=src .venv/bin/python -m pytest tests
```

**三项必须全绿**才能 commit。

Commit message 模板（严格遵循）：

```
Stage X.Y: <one-line summary>

<为什么这个 stage 重要；对应的 P0 审核项>

## What changed

- <文件>:
    <做了什么>

## Tests

tests/parity/phase_X/test_<name>.py — N tests:
- <测试覆盖面>

## make check

ruff: All checks passed!
mypy: Success: no issues found in XXX source files
pytest: <N> passed (<prev> + <delta>), 2 skipped

Co-Authored-By: <your-coauthor-tag>
```

然后 `git push origin main`。

### 步骤 6 — 更新 HANDOVER.md

每个 Stage 完成后，追加到本文档的"已完成"表；如果路线图有调整，更新第三节。

---

## 五、**绝对不要做的事**

（这些都是我踩过坑或者用户明确说过的）

1. **不要盲目 `git add -A`**——总是先 `git status` 看一眼，可能包含你不想提交的删除/改动。Stage 1.5 就是这个教训。
2. **不要跳过行为清单直接写代码**——即使功能看起来简单。Rust 实现往往有魔数 / 边界 / 历史修复，翻译时很容易漏。
3. **不要用 `Exception` 做 `pytest.raises`**（ruff B017）——用具体类型如 `ValidationError`。
4. **不要在 Python 里加"改进"**——比如看到 Rust 代码重复就想抽象，这会破坏 parity 可审计性。
5. **不要静默降级**——比如 `finance` 工具复杂就返回 stub；用户明确要"百分百复刻"。真要 escape 也得先问。
6. **不要在测试用例里调真实的 keyring / 真实 API**——总用 `InMemoryKeyringStore` 或 mock。
7. **不要改 `docs/DeepSeek-TUI-main/`**——这是只读的 parity 参考。
8. **不要在工作区外找 Rust 源**——所有 Rust 源都在 `docs/DeepSeek-TUI-main/crates/`。
9. **不要写"孤岛代码"**——新模块写完后 `grep -rn '<new symbol>' src/` 在它自己的模块外**没有任何匹配**就是债，必须按步骤 7 在同一 Stage 内还清，或明确记入第九节集成债务清单。2026-05-06 用户原话："光写代码进来有什么用，主要是为了用起来"。
10. **不要用"全是 mock 的测试"冒充集成验证**——单元测试 + mock 测"对象能初始化"；集成测"运行时调用链激活"；真实 API 测"wire 行为与真实对端吻合"。三者必须共存。
11. **不要 skip 真实 API 测试"因为没 key"**——`tests/_real_api.py` helper 先看 `DEEPSEEK_API_KEY` 再看 `config.toml`，本地只要有 config.toml 就自动跑。
12. **不要写无意义测试**——参见步骤 4 的黑名单。2026-05-06 清理移除了 34 个此类测试。新增测试前先过 3 问自检。
13. **不要隐式简化**（2026-05-06 用户要求）——任何"stub / 跳过 / 硬编码 / NotImplementedError / 降级"都要按步骤 0 先问用户，不许自作主张。简化完成后在集成债清单补一条 `⬜ <stage>.simplified: <feature>`。
14. **不要一次性堆大量不可跑的代码**（2026-05-06 用户要求）——参见第三节"路线图编排原则"。如果本次提交的代码**没有任何 make check / 真实 API 测试路径能触发**，它就是孤岛，拆小或延后，不许提交。

---

## 六、跨对话 / 跨 AI 接手时的速查

### 上手前必读（按顺序）

1. `AGENTS.md` + `CLAUDE.md` — 项目级 AI 指令
2. **`docs/AUDIT/SUMMARY.md`** — 最重要，列出所有缺口和 Stage 路线图
3. `docs/AUDIT/CODEX_VS_CLAUDE_DIFF.md` — 之前的方法论对比
4. `docs/AUDIT/phase_{A-E}_*.md` — 对应想做的 Stage 看对应 phase
5. 本文档

### 环境搭建

```bash
# 已在 README 里；核心命令：
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
make check  # 所有绿 = 环境 OK
```

### 每个 Stage 的推进模板

```
阶段 X.Y: <feature>
├── 阶段 X.Y.a：读 Rust 源 + 写行为清单 → AskUserQuestion
├── 阶段 X.Y.b：写实现（src/deepseek_tui/<module>/<file>.py）
├── 阶段 X.Y.c：写 parity 测试（tests/parity/phase_<letter>/test_<feature>.py）
├── 阶段 X.Y.d：make check 三项全绿
└── 阶段 X.Y.e：commit + push + 更新 HANDOVER.md
```

### 常用命令

| 场景 | 命令 |
|---|---|
| 查 Rust 文件结构 | `grep -nE '^pub (fn\|struct\|enum)' <file>` |
| 查 Rust 测试 | `grep -n '#\[test\]\|fn test_' <file>` |
| 对比行数 | `wc -l <rust-file> <python-file>` |
| 看已有调用面 | `grep -rn '<symbol>' src/ tests/` |
| 跑单个 parity 测试 | `PYTHONPATH=src .venv/bin/python -m pytest tests/parity/phase_X/<file>.py -v` |
| 跑完整 make check | `PYTHONPATH=src .venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src && PYTHONPATH=src .venv/bin/python -m pytest tests` |

### 遇到问题时的决策树

1. **Rust 行为不清楚** → 读 Rust 测试（`#[test]` 或 `tests/*.rs`）
2. **Rust 用了奇特的 serde / macro** → 看它生成的 JSON 样本（运行 Rust 测试 `cargo test -- --nocapture` 或看 fixtures）
3. **Python 写了但行为和 Rust 不符** → 对比 Rust / Python 测试断言；**Rust 才是真理**
4. **选库选不准**（如 FastAPI vs aiohttp） → 查 `SUMMARY.md` 第六节锁定的决策；没锁的用 `AskUserQuestion` 问用户
5. **性能 / 工作量超预期** → 别偷偷降级，用 `AskUserQuestion` 告诉用户原因并给方案

---

## 七、附：项目目录结构（Stage 1.5 末）

```
deepseek-tui-py/
├── .venv/                                # Python 3.12 venv（已 gitignore）
├── config.toml                           # 用户 API key（已 gitignore）
├── config.example.toml
├── docs/
│   ├── AUDIT/                            # 五阶段缺口审核 + 路线图 + 本文档
│   │   ├── SUMMARY.md                    # 最重要
│   │   ├── CODEX_VS_CLAUDE_DIFF.md
│   │   ├── HANDOVER.md                   # ← 你现在看的
│   │   ├── MASTER_RECONSTRUCTION_AUDIT.md
│   │   ├── phase_A_protocol_config_secrets_state.md
│   │   ├── phase_B_client_engine_execpolicy.md
│   │   ├── phase_C_tools.md
│   │   ├── phase_D_mcp_lsp_hooks_appserver.md
│   │   └── phase_E_tui_cli_commands_prompts.md
│   └── DeepSeek-TUI-main/                # Rust 原项目（parity 参考基线，不修改）
├── src/deepseek_tui/
│   ├── app_server/                       # Stage 4 要重写
│   ├── cli/                              # Stage 5 要重写
│   ├── client/                           # Stage 2.? 要扩
│   ├── config/                           # Stage 1 补过 provider_registry
│   ├── engine/                           # Stage 2 要重写
│   ├── execpolicy/                       # Stage 2.5/2.6 已集成 ✓（不含 sandbox 子目录，Seatbelt 跳过）
│   ├── hooks/                            # Stage 4 要补
│   ├── lsp/                              # Stage 4 微调
│   ├── mcp/                              # Stage 4 补 HTTP + stdio server
│   ├── protocol/                         # Stage 1.4 已全部补齐 ✓
│   │   ├── app.py / approval.py / errors.py / events.py /
│   │   ├── ipc.py / mcp_lifecycle.py / messages.py / prompt.py /
│   │   └── requests.py / responses.py / threads.py / tool_payload.py
│   ├── secrets/                          # Stage 1.2 已全部补齐 ✓
│   │   ├── env_map.py / errors.py / facade.py / file_store.py /
│   │   └── manager.py / store.py
│   ├── state/                            # Stage 2 要补（SQLite schema 对齐）
│   ├── tools/                            # Stage 3 要补齐 74 个
│   │   ├── base.py / builder.py / context.py / encoding.py (已改 ✓) /
│   │   └── registry.py (已改 ✓) / <各工具文件>
│   └── tui/                              # Stage 6 要重写
├── tests/
│   ├── parity/                           # Rust parity 测试
│   │   ├── conftest.py
│   │   ├── rust_fixtures/                # Rust 参考样本目录
│   │   ├── phase_a/                      # 已有：test_secrets.py, test_protocol.py, test_provider_capability.py
│   │   ├── phase_b/                      # 已有：test_tool_name_codec.py
│   │   └── phase_c/                      # 已有：test_registry.py
│   └── test_*.py                         # 其余模块测试
├── .gitignore
├── AGENTS.md
├── CLAUDE.md
├── Makefile
├── pyproject.toml
└── README.md
```

---

## 八、给任何接手 AI 的三句话

1. **用户要的是百分百行为复刻**，不是最快完成；任何想偷工减料的地方先问用户。
2. **Rust 才是规范**；Python 的旧实现很多地方是错的（从 Stage 0 审核可见）。每个 stage 前先读 Rust 源。
3. **每完成一个 P0 就 commit + push**；不要累积改动超过一个逻辑单元。用户希望能在 GitHub 上审阅每一步。

---

## 九、集成债清单（Simplification Debt）

按照第四节步骤 0 的要求，任何偏离"百分百 Rust 行为复刻"的简化都必须记在这里。每条写清楚：**简化了什么、为什么、恢复完整行为需要做什么**。

| 条目 | Stage | 简化内容 | 原因 | 恢复完整行为需要做什么 |
|---|---|---|---|---|
| ⬜ 2.7.simplified: macOS Seatbelt sandbox | 2.7 | 跳过 `sandbox/seatbelt.py` 不实现；`exec_shell` 直接 `subprocess.create_subprocess_shell()` 无 OS 级隔离 | 用户 2026-05-07 决定：命令黑名单 + cwd 边界 + env 清洗足够本地开发用；Seatbelt 做完约 ~800 行工作量换来的是"OS 级兜底"，在本地开发场景收益不高 | 参考 `crates/tui/src/sandbox/{mod,policy,seatbelt}.rs`（~1,364 行），实现：1) `SandboxPolicy`（读/写/执行 allowlist） 2) `SeatbeltProfile` XML 生成 3) `exec_shell` 子进程用 `sandbox-exec -p <profile>` 包装 4) `CommandSpec` 编排器 |
| ⬜ 3.1.simplified: TaskExecutor 占位版 | 3.1 | `task_manager.py::_stub_executor` 只 sleep 50ms 返回合成 summary，不真实调用 LLM / 不驱动 engine / 不真正产出 artifacts | 用户 2026-05-07 决定：让 TaskManager 的持久化/队列/状态机/重启恢复四层骨架今天落地；真 Executor 等 Stage 4 engine 链接通后替换 | 实现 `EngineTaskExecutor`：接 `engine/turn_loop` + `client/deepseek_client` + `ToolRegistry`，把 Rust `task_manager.rs::EngineTaskExecutor`（行 413-699）行为翻过来 —— 含 `TaskExecutionEvent` 流 + `apply_execution_event` + runtime_event_count 累加 + 产出 artifacts |
| ✅ 3.1.simplified: task_shell_start/wait 空壳 | 3.1 | `TaskShellStartTool` / `TaskShellWaitTool` 原为 `raise ToolError("not yet implemented")` | PTY shell 归在 Stage 3.4 | **Stage 3.4 已还清**（commit `7456887`）：两工具直接调 `ExecShellTool`（pty=True 默认），wait 时把 output 以 `TaskArtifactRef` 形式记到 `TaskRecord.artifacts` 并 append timeline 事件；`task_shell_wait` 额外接受 `task_id` 关联任务 |
| ✅ 4.1.simplified: /prompt 不调 LLM | 4.1 → 4.1.next → 4.1.nn | 原为 3-frame placeholder；**已还清**（commit `234dbe9`）：AppRuntime.stream_prompt 注入 LLMClient 时走真实 Engine → turn_loop → DeepSeekClient → SSE，12 种 EngineEvent 全部桥接；无 client 时保持 3-frame placeholder（向后兼容）。含真实 DeepSeek API 集成测（/prompt/stream → flash 模型 → "pong" round-trip） | — | — |
| ⬜ 3.2.simplified: SubAgent 占位 Executor | 3.2 | `subagent/manager.py::_stub_executor` sleep 50ms 返合成 result；没有真实 LLM 调用 / 没 turn loop / 没工具派发 / 不累加 token usage | 用户 2026-05-07 决定：让 Manager+Mailbox+持久化+重启恢复+10 工具接口今天落地，LLM 驱动等 Stage 4 接通 | 实现 `LlmSubAgentExecutor`：用 `DeepSeekClient` + mini turn loop + 为 sub-agent 构建过滤过的 `ToolRegistry`（按 `agent_type.allowed_tools()`）+ 发 `MailboxMessage.tool_call_started/completed` + 发 `MailboxMessage.token_usage`。参考 Rust `mod.rs:1077+`（run_loop / dispatch_tool / handle_api_response）约 ~800 行 |
| ⬜ 3.2.simplified: 7 种 SubAgentType 的 system prompt 未拷 | 3.2 | 只实现了类型枚举 + `allowed_tools()` 推荐清单；各类型的 **system prompt** 没从 `crates/tui/src/prompts/` 拷进来 | prompt 文件和 executor 强耦合，等真 Executor 落地一起做 | 把 `GENERAL_AGENT_PROMPT / EXPLORE_AGENT_PROMPT / PLAN_AGENT_PROMPT / REVIEW_AGENT_PROMPT / IMPLEMENTER_AGENT_PROMPT / VERIFIER_AGENT_PROMPT / CUSTOM_AGENT_PROMPT` 7 份从 Rust 常量整理到 `src/deepseek_tui/prompts/subagent_*.md` 并在 `SubAgentType.system_prompt()` 加载 |

> **约定**：✅ 已还清 / ⚠️ 部分还清 / ⬜ 未还清

---

## 十、联系方式（用户侧）

- 仓库：https://github.com/fjw1049/deepseek-tui-py
- 用户 ID: fjw1049
- 开发机：macOS（Python 3.12.13 via Homebrew / uv）
- 用户自述："我不太懂 Rust"——所以行为清单写给用户看时，要**用人话解释 Rust 在做什么**。

---

**本文档会随每个 Stage 完成而追加"已完成"条目。如果发现本文档与实际状态不符，以 git log 和 `docs/AUDIT/SUMMARY.md` 为准。**
