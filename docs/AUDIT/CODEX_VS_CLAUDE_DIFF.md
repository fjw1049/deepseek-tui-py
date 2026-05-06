# Codex vs 本次（Claude）审核 — 差异分析

**日期：** 2026-05-06
**Codex 报告：** [MASTER_RECONSTRUCTION_AUDIT.md](MASTER_RECONSTRUCTION_AUDIT.md)
**本次审核：** [SUMMARY.md](SUMMARY.md) + Phase A–E 五份报告

用户需求：百分百复刻。这份文件只讲我和 Codex 的不同意见，相同结论不再赘述。

---

## 0. 共识（先确认我们站在同一边）

两份审核在以下结论上完全一致：

- 当前 Python 重构**不是 95% parity**，更像"骨架 + 部分 happy path + 大量同名占位"。
- 旧的 `ARCHITECTURE_AUDIT.md` 和 `COMPLETION_SUMMARY.md` 的"95% / 生产就绪"判断**错了**。
- P0 缺口高度重合：tool name codec 不可逆、secrets 顺序反转、state schema 时间戳不兼容、sandbox 缺失、subagent loop 不存在、task/automation 仅内存、apply_patch 无模糊匹配、app_server HTTP/28 路由全是 stub、49 slash 命令全空、prompt 模板全缺、~30K LOC sub-managers 全缺。
- Codex 推荐的"先做阶段 0（环境校准）再做阶段 1（协议/密钥/状态底座）"路径与我建议的 Stage 1 一致。

下面只列**不同意见**与 Codex 报告**没覆盖到**或**判断有偏差**的地方。

---

## 1. Codex 报告的优势（我承认它做得比我好的地方）

### 1.1 跑了真实的工程命令，发现 Codex 独家的事实

Codex 实际在隔离 uv 环境下跑了 `make check` / `ruff` / `mypy` / `pytest`，发现：

- ⚠️ **`.venv/bin/python` 链接已坏**（指向不存在的 `/Users/fjw/miniconda3/bin/python3`）。
- ⚠️ **`ruff check src tests` 有 16 项错误**（async 测试中误调 `pathlib` 同步方法等）。
- ⚠️ **项目目录不是 git 仓库**。
- ✅ `mypy src` / `pytest tests` 在隔离环境下能跑通。

我的审核**完全没跑这些命令**，只读源码做对比。这是 Codex 比我更有价值的地方——它揭示了**工程基础**层面的隐患，这些问题不读源码看不出来。

### 1.2 "测试通过 ≠ 行为复刻" 的判断更尖锐

Codex 一句话点出了核心问题：
> 多项测试只验证"对象能初始化 / 桩返回 not_implemented / 内存状态可读写"，没有覆盖 Rust 的真实流程。

我的审核虽然也提到测试覆盖不充分，但没有 Codex 这么直接地揭示"现在的 97 passed 是假象"。

### 1.3 阶段 0（环境校准 + 文档状态修正）

Codex 把"先修 venv、修 ruff、修 TASKS.md/COMPLETION_SUMMARY.md 中的虚假完成度"独立列为阶段 0。这一点**我的 SUMMARY 漏写了**——我直接从协议层缺口跳到了 Stage 1。这是真正应该最先做的事。

### 1.4 LSP post-edit 注入路径的具体描述

Codex 指出 LSP 当前缺的不是 client，而是"**diagnostics 没 flush 回下一次 API 请求的 synthetic user message**"。这个具体的注入点描述比我的 phase D 报告更精准。

---

## 2. 我比 Codex 更深 / 更细的地方

### 2.1 数量化细节（行数、文件级清单、字段级对比）

我的 phase 报告里有 Codex 没给的具体数字：

- Rust 共 161,000 行，Python 7,597 行，**比例 ~21:1**。
- `tui/` 目录 47K 行 widget 拆 48 个文件，**逐文件 LOC 列了表**。
- 49 个 slash 命令逐条列了**命令名 + 别名 + Rust 文件 + 行数 + 用途 + Python 状态**。
- 28 个 HTTP 路由逐条列了**路径 + method + 用途**。
- 17 个 prompt 模板逐文件列了**文件名 + 行数**。
- 74 个工具完整 inventory 表（**tool 名 / Rust 文件 / 行数 / 用途 / Python 状态 / 严重等级**）。

Codex 报告偏定性，缺了这种"可以直接拿来当工单"的清单。补齐的时候 Codex 报告不能直接交付给工程师，我的报告可以。

### 2.2 工作量估算

我给了具体数字：~90,000 LOC Python 待补，**45–66 周（一名全职）/ 4–6 个月（2–3 人并行）**。Codex 给了路径但没给量。如果要立项 / 排期，我的数字更可用。

### 2.3 ratatui→Textual 架构替换的明确决策点

Codex 在阶段 0 提到"Textual 替代 ratatui 是否算复刻"作为待确认项，但没展开后果。我在 SUMMARY 第六节 Q1 里给了三个**具体方案**（保留 Textual / 换 prompt_toolkit / 放弃 Python TUI 只做 headless），让用户能直接做选择。

### 2.4 沙箱、子代理、HTTP 框架的实施路径选项

我把"如何实现"也展开了：
- 沙箱：sandbox-exec/landlock 子进程 vs Docker/bubblewrap vs pylibseccomp。
- 子代理：asyncio.Task vs multiprocessing vs subprocess + 子解释器。
- HTTP：FastAPI vs aiohttp vs Starlette。

Codex 列出了"应该做什么"，我列出了"可以选哪些做法"。决策时这是不同维度。

### 2.5 Registry alphabetical sorting 的根因（DeepSeek KV prefix cache）

我点出了这个排序不是为代码可读性，而是因为 DeepSeek issue #263 要求 prefix cache 稳定性——**乱序会导致 token 成本数倍上涨**。Codex 的报告里只说"Registry 虽然已排序，但缺少 capability filter 等"，**我和 Codex 在"是否已排序"这一点结论不同**：我的子代理审核认为没排序，Codex 说"已排序"。这是我们之间需要在动手前再核实一次的具体事实点（见下文 §3）。

### 2.6 协议事件枚举的具体数量

我的 phase A 给了"EventFrame 20 变体、ThreadRequest 10 变体、Envelope<T> 包装"的具体计数；Codex 只说"缺少 envelope/event frame/thread request/response/approval/MCP startup event"，**没给基数**。补齐时我的清单可以直接当 checklist 用。

### 2.7 子代理 spawn 深度限制 + tool 类型过滤

我在 phase C 里点出 Rust 子代理有 **6 种类型**（General / Explore / Plan / Review / Implementer / Verifier / Custom）+ **默认深度 max=3** + **mailbox + cancellation token + JSON state file + session boot id**。Codex 只说"内存模拟，没接 mailbox/agent loop"，没列出 sub-agent 类型矩阵。

### 2.8 8 个 ASKS 问题

我的 SUMMARY 用 AskUserQuestion 风格列了 8 个等用户回答的具体问题（TUI 框架 / 沙箱 / 子代理并发模型 / HTTP 框架 / 协议二进制兼容 / prompt 翻译 / 旧报告处置 / 资源凭据）。Codex 只在阶段 3 提了"是否引入 Playwright / finance 数据源 / subagent 多进程"3 个问题，**少 5 个**，且没集中。决策一次性对齐时我的更省时间。

---

## 3. 我和 Codex 的判断分歧（这些需要再核实再决定）

### 3.1 Registry 是否已经按字母序排

- **Codex**：已排序，缺 capability filter。
- **我（phase C 子代理）**：基本是 dict 顺序，缺字母序排序。

→ **建议在动手前 grep 一次 `src/deepseek_tui/tools/registry.py` 的 `to_api_tools()` 实现**，看是否真有 sorted() 调用。错了会在后续工作里发酵。

### 3.2 TUI 当前 widget 数量

- **Codex**：基础 TUI/Textual 壳已搭起。
- **我（phase E）**：14 个 Python widget 文件 vs Rust 48 个，**parity ~1%**。

差异在于"骨架是否搭起"≠"是否 1% parity"。两边描述的是不同维度。**我们其实不冲突**，但措辞会让用户误以为有矛盾。在 SUMMARY 中要明确说"骨架 OK，行为覆盖 1%"。

### 3.3 阶段 0 的范围

- **Codex 阶段 0**：修 venv + 修 ruff + 改虚假完成度文档 + 建 parity 清单。
- **我的 Stage 1**：直接进入协议/密钥/状态底座修复，没单独列环境校准阶段。

→ **Codex 是对的**。我的 SUMMARY 应该补"Stage 0：工程环境与文档校准"作为 Stage 1 的前置。下面我会在 SUMMARY.md 里追加这一段。

### 3.4 TUI 优先级

- **Codex**：TUI 整体 P1（slash/mode/approval UI/prompts/CLI exec/serve/auth 是 P0）。
- **我**：TUI 顶层编排、流式 transcript、approval gate UI 是 P0；命令面板、file mention 等 P1；onboarding/i18n/theme 等 P2。

→ **我和 Codex 在"哪些是 P0"这一点几乎一致**（都把 approval、mode、slash 列为 P0），但我把更多 widget 也列为 P0。考虑到用户是"百分百复刻"，我倾向坚持自己的更严标准：UI 行为也得复刻，不能省。

### 3.5 finance 工具的态度

- **Codex**："明确数据源或从默认 registry 移除并标为不支持"——给了 escape hatch。
- **我**：列为 P2，但既然用户要"百分百"就不能省。

→ **用户要"百分百"就不能用 escape hatch**。我坚持必须实现，Codex 这条是放水了。

### 3.6 关于 `web_run` 引入 Playwright

- **Codex**：把"是否允许引入 Playwright"作为决策项交给用户。
- **我**：默认 P0 必须实现，列为 Q1 之外的实施细节。

→ Codex 的态度更稳。我承认应该把这个交给用户决定。已在 SUMMARY 第六节，但措辞可以更明确。

---

## 4. Codex 报告的盲点（我比它额外发现的事）

### 4.1 ~30K LOC 的 top-level sub-managers 没系统枚举

Codex 提到了"compaction/cycle/session/task/automation/seam/memory/project managers 缺失"，但没逐个列出 **runtime_threads.rs (4,413 LOC)、runtime_api.rs (2,729 LOC)、compaction.rs (2,008 LOC)、cycle_manager.rs (1,071 LOC)、working_set.rs (1,198 LOC)、session_manager.rs (1,339 LOC)、seam_manager.rs (700 LOC)、command_safety.rs (~1,200 LOC)、network_policy.rs (~700 LOC)、workspace_trust.rs (~286 LOC)、error_taxonomy.rs (477)、eval.rs (742)、localization.rs (1,863)、settings.rs (597)、project_context.rs (472)、utils.rs (707)、palette.rs (434)、models.rs (515)、schema_migration.rs (371)、composer_history/composer_stash (479)、deepseek_theme.rs (176)、mcp_server.rs (625)、repl/runtime.rs (877)、snapshot/repo.rs (664)** 这些。**这些是 Phase E 报告 §5 的核心清单，Codex 没穷举。**

### 4.2 `MAX_FUZZ=50` 等具体常量

我的 phase C 子代理点了 `apply_patch.rs` 的 `MAX_FUZZ=50` 常量、`compaction.rs` 的 `token_threshold=50k / message_threshold=50` 阈值、子代理 `default max depth = 3` 等具体魔数。Codex 没给。补齐时这些常量必须复刻才算 parity。

### 4.3 协议层面的具体字段计数

我点出 "ThreadMetadata 有 21 个字段，Python 只保留基础几个"。Codex 也提到 ThreadMetadata，但**没给字段数**。同样，配置层我点出"50+ 缺失字段、10+ 缺失枚举、15+ 缺失函数"，Codex 偏定性。

### 4.4 V4-pro 25% 折扣 + cache_read_input_tokens 计费

我的 phase B 点出 Rust pricing.rs 含 V4-pro $0.55/M 输入（25% 折扣）+ `cache_read_input_tokens` 计费。Codex 只说"pricing/cache accounting 缺失"，没给折扣比例。

### 4.5 Rust 子代理"prior session boot id" 过滤机制

我点出了 Rust 子代理用 boot id 过滤 prior-session 的子代理记录，避免重启后误识别为 active。Codex 没提。

### 4.6 8 个具体的 ASKS

如前所述，我比 Codex 多了 5 个"用户必须回答"的关键决策问题。

---

## 5. 哪些地方 Codex 比我可信，应该采纳它的判断

按重要性排序：

1. **Stage 0 是必须的**：先修 .venv、ruff、git init、改 TASKS.md/COMPLETION_SUMMARY.md。我的 SUMMARY 该补这一段。
2. **97 passed 测试是假象**：补 parity 测试的优先级被我低估了。Codex 的"每补一个模块都能证明等价"思路应该贯穿整个补齐过程。
3. **finance/web_run/subagent 多进程是给用户的开放问题**，不是审核员的硬主张。我应该把它们也明确列为决策项。
4. **LSP 的 "diagnostics 注入下一次 user message"** 是具体可执行的描述，应该放到 phase D 的 P1 详述里。
5. **CLI auth 子命令面**（login/logout/status/set/get/clear/list/migrate）Codex 一一列出，我只说"auth 子组缺失"。Codex 的清单可以直接当 ticket。

---

## 6. 哪些地方我比 Codex 可信，应该采纳我的判断

按重要性排序：

1. **74 个工具完整 inventory 表**：Codex 没给完整表，我给了，可以直接当工单。
2. **49 个 slash 命令完整表**：同上。
3. **28 个 HTTP 路由完整表**：同上。
4. **48 个 TUI widget 文件清单 + 逐文件 LOC**：同上。
5. **17 个 prompt 文件清单**：同上。
6. **30+ top-level sub-manager 清单 + LOC**：同上。
7. **工作量数字**：90K LOC、45-66 周、9-14 月单人估算——立项必须有的数字。
8. **8 个集中的用户决策问题**：Codex 散落 3 个，我集中 8 个。
9. **architecture 替换的多方案对比**（ratatui→Textual / 沙箱实现 / 子代理并发 / HTTP 框架）：决策时必须看的材料。
10. **具体魔数 / 常量 / 字段计数**：parity 的关键证据。
11. **DeepSeek KV prefix cache 稳定性**（issue #263）的根因：Codex 提到要排序但没说原因。

---

## 7. 综合建议（合并两份报告的最终路径）

按"先 Codex 阶段 0、再用我的 inventory 按 Stage 1–7 推进"组织：

1. **Stage 0（1 周）— Codex 主张**：
   - `git init` + commit 当前 baseline。
   - 修 .venv 让 `make check` 在本机能跑。
   - 修 16 项 ruff 错误。
   - 把 TASKS.md / COMPLETION_SUMMARY.md / ARCHITECTURE_AUDIT.md 中"完成 / 95% / 生产就绪"的措辞改为真实状态（或直接归档到 docs/AUDIT/legacy/）。
   - 建 parity 测试基础设施：每个补齐的模块要有 Rust fixture parity test。
2. **Stage 1（2–3 周）— 我的清单**：协议 envelope/EventFrame、密钥优先级反转、时间戳类型、tool name codec、registry 字母序、provider capability matrix。
3. **Stage 2（4–6 周）— 我的清单**：engine turn_loop / capacity / compaction、execpolicy parser、command_safety、sandbox 平台后端。
4. **Stage 3（4–6 周）— 我的工具清单 74/74**。
5. **Stage 4（4–6 周）— 我的清单**：MCP HTTP/server、LSP post-edit 注入（Codex 主张）、Hooks 7 类事件 + 条件、App Server HTTP + 28 路由 + RuntimeThreadManager。
6. **Stage 5（6–8 周）— 我的清单**：CLI 22 子命令 + 49 slash 命令 + 17 prompt 模板 + skills 子系统。
7. **Stage 6（8–12 周）— 我的清单**：TUI 顶层编排 + 流式 transcript + approval/markdown/diff 渲染 + command palette + 30+ sub-manager。
8. **Stage 7（2–4 周）— Codex parity 测试与发布门禁**：E2E、failure mode、真实 DeepSeek tool call smoke、CI。

合计 31–46 周（一名全职）。和我之前估的 45–66 周相比变短了，因为 Codex 的 Stage 0 把"返工成本"前置消除了，后期更顺。

---

## 8. 用户最终该怎么决策

把两份报告合并后，**用户只需要回答 SUMMARY.md §6 那 8 个问题**（TUI 框架 / 沙箱实现 / 子代理并发 / HTTP 框架 / 协议二进制兼容 / prompt 翻译 / 旧报告处置 / 资源凭据），并加上 Codex 提的 **3 个补充问题**：

- Q9. CLI 命令名是 `deepseek` 还是 `deepseek-tui`？（Codex 阶段 0 提的）
- Q10. 是否允许引入 Playwright + 浏览器下载（web_run 实现需要）？（Codex 阶段 3 提的）
- Q11. `finance` 数据源指定（如必须复刻）？（Codex 阶段 3 提的）

回答完这 11 个问题，就可以从 Stage 0 开始动手。

---

## 9. 一句话总结差异

- **Codex 偏向"工程师视角的环境与流程修复"**：跑命令、改文档措辞、建 parity 测试、阶段 0 校准。
- **我偏向"审核员视角的清单与数量化缺口"**：全 inventory、字段级对比、工作量估算、决策方案对比。
- **二者互补，不冲突**。最终交付应是"Codex 的 Stage 0 + 我的 Stage 1–6 inventory + Codex 的 Stage 7 parity 测试"。
