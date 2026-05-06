# DeepSeek-TUI Python 重构 — 接手指南 / HANDOVER

> 本文档是为**跨平台、跨对话、跨 AI 工具**继续这个项目而写的。读完这一份你就能接手。
>
> 最后更新：Stage 2.1 完成 + Integration #1 完成（2026-05-06）。

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
| 子代理并发 | `multiprocessing` 子进程 |
| App Server HTTP | FastAPI |
| prompt | 照搬英文原文 |
| 协议二进制兼容 Rust | **不需要**（独立演进）—— 但 Stage 1.4 还是把 JSON shape 对齐了，因为这对多工具间接入更友好 |
| Rust 原项目 | 保留作 parity 参考基线 |
| 开发平台 | macOS 本地；跳过 Linux Landlock / Windows AppContainer |
| CLI binary | `deepseek-tui`（避免与 Rust `deepseek` 冲突） |

---

## 二、项目当前状态（2026-05-06）

### 已完成

| Stage | Commit | 核心产出 | 测试增量 |
|---|---|---|---:|
| 0 | `b9ab4c9` | git init + venv + ruff + parity 脚手架 | 99 passed |
| 1.1 | `c15acc3` | DeepSeek tool-name codec（可逆编码 + bare hex 容错） | +30 |
| 1.2 | `21d9ebd` | secrets 优先级反转 keyring→env→config + NVIDIA 别名链 + FileKeyringStore | +22 |
| 1.3 | `7a42e8e` | ToolRegistry 16 个方法补齐 + ApprovalRequirement + cache_control | +22 |
| 1.4 | `a7d3b82` | protocol IPC：Envelope/EventFrame×21/ThreadRequest×10/AppRequest×7/ToolPayload/ReviewDecision 等，Rust JSON parity | +72 |
| 1.5 | `8df5331` | provider_registry：ApiProvider×7 / ProviderKind×5 / ProviderCapability / context_window 含 NNNk hint | +77 |
| 2.1 | `04eb1fa` + `df44565` + `0bd776d` | execpolicy 全量重写：Decision / Policy / PolicyParser (mini-Starlark) / matcher / amend / rules TOML；**没接入运行时** | +53 |
| **Integration #1** | `469b650` | tool-name codec 接入 `ToolRegistry._serialise_tool` + `OpenAIStreamParser`；**真实 DeepSeek API 验证 round-trip** | +8 (+2 unskipped) |
| **累计** | | | **385 passed, 0 skipped** |

### ⚠️ 集成债（必读）

Stage 1.1–2.1 的代码**大部分是"孤岛"**：写进来、parity 测试过，但运行时从来不调。2026-05-06 用户指出此问题后，引入了新的强制约束（见[四·步骤 7](#步骤-7--集成债务处理每个-stage-必做)）。

**已还清**：
- ✅ Integration #1（codec）—— commit `469b650`，真实 API 验证过

**未还清（按顺序处理，每条一个独立 commit）**：
- ⬜ Integration #2：`provider_capability` 接入 `client/deepseek.py._build_payload`
- ⬜ Integration #3：`ApprovalRequirement` 接入 `engine/engine.py:_execute_tool_calls`
- ⬜ Integration #4：`Secrets.auto_detect()` 接入应用启动入口
- ⬜ Integration #5：execpolicy `Policy.check` 接入 `shell_tools.py`（需配合 Stage 3 shell 重写）
- ⬜ Integration #6：`EventFrame` 接入 `app_server` SSE（需配合 Stage 4 App Server 重写）

详见第九节"[集成债务清单](#九集成债务清单还清路线图)"。

### 五阶段缺口审核（`docs/AUDIT/`）

五份详尽审核 + 一份 SUMMARY + 一份 Codex vs Claude 差异对比，2,382 行。**接手时必读 `SUMMARY.md` 第七节（Stage 0–7 路线图）**。

### make check

```
make check  # = ruff + mypy + pytest
# 全绿：ruff / mypy 0 errors，pytest 385 passed, 0 skipped
```

### 关键已修 bug

1. `.venv/bin/python` 曾指向另一台机器的 `/Users/fjw/miniconda3/...`——已用 `/opt/homebrew/bin/python3.12` 重建。
2. ruff 16 项错误（未用 import / async 测试误调 `pathlib`）——已清零。
3. 密钥优先级反了（env 优先于 keyring，违反 Rust 安全规则）。
4. Tool name 不可逆（`multi_tool_use.parallel` 会被毁成 `multi_tool_use_parallel`）。

---

## 三、接下来要做什么（路线图）

按 `docs/AUDIT/SUMMARY.md` 第七节，剩余 Stage 2–7，合计 29–42 周（一名全职）。

### Stage 2（4–6 周）：engine 核心 + execpolicy + sandbox

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
7. `execpolicy/sandbox/seatbelt.py` 新建
   - **读** `crates/tui/src/sandbox/{mod,policy,seatbelt}.rs`（~1,364 行）
   - macOS Seatbelt XML profile 生成

### Stage 3（4–6 周）：74 工具补齐

按 `docs/AUDIT/phase_C_tools.md` 的 inventory 表逐行推进。关键 P0：

1. **durable Task 系统**（SQLite 表 `tasks` / `task_attempts` / `task_gates` + 7 个 task 工具）
2. **Sub-agent runtime**（用 `multiprocessing` 子进程 + mailbox，不是 `asyncio.Task`）
3. **apply_patch 模糊匹配**（Rust `MAX_FUZZ=50` + 合并冲突检测）
4. **PTY shell**（用 `ptyprocess` 或 `pexpect`，集成 Seatbelt）
5. **approval cache 指纹**（280 行 Rust → Python，按 apply_patch 路径 / exec_shell 前 3 词 / fetch_url hostname 指纹）
6. **web_run**（Playwright 集成，需要用户授权浏览器下载）
7. **RLM / Remember / Plan / Skill / Validate_data / Test_runner / Truncate / Request_user_input** 等

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

### 步骤 7 — 集成债务处理（每个 Stage 必做）

> **这是最容易被跳过、但也是最容易让"为了重构而重构"滋生的步骤。**

在 2026-05-06 之前，Stage 1.1–2.1 的方法论漏了这一条——结果 **6 个 Stage、~3,700 行代码、240+ parity 测试**都是孤岛：写进来了，parity 测试过了，但运行时**没有任何调用链真的调它们**。用户指出问题后加入此步骤作为硬性约束。

**验收门槛（3 条缺一不可）**：

1. **运行时调用**：新实现至少被 `src/deepseek_tui/<其他模块>/*.py` 中的一处生产代码调用（不是只在 parity 测试里）。
2. **旧实现退役**：相同语义的旧代码被替换 / 删除 / 加 `DeprecationWarning`。不能让新旧并存留下"反正都能用"的幻觉。
3. **e2e 测试覆盖**：在 `tests/integration/test_<feature>_wire.py` 中至少加一组：
   - 编码/解码/编排方向的**单元集成**（验证 wire 格式、调用链激活）
   - **真实 API 验证**（用 `tests/_real_api.py` 的 helper 读 `config.toml` 的 DeepSeek key；`has_deepseek_api_key()` 为 False 时 auto-skip）
   - mock 测试**保留**但**不是唯一**（"全是 mock 的测试无法证明真的跑起来了"——用户原话）

**集成债样例（已实施，作参考）**：Integration #1 = commit `469b650`。查看那个 commit 了解标准动作：
- 代码改动两处（`tools/registry.py` + `client/streaming.py`），每处都附注释指向 Rust 源行号
- `tests/_real_api.py` 作为共享 helper 从 `config.toml` 读真实 key
- `tests/integration/test_tool_name_wire.py` 8 个测试：4 wire-encode + 3 wire-decode + 1 live DeepSeek
- Commit message 里写 **"Verification"** 段，记录真实 API 调用的实际输出（如 `decoded names: ['namespace.dot_tool']`）

**Commit message 模板（集成债专用）**：

```
Integration #N: wire <feature> into runtime

The Stage <X.Y> (commit <hash>) added <module> with N parity tests, but
nothing called it — <explain the bug that integration fixes>.

This commit closes the integration debt for Stage <X.Y>.

## What changed

src/deepseek_tui/<module>/<file>.py
    <具体改动 + Rust 源行号注释>

## Tests

tests/integration/test_<feature>_wire.py (new, N tests)
    - M unit integration tests for encode/decode path
    - 1 live <provider> round-trip (auto-skip when no key)

## Verification

Live run confirmed: <引用真实 API 返回的关键断言>

## make check

ruff: All checks passed!
mypy: Success: no issues found in N source files
pytest: N passed (was M; +delta integration + X previously-skipped
        real_api tests now run)
```

**什么时候加集成债，什么时候在 Stage 内部就集成**：

- **每个新 Stage**：默认要求 Stage 内部就完成"运行时 + 退役 + e2e"三件事，不准产生新的债。
- **遇到依赖缺失**：如果新模块接入点依赖一个还没做的模块（比如 Integration #5 execpolicy 需要 shell_tools 还没重写），记入"集成债"（见第九节），Stage 过线，**但必须在最终 release 前全部还清**，禁止带着集成债发布。

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
9. **不要写"孤岛代码"**——新模块写完后如果 `grep -rn '<new symbol>' src/` 在它自己的模块外**没有任何匹配**，就是债，必须按第四·步骤 7 在同一 Stage 内还清，或明确记入第九节的集成债务清单。2026-05-06 用户原话："光写代码进来有什么用，主要是为了用起来"。
10. **不要用"全是 mock 的测试"冒充集成验证**——单元测试 + mock 测的是"对象能初始化"；集成测的是"运行时调用链激活"；真实 API 测的是"wire 行为与真实对端吻合"。三者必须共存，缺一不等于完成。
11. **不要 skip 真实 API 测试"因为没 key"**——`tests/_real_api.py` 的 helper 会先看 `DEEPSEEK_API_KEY` env，再看 `config.toml` 的 `[providers.deepseek] api_key`。本地只要有 `config.toml` 就会自动跑起来；真的没 key 再 auto-skip。

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
│   ├── execpolicy/                       # Stage 2 要重写（+ 新增 sandbox/）
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

---

## 九、集成债务清单（还清路线图）

> 本节是**独立于 Stage 路线图**的并行工作清单。每条债务一个独立 commit，命名 `Integration #N: wire <feature> into runtime`。**剩余 5 条必须按顺序还清。**

### 还清原则

1. **按风险递增**：#1 最小 → #6 最大。每条打磨通了再下一条，不并行处理。
2. **不扩展新功能**：集成债只做"接入 + 退役 + e2e"，遇到 Rust 新语义需要补实现的，拆到新 Stage 做。
3. **每条一个 commit**：方便 GitHub 上逐条 review。
4. **卡住就写**：如果某条债因为依赖缺失还不动（如 #5 依赖 shell_tools 重写），**在本节里更新"阻塞"字段**，不删除。最终 release 前必须全部还清。

### ✅ Integration #1 — tool-name codec 接入运行时

- **Commit**：`469b650`
- **接入点**：`tools/registry.py:_serialise_tool` 编码 wire name；`client/streaming.py:OpenAIStreamParser` 解码回流 name
- **退役**：无（之前这条路径根本不调 codec）
- **e2e 测试**：`tests/integration/test_tool_name_wire.py` —— 7 个单元 + 1 个真实 DeepSeek round-trip
- **真实验证输出**：`✓ live round-trip decoded names: ['namespace.dot_tool']`

---

### ⬜ Integration #2 — `provider_capability` 接入 `client._build_payload`

- **Stage 依赖**：Stage 1.5（`8df5331`）
- **接入点**：`src/deepseek_tui/client/deepseek.py`
  - 在 `_build_payload()` 顶部调 `provider_capability(ApiProvider.parse(provider), model)`，拿到 `cap`
  - 若 `request.max_tokens is None`，默认取 `cap.max_output`
  - `stream_options.include_usage` 只在 `cap.cache_telemetry_supported` 为 True 时开启
  - 若 `cap.deprecation is not None`，在构造请求前发一次 `warnings.warn(cap.deprecation.notice, DeprecationWarning)`
- **退役**：
  - `client/chat_messages.py` 里如果还有写死的 `max_tokens` 或 `include_usage`，统一走 capability
  - 删除任何硬编码的 128_000 / 1_000_000 上下文窗口常量
- **e2e 测试**：`tests/integration/test_provider_capability_wire.py`
  - 单元：mock 一个 `DeepSeekClient._build_payload`，断言 `deepseek-v4-pro` 输出 `max_tokens=262_144`、`stream_options.include_usage=True`
  - 单元：mock `deepseek-chat`（legacy），断言 `DeprecationWarning` 被触发
  - 真实 API：用 `config.toml` 的 key 跑 `deepseek-v4-pro` 一次短对话，断言 usage 里包含 `cache_read_input_tokens` 字段（`cap.cache_telemetry_supported=True` 的证据）
- **风险**：低
- **阻塞**：无

### ⬜ Integration #3 — `ApprovalRequirement` 接入 `engine._execute_tool_calls`

- **Stage 依赖**：Stage 1.3（`7a42e8e`）
- **接入点**：`src/deepseek_tui/engine/engine.py:_execute_tool_calls`
  - 在工具执行前，先读 `tool.approval_requirement()`，根据返回的 `ApprovalRequirement.AUTO / SUGGEST / REQUIRED` 决定是否触发 `approval_handler.request_approval(...)`
  - 替代当前的 `ExecPolicyEngine.evaluate(tool_name, capabilities)` 启发式（由 capability 推断 risk level）
- **退役**：
  - `execpolicy/engine.py:_assess_risk` / `_classify_category`（capability 启发式）改为**fallback**（当 tool 没覆盖 `approval_requirement()` 时才用）
  - `execpolicy/models.py:RiskLevel / ToolCategory` 加 `DeprecationWarning`
- **e2e 测试**：`tests/integration/test_approval_requirement_wire.py`
  - 单元：注册一个 `approval_requirement() == REQUIRED` 的 tool；让 engine 走一轮对话让 LLM 调它；断言 `ApprovalRequiredEvent` 被发射
  - 单元：注册一个 `AUTO` 的 tool；断言无 approval event
  - 真实 API：用 DeepSeek 跑一次让它调用一个 SUGGEST 级别的 tool（比如模拟 `write_file`），断言 approval gate 触发一次
- **风险**：中（改 engine 主路径）
- **阻塞**：无

### ⬜ Integration #4 — `Secrets.auto_detect()` 接入应用启动入口

- **Stage 依赖**：Stage 1.2（`21d9ebd`）
- **接入点**：
  - `src/deepseek_tui/__main__.py` / `src/deepseek_tui/cli/`：启动时调 `Secrets.auto_detect()`，注入给 `SecretsManager(secrets=...)`
  - 确保 `Engine` / `DeepSeekClient` 的初始化路径上 API key 真的走 `keyring → env → config.toml` 优先级
- **退役**：
  - 任何直接读 `os.environ["DEEPSEEK_API_KEY"]` 的代码（应 grep 一次全项目）
  - 旧 `SecretsManager()` 无参默认构造已经用新 façade，但没人显式建 —— 加到启动入口
- **e2e 测试**：`tests/integration/test_secrets_wire.py`
  - 单元：mock keyring 存一个 key，断言启动时优先读它
  - 单元：keyring 空、env 空、config.toml 有 key → 读 config.toml
  - 真实 API：在 macOS Keychain 里存一个 test key（`security add-generic-password -s deepseek -a deepseek -w sk-test`），启动 DeepSeekClient，断言读到的是 keyring 值（之后清理）
- **风险**：中（涉及 macOS keyring 操作）
- **阻塞**：无

### ⬜ Integration #5 — execpolicy `Policy.check` 接入 `shell_tools`

- **Stage 依赖**：Stage 2.1（`04eb1fa` + `df44565` + `0bd776d`）
- **接入点**：`src/deepseek_tui/tools/shell_tools.py:ExecShellTool`
  - `execute()` 入口处：`tokens = shlex.split(command); evaluation = policy.check(tokens, heuristic_fallback)`
  - `Decision.FORBIDDEN` → 返回 `ToolResult(success=False, content="blocked by execpolicy: ...")`
  - `Decision.PROMPT` → 走 approval gate
  - `Decision.ALLOW` → 直接跑
  - `heuristic_fallback` 接 Stage 2.2（command_safety）的危险模式检测
- **退役**：
  - `execpolicy/sandbox.py`（当前 stub）—— Stage 2.5 Seatbelt 完成后统一替换
- **e2e 测试**：`tests/integration/test_execpolicy_wire.py`
  - 单元：注册 Policy 让 `git status` = ALLOW，`rm -rf /` = FORBIDDEN；分别调 shell tool 验证
  - 真实 API：让 DeepSeek 调用 `exec_shell` 跑 `git --version`（应 ALLOW）和 `rm -rf /tmp/does-not-exist`（应 FORBIDDEN 或 PROMPT）
- **风险**：高（改 shell 主路径 + 影响真实文件系统）
- **阻塞**：**需要先完成 Stage 3 shell_tools 真实化重写**（当前是 in-memory stub，没真正跑命令，也没 tokens 可 check）

### ⬜ Integration #6 — `EventFrame` 接入 `app_server` SSE

- **Stage 依赖**：Stage 1.4（`a7d3b82`）
- **接入点**：
  - `src/deepseek_tui/app_server/server.py` + `sse.py`：用 `ResponseDeltaEvent / TurnCompleteEvent / ToolCallStartEvent / ...` 等具体变体替代当前 stub
  - `src/deepseek_tui/hooks/events.py` 的 `GenericEventFrameEvent` 桥接到新 `EventFrame` 联合类型，不再定义独立事件类
  - engine 发射事件时走统一的 `EventFrame` 序列化
- **退役**：
  - `hooks/events.py` 的 6 个内部事件类（除了保留 hook-payload 形式用的）
  - `app_server/sse.py` 的 stub
- **e2e 测试**：`tests/integration/test_event_frame_wire.py`
  - 单元：启动一个 mock app server，发送一次 turn，断言 SSE stream 里出现 `event: turn_started` / `event: response_delta` / `event: turn_complete`
  - 真实 API：启动 app server，用 `curl -N` 或 httpx async client 订阅 `/v1/threads/{id}/events`，跑一次真实 DeepSeek 对话，断言 SSE 里收到至少 3 个 EventFrame 变体
- **风险**：高（涉及 SSE 流 + 多组件协调）
- **阻塞**：**需要先完成 Stage 4 App Server FastAPI 重写**（当前 `app_server/server.py` 大部分是 `NotImplementedError`）

---

### 集成债版本化

本清单**随项目演进会增加新条目**。约定：

- 任何新 Stage 完成后，如果发现新模块没被调用链覆盖，**在本节追加 `⬜ Integration #N`**，不是隐藏
- 完成一条就把 `⬜` 改 `✅`，写上 commit hash + 真实验证输出
- `HANDOVER.md` 的"已完成"表在顶部、集成债清单在底部——顶部庆祝、底部催账，两个视角互相校验

### 工作流断链

如果接手 AI / 你发现某个"集成债"清单项描述与实际代码不符（比如接入点文件路径变了、Rust 源 reorganize 了），**以 git log + `docs/AUDIT/SUMMARY.md` 为准**。本文档是导航，不是唯一真相。

---

## 十、联系方式（用户侧）

- 仓库：https://github.com/fjw1049/deepseek-tui-py
- 用户 ID: fjw1049
- 开发机：macOS（Python 3.12.13 via Homebrew / uv）
- 用户自述："我不太懂 Rust"——所以行为清单写给用户看时，要**用人话解释 Rust 在做什么**。

---

**本文档会随每个 Stage 完成而追加"已完成"条目。如果发现本文档与实际状态不符，以 git log 和 `docs/AUDIT/SUMMARY.md` 为准。**
