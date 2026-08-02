# 上下文工程优化方案 — CONTEXT_ENGINEERING_OPTIMIZATION_PLAN

> 来源：2026-08-02 上下文工程全链路审核（`Engine._handle_send_message_inner` → provider wire 的完整消息装配），对照 `system_prompts_leaks-main` 中 Claude Code 2.1.211（含 binary 提取的 `injected-reminders/`、`compact.md`）、Codex gpt-5.6、OpenCode、Cursor。
> 状态：**待拍板，未动任何代码**。
> 方法：静态代码走查，未做运行时采样；所有行号为审核当时。

## ⚠️ 执行前需要先拍板的三件事

1. **与"行为复刻"的关系**。本项目是 Rust 版 DeepSeek-TUI 的行为复刻（见 `docs/HANDOVER.md`）。Phase 0/1 属健壮性与接线修复，不改变模型可见语义，可直接做。**Phase 2/3 会改变注入模型的上下文内容**（新增用户请求账本、新增文件变更提醒），与复刻语义存在张力，需与工具方案 Phase 1 同样的方式拍板：接受偏离并在 parity 中标注，或只做 Phase 0/1/4。

2. **既有契约测试会被改写**。`tests/engine/test_context_query_survival.py` 的 `test_prepend_bridge_replays_last_query_when_outside_window` 与 `test_cycle_seed_has_no_fake_assistant_ack` **把"只回放最后一条用户请求"固化成了契约**。Phase 2 不是新增测试，而是修改这两条断言的语义。需确认这是有意变更而非回归。

3. **Phase 3 的误报容忍度**。文件变更提醒会被格式化工具、`git checkout`、编辑器保存触发。需决定：只提醒不拦截（建议），还是硬拦截强制重读。

---

## 一、核心诊断：不是欠工程，是欠集成

本项目的上下文机器**比 Claude Code 更多**：对方只有一层压缩，这里有 L0 修剪、soft seam、rewrite、cycle 四层，外加 working set、pin 策略、spillover、mutation ledger、turn checkpoint。

问题不在功能数量，而在两点：

- **各层产出没接到模型上**。cycle 归档 JSONL 只进 `logger.info`；mutation ledger / shell 快照对比 / git reconcile 只进 UI 与 SSE；pre-write 快照只服务 undo；`to_api_tools_with_cache` 零调用；`CapacityController` 默认关闭却每轮空转。
- **层与层之间不共享同一套来源契约**。`MessageOrigin` 枚举定义完整、`is_synthetic_user_message` 也已存在，但摘要器不消费它，退回到 `msg.role == "user"` 判断。

因此优化方向是**接线与收敛，不是继续加特性**。这个判断决定了下面的全部排序。

## 二、三条可泛化原则

下方 22 项发现不必逐个记忆，它们是三条原则各自被违反的实例。

### 原则一 · 来源信息必须端到端保真

凡是缩减、改写、重新格式化消息的组件，都必须消费 `MessageOrigin`，不得依据 role 或文本前缀推断。

**可执行判据**：代码中每一处 `msg.role == "user"` 均为缺陷候选，需逐个复核。`is_synthetic_user_message` 内部仍以 `text.startswith("[System]")`、`"**Important**: The user asked"` 等字符串嗅探兜底，这本身即 provenance 未打通的证据。

### 原则二 · 压缩只能丢弃"模型可用一次工具调用重新取回"的内容

代码内容可丢（留路径）、工具输出可丢（可重跑）、git 状态可丢（可重查）。**用户表达过的意图与约束在任何地方都查不回来**，是唯一不可重建类，必须逐字保留。

Claude Code `compact.md` 第 6 节要求 `List ALL user messages that are not tool results`；Codex gpt-5.6 向模型承诺 `you will see all prior user requests`。两家独立收敛到同一点。

**推论**：注入归档路径不是锦上添花，而是激进压缩的合法性前提——它把"丢失"变为"可重建"。Claude Code 的续写消息即写明 `read the full transcript at: {transcript_path}`。

### 原则三 · 发不发看是否作废假设，发在哪看是否 session 内稳定

两个正交维度。混淆会做出既费 token 又打断前缀缓存的决定。

- **发不发**：提醒不可替代的用途是作废模型已持有的信念。准入测试——"不发这条，模型会基于什么错误假设行动？"答不上来就不该做成提醒。Claude Code 七条注入提醒无一例外是此形状（容器重启后台任务已停、模型已切换、输出通道已变、退出协议已变、召回记忆可能过期）。
- **发在哪**：session 内稳定的进 system 吃前缀缓存，易变的进提醒以保护前缀。

### 用原则三重审现有 13 条注入

| 注入物 | 作废了什么假设 | 模型能否自行重建 | 结论 |
|---|---|---|---|
| git 快照 | 无，纯信息投递 | 可，自行 `git status` | **删除**（F14） |
| handoff | 「这是全新会话」 | 不可，模型不知该文件存在 | 保留 + 加时效声明（F15） |
| hook additionalContext | 视 hook 而定 | 不可 | 保留 |
| plan 探索 nudge | 「我可以直接出计划」 | 不可 | 保留 |
| LSP 诊断 | 「我刚才那次编辑是干净的」 | 可但昂贵 | 保留 + 默认开启（F12） |
| 子 agent 完成 | 「子任务还在跑」 | 不可 | 保留 |
| 长会话锚点 | 「我还清楚记得系统指令」 | 不可，注意力衰减无法自知 | 保留 + 必须贴尾 |
| Stop hook 阻断 | 「我可以收尾了」 | 不可 | 保留 |
| soft resume | 「我没有被中断过」 | 不可 | 保留 |
| checklist 状态（缺） | 「我记得待办清单现在的样子」 | 可，调 `checklist` 读取 | 新增，低频（F13） |
| 文件被外部修改（缺） | 「我读到的内容还是最新的」 | **不可，无声失败** | 新增（F11） |
| soft seam | —— 非提醒，是历史替代物 | —— | 换信封（F16） |
| cycle seed | —— 同上 | —— | 换信封（F16） |

**最后两行揭示尾部混乱的根因**：soft seam 与 cycle seed 套着 `<system-reminder>` 信封，但它们是**历史替代物**，必须待在时间顺序的正确位置；真正的提醒是**实时告警**，必须贴尾。两类语义共用一个信封，位置策略无从谈起，只能退化为"谁先 append 谁靠前"。缺的是信封分家，不是一个排序函数。

---

## 三、审核发现全表（可追溯）

| # | 发现 | 位置 | 违反原则 | 阶段 |
|---|---|---|---|---|
| F1 | 压缩只回放最后一条用户请求，多轮累积约束首次压缩即丢失 | `capacity.py:798,842`、`cycle.py:295` | 二 | P2 |
| F2 | 摘要器角色坍缩：所有注入物以 `User:` 身份进入摘要输入 | `capacity.py:886` | 一 | **P1 ✅ 已修** |
| F3 | 摘要器输入逐条截断至 2000 字符（小窗口 800） | `capacity.py:890` | 二 | P2 |
| F4 | 摘要器输入超 120k 字符时中段整体抹除，摘要器看不见中间说过什么 | `capacity.py:900-906` | 二 | P2 |
| F5 | `compact.md` 未要求逐字保留安全/范围约束，无防伪造归因，next step 无逐字引用 | `prompts/compact.md` | 二 | P2 |
| F6 | 迭代再压缩：上一版摘要作为输入再改写，转述的转述无界漂移 | `capacity.py:917-923` | 二 | P2（由 F1 解决） |
| F7 | pin 依赖"文本含 working-set 路径字符串"，约束存亡取决于字符串巧合 | `context.py:1092` | 二 | P2（由 F1 缓解） |
| F8 | cycle 归档 JSONL 路径只进 `logger.info`，从未注入上下文 | `cycle.py:251`、`maintenance.py:433` | 二 | P1 |
| F9 | skill focus 重写 system prompt 的 `## Skills` 段，一次 `/skill` = 两次完整前缀失效 | `core.py:2047` | 三（位置） | P1 |
| F10 | `to_api_tools_with_cache` 零调用；且 Anthropic 侧 `_map_tool` 也不输出该字段 | `registry.py:504`、`anthropic.py:140` | —— | P1 |
| F11 | 无文件读新鲜度追踪。`edit_file` 为精确字符串替换，外部改动后可能**匹配成功但基于过时认知**，无任何错误浮现 | `tools/file.py`、`ToolContext` | 三 | P3 |
| F12 | LSP 诊断默认关闭，唯一的状态失效通道实际一条都不发 | `config/models.py:346` | 三 | P3 |
| F13 | 有 `checklist` 工具但状态从不回灌，写入只返回一个计数 | `tools/todo.py:337` | 三 | **P1 ✅ 已修**（原排 P3，提前） |
| F14 | ~~git 快照该删~~ **撤回**：快照正文已自带 "snapshot in time and will not update — use the git tool" 免责声明，且明确指路替代动作，符合 Claude Code 做法。保留 | `prompts.py:148-153` | —— | 不改 |
| F15 ✅ | ~~快照类注入普遍缺时效声明~~ **降级**：git 快照已有声明（见 F14）。仅剩 handoff 内联正文无声明 | `prompts.py:581` | 三 | **P4 ✅ 已修**（并顺带补上中和） |
| F16 ✅ | 历史替代物（seam / cycle seed）与实时告警共用 `<system-reminder>` 信封 | `context_pressure.py:106` | 三（位置） | **P4 ✅ 已修** |
| F17 ◐ | 尾部提醒无优先级与预算，顺序是 append 调用顺序的副产物 | 散落 6 个文件 | 三 | **P4 部分**：优先级已声明并由测试守住；总预算未做，理由见 Phase 4 遗留 |
| F18 ✅ | 13 条提醒以内联字符串散落在 `core.py` / `maintenance.py` / `lifecycle.py` / `cycle.py` / `manager.py`，无注册表 | 同上 | 一 + 三 | **P4 ✅ 已修**（`engine/reminders.py`） |
| F19 ✅ | `is_synthetic_user_message` 以字符串前缀嗅探兜底 | `context_pressure.py:171-199` | 一 | **P4 ✅ 已修**（嗅探下沉为反序列化迁移） |
| F20 ✅ | `CapacityController` 默认 `enabled=False` 却每轮调用，实为空转 | `capacity.py:83` | —— | **P4 ✅ 已修**（提前退出，功能保留） |
| F21 ✅ | `RATIO_AUTO_FLOOR` 注释声称 ingress truncation，无对应实现 | `context_pressure.py:24` | —— | ~~P4~~ 已由 P3.5 顺带解决 |
| F22 ✅ | 不读 `.cursor/rules`，而 skills 发现路径已包含 `.cursor/skills`，两者未对齐 | `engine/context.py:597` | 生态 | **P4 ✅ 已修**（仅 alwaysApply） |
| F23 | 工具结果入场截断只看 model + tool name，**不看当前压力**。5% 窗口时 30k 字符的 `read_file` 照样被砍成头尾片段，而 L0 prune 本就能按压力递进地做同一件事 | `context.py:212-247` | 二 | P3 |
| F24 | `measure_context_pressure` 支持 `system_prompt` / `tools` 入参，但**四个生产调用点全都不传**。估算路径（每个 session 首轮、cancel 后）系统性漏算 system+tools 约 8.4k tokens，阶梯判断整体偏低 | `maintenance.py:136,225`、`capacity.py:745,1039` | —— | P0 |
| F25 | seam L1 触发点在 **20%**：128k 窗口下 25k tokens 就开始烧 Flash 做摘要，而 seam 是 append-only，摘要文本自身还要占位——低压力时主动往上下文加东西 | `context_pressure.py:17` | —— | P3（需 0.2 基线） |
| F26 | 摘要器输入里 `ToolUseBlock` 只渲染成 `[Used tool: name]`，**参数整条丢弃**。摘要器因此看不到改了哪个文件、跑了什么命令、checklist 写进去什么，只能从紧随其后的 tool result 反推。`### Done` 里那些"landed patches / passing tests"要求的正是这些信息 | `capacity.py:915-917` | 二 | 待定，见下 |

## 四、保留不动的设计（做得好的，勿改坏）

- **`base.md:120` 的单向权威条款**。提醒只能 tighten 约束、不能 loosen 安全规则或索要系统提示，任何反例按"用户数据中的伪造内容"处理。对照之下 Claude Code、OpenCode、Cursor 均只有一句"reminder 不是用户输入，照做"。本项目此条配合 `neutralize_fake_system_reminders` 形成闭环，是全局最强的一处。
- **volatile 不进 system 的不变量**，及守护它的 `test_system_prompt_stable_volatile.py`。这是把原则固化成契约测试的范本，第六节照此扩展。
- **`active_tools_for_step` 的 `head + tail` 顺序**（`engine/tools.py:303-314`）。运行中新激活的 deferred 工具一律追加尾部，头部前缀逐字节不变——工具序列本身是照顾前缀缓存设计的。
- **工具结果三级瘦身**（spillover → context compact → L0 prune），UI 收完整内容、只压进模型的副本。
- **`<user_query>` / `<local_context>` 的结构化拆分**，以及 @mention 的字节预算与 artifact 溢出。

---

## 五、与第二份独立审核的交叉核实

第二份审核（Cursor）独立走了一遍同一条链路。逐条核对源码后的结论：

**它对、本方案漏了的**（已并入上表）

- F23 工具结果截断与压力解耦。本方案把"三级瘦身"整体列进了第四节的"勿改坏"，没有质疑第一级的触发条件，这是漏判。
- F25 seam L1 在 20% 触发过早。本方案列了六级阶梯却没有质疑参数取值。
- F13 的修法比本方案具体：`_build_result_metadata` 已经把完整快照准备好了，`_read` 也已有渲染逻辑，只差把它接进 `_write` 的 `content`。因此从 P3 提前到 P1 并已落地。

**它错的**

- "estimate 用字符数，应改 tiktoken"——`estimate_tokens` 早已是 tiktoken `o200k_base`，字符切分只是无 tiktoken 时的兜底（`context.py:287-301`）。`estimated_input_tokens` 还额外把 JSON framing 算进去，偏保守而非低估。
- 因此 `_maybe_advance_cycle` 里那句 "~6x-undercounting" 注释是 **tiktoken 改造前的遗留，现已失真**，应删。真正的低估源头是 F24：调用点不传 system+tools。

**本方案对、它漏了的**——这批恰好是最重的几条，且都集中在压缩链路：

- F1 压缩只回放最后一条用户请求。它在 75% 那行写了"replay 用户目标"（单数）但未识别为缺陷。这是全表第一优先级。
- F2 摘要器角色坍缩、F5 `compact.md` 缺逐字保留契约、F8 归档路径从不注入。
- F9 skill focus 重写 system prompt。它的表述"system prompt 每轮重建但内容基本不变"在 `/skill` 场景下不成立。
- F16 信封错配。它把 soft seam 归入"压力驱动的提醒"，而 seam 是历史替代物不是提醒——这正是 F16 描述的混淆本身。

**本方案自纠**——F14/F15 见上表：git 快照正文早已带时效声明并指路 `git` 工具，"缺时效声明"的判断不成立，撤回。

---

## Phase 0 · 先让问题可观测（无行为变更）

| # | 改动 | 位置 | 覆盖发现 | 风险 |
|---|---|---|---|---|
| 0.1 ✅ | 端到端约束存活测试：12 轮会话、第 3 轮一条**不含任何文件路径**的纯文字约束（绕开 F7 的字符串巧合），假摘要器**故意丢掉该约束**（契约是"不管摘要器输出什么都要活下来"），覆盖 rewrite、cycle、以及两者串联 | `tests/contract/test_user_constraint_survival.py` | F1 F7 | 无。标 `xfail(strict=True)`：Phase 2 落地后 xfail 自身会转红，强制摘掉标记 |
| 0.2 ✅ | 每轮 `prefix_cache round=N hit=… miss=… ratio=…` 日志，挂在 `last_real_input_tokens` 刷新处。两个计数都为 0 时不打——按 `base.md` 的规定那是"未知"而非 miss | `core.py` 轮次 usage 处 | F9 | 无。不新增采集 |
| 0.3 ✅ | **五个**（不是四个）压力计算点补传 `system_prompt` 与 `tools`；`_maybe_advance_cycle` 原本绕过 `measure_context_pressure` 自己算，一并收拢，失真的 "~6x-undercounting" 注释删除 | `maintenance.py` ×3 + `_maybe_advance_cycle`、`capacity.py` ×2、`core.py` 四个调用点 | F24 | 低。阶梯会**更早**触发（此前系统性偏低）。测试见 `tests/contract/test_pressure_counts_static_prefix.py`，含一条**接线守卫**：F24 的本质是参数存在却没人传，只测函数签名挡不住复发 |

**不要在没有 0.2 基线的情况下改任何缓存相关项。** F9 的收益必须可量化。
**也不要在 0.3 之前调任何阈值**（F25）——当前压力信号本身是偏低的，基于它调参会调错方向。

## Phase 1 · provenance 保真与接线（四项互不依赖，可并行）

| # | 改动 | 位置 | 覆盖发现 | 风险 |
|---|---|---|---|---|
| 1.0 ✅ | checklist 写入回显完整列表：抽出 `_render_items`，`_write` 与 `_read` 共用；保留 `N items written` 前缀（Workbench `extract-todos-from-blocks.ts` 靠它识别写入） | `tools/todo.py` | F13 | 低。已落地，`tests/contract/test_checklist_write_echoes_state.py` |
| 1.1 ✅ | 摘要器角色分流：`user` 角色再过一道 `is_synthetic_user_message`，注入物标 `Harness:`；摘要器 system prompt 说明该标签含义 | `capacity.py:886` | F2 | 低。已落地，`tests/contract/test_summary_role_provenance.py` |
| 1.2 ✅ | skill focus 不再改写 system：去掉 `only=focus_skill` 窄化，仅保留 `_focus_tool_whitelist`。核实过 `/skill` 前缀**不会**被剥离（只有 MCP 的 `@name` 会走 `_strip_focus_prefix`），模型在用户消息里仍看得到技能名，信号不丢。插件挂载的窄化保留——那是 session 级状态，前缀跨轮稳定 | `core.py` | F9 | 低。已落地，守卫在 `test_system_prompt_stable_volatile.py` |
| 1.3 ✅ | 归档路径注入 seed。**比计划复杂**：归档在 `~/.deepseek/sessions/<id>/cycles/`，既有读放行只覆盖 `~/.deepseek/tool_outputs/`，直接注入等于给模型一个必然报错的路径。加了 `ToolContext.cycle_archive_root` 专用字段（不复用 `extra_read_roots`——插件挂载会整体重赋值把它冲掉），仿照 spillover 的门控：只读、只放行本 session 那一个目录 | `cycle.py`、`maintenance.py`、`tools/registry.py` | F8 | **中（读沙箱边界）**。测试见 `tests/contract/test_cycle_archive_is_reachable.py`，含"不放宽到同级 session"与"写调用不受益"两条 |
| 1.4 ✅ | `to_api_tools_with_cache` **删除**。三重确认为死代码：src 零调用、tests 零引用、且 Anthropic `_map_tool` 重建 dict 时只取 name/description/input_schema，`cache_control` 就算挂上也会被丢掉——接通不会生效，只有 docstring 在误导人 | `registry.py` | F10 | 无 |

**验证**：1.2 用 Phase 0.2 的基线对比 `/skill` 调用前后两轮的 cache hit ratio（需真实会话）；其余已跑全量确认零新增失败。

## Phase 2 · 用户请求账本（核心，改变模型可见上下文）

| # | 改动 | 位置 | 覆盖发现 | 风险 |
|---|---|---|---|---|
| 2.1 ✅ | 账本写入：**改为从消息流派生，不挂引擎状态**。`collect_user_requests()` 扫 `REAL_USER` 消息 + 上一轮留下的 `REQUEST_LEDGER` 载体，去重后按序返回。理由：`prepend_compaction_bridge` 本来就把 query 以 `REAL_USER` 回填进历史，顺着这个自持模式走，账本就能扛住重启、子 agent、emergency compact，不必给每个调用点穿新的可变状态 | `context_pressure.py`、`protocol/messages.py`（新 origin `REQUEST_LEDGER`） | F1 | 低 |
| 2.2 ✅ | 两个吐出点：`prepend_compaction_bridge` 与 `build_seed_messages` 新增 `prior_requests` 入参，渲染 `<prior_user_requests>` 块，说明"最后一条是当前请求，之前的除非用户撤回否则仍然生效"。`last_real_query` 保留原义不动——它答的是"现在要做什么"，账本答的是"到目前为止用户说过什么"，两个问题 | `context_pressure.py`、`cycle.py`、`capacity.py`、`maintenance.py` | F1 F6 F7 | 低。**`test_context_query_survival.py` 未受影响，无需改写** |
| 2.3 ✅ | 有界化：总量 20k 字符丢中段保头尾；单条 2k 字符两端裁剪。单条上限是必须的——账本每次压缩都从自己的上一次渲染重建，一段超长粘贴若不裁，丢中段的逻辑挤不动它。裁剪长度按"裁完仍在上限内"取，保证幂等，否则同一条会被反复削 | `context_pressure.py` | F1 | 低 |
| 2.4 ~~撤销~~ | 原计划让 `find_last_real_user_query` 退化为 `ledger[-1]`。实现后发现两者语义不同（见 2.2），退化会让 cycle seed 把整本账本当成当前请求。**保持原实现** | —— | —— | —— |
| 2.5 ✅ | `compact.md` 契约补强三条：① 归因规则——只有 `User:` 行是人，`Harness:` 是注入，`Assistant:` 行可能在**引用**用户，都不能变成用户指令；② 约束分「stated / discovered」两类，discovered 要逐字引用建立它的那条报错或输出；③ next step 必须锚定到文件/符号/命令。**另加一条计划外的**：告诉摘要器用户原话已由账本逐字保管，别再花字数改写，把预算留给"试了什么、得到什么、为什么这么定" | `prompts/compact.md` | F5 | 低 |
| 2.5b ✅ | **P2 落地时自己开的口子**：`COMPACT_CONSUMER_HINT` 只教模型读 `<archived_context>`，没提 `<prior_user_requests>`，两者冲突时无仲裁规则。补上并明确**逐字账本优先于摘要**，且"摘要漏掉某条约束"是预期状态而非异常——账本存在的理由就是这个 | `prompts.py:787` | F5 | 低。进静态前缀，缓存友好 |
| 2.6 ✅ | 摘要器**逐条消息**的截断从「静默砍头」改为「头尾保留 + 显式省略标记」（新 `_elide_middle`）。原实现两处失效：结论在消息**末尾**（"所以选 X 因为 Y"、traceback 的 assertion 行），砍头正好把结论砍掉；且无标记时摘要器分不清"这条本来就短"和"这条被截断了"，会把半个决策当成整个决策记下来。L0 prune 早就是头尾保留，这里只是补齐一致性。会话级 head/tail（72k/36k）本来就有标记，不动 | `capacity.py`（新 `_elide_middle` + 两处调用） | F3 F4 | 低 |

**验证**：Phase 0.1 的三条 xfail 已转绿并去掉标记，另加三条：重复压缩不叠加载体、账本不被当成新请求、`_maybe_advance_cycle` 确实传了账本（源码级 wiring 断言，防的是"参数加了但没人填"这类改动——签名对了测试全绿而线上照旧失忆）。新增 `test_user_request_ledger.py` 守 render/parse 往返：多行、内嵌编号列表、超长裁剪、反复渲染幂等。新增 `test_summary_input_fidelity.py` 守 2.5/2.6：长 assistant 消息末尾的 DECISION 行与 traceback 末尾的 assertion 行必须抵达摘要器、截断必须可见、契约三条与消费端仲裁规则必须在位，并含一条"契约确实被发出去了"的断言。全量 1310 passed，失败集合与基线逐条一致（沙箱 git + 既有 `context_window_override` 跨测试污染）。剩余：实测 50 轮会话的账本 token 占比应低于窗口 3%。

## Phase 3 · 读新鲜度与状态回灌（新增模型可见提醒）

| # | 改动 | 位置 | 覆盖发现 | 风险 |
|---|---|---|---|---|
| 3.1 ✅ | read registry：`ToolContext.file_reads: dict[Path, tuple[int, int]]`，记 `(st_mtime_ns, st_size)`。`read_file` 成功后记，`write_file` / `edit_file` 成功后也记——否则 agent 连写两次就会被自己绊倒。用 `st_mtime_ns` 而非 `st_mtime`：同大小改动只有纳秒级 mtime 能分辨。**`Engine.create` 的 `dataclasses.replace` 必须显式传 `file_reads={}`**，与 `metadata` 同理，否则同一 runtime 下的多个 engine 共用一个 registry，A 的写会把 B 的过期读标成新鲜——正好在两个 agent 同改一个文件时把守卫关掉 | `tools/registry.py`、`tools/file.py`、`core.py:1122` | F11 | 低 |
| 3.2 ✅ | **改为写入前硬拦，不走排队提醒通道**。原计划复用 LSP 的"排队 → 下轮 flush"，但那条通道是**延迟一轮**送达的：等提醒到达时 `write_file` 早已覆盖完毕，提醒只剩事后追悔，防不住任何东西。改为 `write_file` 执行前比对，不一致直接 `ToolError`，报错文本给出唯一解法（重新 `read_file`），一次工具调用即可清除。`edit_file` **不拦**——它只替换匹配到的文本，爆炸半径远小于全量覆盖；改为在 no-match 时若检测到过期就换成过期报错，否则"Search string not found" 会把模型引去找根本不存在的 typo | `tools/file.py` | F11 | 中。误报源：格式化工具、`touch`、内容相同的重新生成。误报方向安全（提示重读），且重读即解 |
| 3.3 ✅ | LSP 诊断默认开启评估 → **结论：评估前不能开，因为功能本身是坏的**。查出三处缺陷并已修复，**默认值仍保持 `False`，等真机验证后再由人拍板**。① `did_open` 用全局 turn 计数当判据（`if seq == 1`），于是只有第 1 轮编辑过的文件被 open，之后所有文件都是对未 open 文档发 `didChange`——服务端直接丢弃，**整个功能对绝大多数文件静默失效**；改为按文档跟踪 open 状态与版本号（同一轮内两次编辑也不会撞版本）。② 有 server 时每次编辑**无条件 `sleep` 5 秒**，40 次编辑白等 200 秒；改为在 `publishDiagnostics` 上挂 `asyncio.Event`，服务端一发布就返回，干净文件也会收到空列表，超时退化成病态情况的兜底而非常态成本。③ 生成失败不缓存：`_warned_missing` 只写不读且从不打日志，没装 language server 的机器**每次编辑都重新 fork 一个注定失败的子进程**且全程静默；改为缓存不可用语言并 warn 一次，附上安装或配 `[lsp.servers]` 的指引。此前该模块**零测试覆盖**，这也是三处缺陷能一起存活的原因 | `integrations/lsp.py`、`lifecycle.py:130` | F12 | 中 |
| 3.4 | ~~checklist 状态回灌~~ 已由 1.0 覆盖。剩余可选项：长会话锚点那句抽象叮嘱改为附带当前待办项 | `maintenance.py:205` | F13 | 低。1.0 之后收益已大幅下降 |
| 3.5 ✅ | 工具结果入场截断接入压力。`compact_tool_result_for_context` 新增关键字入参 `pressure_ratio`（默认 `None`），经 `_pressure_scale` 换成三档倍率乘到 hard / soft / snippet 三个上限上：低于 `RATIO_AUTO_FLOOR` 放宽 3×、达到 `RATIO_L0_PRUNE` 收紧 0.5×、中间维持原值。**档位边界直接复用阶梯自己的常量**，不另立一套数字，3.6 调参时两者同步移动（契约测试断言函数体内不得出现与 `pressure_ratio` 比较的字面量）。**压力信号只取真值**：新增 `_ingress_pressure_ratio` 读 `self.last_real_input_tokens / window`，provider 尚未回报时返回 `None` 退化成原行为——不接估算路径，因为它已知偏低，恰好会在最不该放宽的时刻把上限调大。串行与并行两个工具循环都接线，契约测试用源码检查守住（只接一个的话并行批次会继续按旧上限截断） | `context.py`、`tooling.py` 两个调用点 | F23 | 中。低压力时上下文变大——0.5× 那一档正是它的对冲：3.6 复核阈值时须一并看这条对 seam 触发频率的影响 |
| 3.6 | seam L1 阈值复核：`RATIO_SEAM_L1` 从 0.20 上调或直接取消 L1 | `context_pressure.py:17` | F25 | 中。**必须先有 0.2 与 0.3**，否则是在偏低的信号上调参 |
| 3.7 ✅ | 摘要器输入补 tool_call 参数（F26）。**最终没用 per-tool 白名单**——22 个内置工具要写 22 条、每加一个工具就要同步一次，而 MCP 工具在运行时注册，白名单根本覆盖不到。改用**尺寸判别**：短值（path / command / pattern / url）逐字渲染，长值（content / old_string / prompt）塌缩成 `<N chars>`。识别性参数天然短、载荷参数天然长，一条规则覆盖全部工具且零维护。`checklist` 不需要特例，P1.0 已让它把完整清单回显进 tool result | `capacity.py`（新 `_render_tool_args`） | F26 | 低 |

**验证**：`tests/contract/test_stale_write_guard.py` 15 条。正例：读 → 外部改 → 写被拒且磁盘内容未变、重读后放行、报错文本含 `read_file`。反例（必须不拦）：新文件、本 session 从未读过的既有文件、agent 连续写、读完立刻写、agent 自己 edit 后再写。`edit_file` 非对称性两条：过期但仍匹配放行、过期且未匹配换成过期报错。另含 registry 单测：删除文件出栈、同大小改动仍能检出、并发读不丢条目，以及一条 `dataclasses.replace` 别名守卫（直接断言不加 `file_reads={}` 时两个 context 共享同一 dict）。

3.5 的验证是 `tests/contract/test_ingress_truncation_pressure.py` 13 条：三档倍率各一条、未知压力等同旧行为一条、阈值必须具名一条；端到端四条（空上下文里 17k 字符 `read_file` 逐字存活、同一份在 0.60 被压缩、不传 `pressure_ratio` 与传 `None` 结果逐字相同、0.80 的片段短于 0.30）；边界两条（短结果任何压力下不动、50 万字符在 0.01 仍被压缩——放宽有天花板，"单条结果太大"那份职责不受压力影响）；接线两条（两个工具循环都传参、无真值时返回 `None`）。3.6 仍需 0.2 基线对比调整前后的 Flash 调用次数与实际 token 曲线，且此时基线已包含 3.5 带来的低压力增量。

## Phase 4 · 治理：把提醒变成有契约的通道

| # | 改动 | 位置 | 覆盖发现 | 风险 |
|---|---|---|---|---|
| 4.1 ✅ | 注册表落地，但**没建 `prompts/reminders/` 目录**。原计划照搬 `prompts/modes/` 的组织方式，实测不合身：modes 是整篇多段文档，而 13 条注入里过半是动态的（git status、LSP 诊断、子 agent JSON），静态的最短只有 107 字符——各拆一个 `.md` 只是换个地方存字符串，F17 要的排序和预算一条都不解决。改为新建 `engine/reminders.py`，用 `ReminderSpec` 同时声明信封、位置（`Placement.HEAD/TAIL/IN_HISTORY`）、`MessageOrigin` 与尺寸上限，`reminder_message()` 一次性把信封和 provenance 一起打上——**wrap 与 tag 分两步调用正是四个站点只 wrap 不 tag 的成因**。文本仍归 `prompts.py`（唯一内联的 plan nudge 一并迁过去），职责是"说什么"；`reminders.py` 管"怎么送"。11 个注入站点全部改接注册表 | 新增 `engine/reminders.py`；`core.py` ×5、`maintenance.py` ×2、`lifecycle.py`、`cycle.py`、`manager.py`、`subagent/loop.py` ×4 | F17 F18 | 中。已落地，全量套件无新增失败 |
| 4.2 ✅ | 信封分家。soft seam 去掉外层 `<system-reminder>`——它本就自带 `<archived_context level=... range=...>`，再包一层只会把模型要读的属性埋掉；cycle seed 换成 `<cycle_carryover>`。base.md 新增一条说明两者"是过去、不是指令"。**推翻了一条既有断言**：`test_cycle_seed_has_no_fake_assistant_ack` 原本断言 seed 含 `<system-reminder>`，已改写并在测试里写明推翻理由 | `reminders.py`、`prompts/base.md:121` | F16 | 中。改变模型可见标签 |
| 4.3 | ~~删除 git 快照提醒~~ **撤销**，见 F14。快照已自带时效声明并指路 `git` 工具 | —— | F14 | —— |
| 4.4 ✅ | handoff 正文加时效声明（"是上个 session 留下的描述，未与当前状态核对，凡涉及文件/分支/完成度的说法都是待验证线索"）。**另修一处不在 F15 范围内的问题**：handoff 正文是 workspace 文件内容，克隆来的仓库可以在 `.deepseek/handoff.md` 里塞伪造的 `<system-reminder>`，而 git 快照早已做了中和、这里没有。同一函数、同一威胁、一行修复，一并补上 | `prompts.py:581-612` | F15 | 无 |
| 4.5 ✅ | **不是删掉嗅探，是把它搬到边界**。直接删会炸：探索查出四类没设 origin 的合成消息（`subagent/loop.py` 三处 nudge、`threads/items.py:90` 重建 turn item、旧持久化 session 无 origin 字段、cycle 归档 JSONL 压根不写 origin），删掉嗅探后它们全部变成"真实用户消息"。改法是①把四类构造点全部补上 origin（顺带把 `loop.py` 那处手拼 `<system-reminder>` 字符串改走信封函数、`cycle.py` 归档改用 `model_dump` 以保住 origin）；②新增 `messages_from_dicts()` 作为**唯一**反序列化入口，嗅探逻辑搬进 `infer_legacy_origin()` 在此一次性执行；③`is_synthetic_user_message` 只剩 origin 判断 + 空文本判断。六个 loader 全部改道，契约测试用全仓库扫描断言 `Message.model_validate` 只允许出现在该 loader 里。**顺带修好一条死分支**：旧规则要求 `ARCHIVED_CONTEXT_OPEN in text and 'level="' in text`，但常量是裸标签 `<archived_context>` 而真实 seam 一定带属性，两个条件永不同时成立 | `context_pressure.py`、`protocol` 无改动、六个 loader、四处构造点 | F19 | 中。已落地 |
| 4.6 ✅ | `CapacityController` **保留不删，改为提前退出**。原计划是"开启或删除"，但删要动 250 行、且 env var `DEEPSEEK_CAPACITY_ENABLED` 是条真实开关。实际的浪费只在一处：三个 checkpoint 都先跑 `build_observation()`（遍历全部消息 + 估 token）**再**去问 `enabled`，而 `observe_*` 在关闭时必然返回 `None`。把 `enabled` 判断提到 `build_observation` 之前即可，功能完整保留，每轮空转消失 | `capacity.py:391,425,451` | F20 | 低 |
| 4.7 ✅ | `.cursor/rules/*.mdc` 支持，**只读 `alwaysApply: true`**。glob 作用域的规则要按当前涉及哪些文件改写 system prompt，而整个 prompt 就是按 most-static-first 排的、图的就是前缀逐字节稳定可缓存——一条会动前缀的规则，代价大于它携带的信息。跳过的条数打一条 info 日志。合并层从"global + project"两层硬枚举改为按层列表拼接（单层仍是裸文本、不加头注释，保证既有形状不变），且**光有 cursor rules 也算配置过的项目**，不再生成占位 instructions | `context.py`（新 `load_cursor_rules`、`load_project_context_with_parents` 重构） | F22 | 低。纯增量 |

**验证**：三个新契约文件共 82 条。`test_reminder_registry.py` 40 条守信封分家（告警侧只能是 `<system-reminder>`、历史侧不得是它、seam 渲染后逐字等于输入、base.md 必须解释两个新标签）、守信封与 provenance 同行（每条 spec 渲染出的消息都被 `is_synthetic_user_message` 判为合成、没有一条 origin 是 `REAL_USER`）、守优先级不是摆设（stop hook 必须是 tail 里最大、drift 必须小于 LSP，并用源码检查断言 `_run_conversation` 里两者的 append 顺序与声明一致），最后全仓库扫描禁止再直接调 `wrap_system_reminder`。`test_message_provenance.py` 29 条：四条"人类真能打出来"的诱饵文本（`[System] boot sequence failed…`、`<system-reminder> is showing up in my output, why?`）在有无 origin 时都必须判为真实用户；六种 legacy 形状在 load 时被正确回填；显式 origin 不得被二次猜测；推断幂等；以及全仓库扫描锁死 `Message.model_validate` 的唯一入口。`test_cursor_rules.py` 13 条：只加载 always-apply、frontmatter 不得进 prompt、多规则按文件名排序且各带来源标注、坏 frontmatter 只警告不炸且不连累同目录其他规则、单层形状保持裸文本不变。

**P4 遗留**：F17 的"token 预算"只做到**每条注入自带上限**（`ReminderSpec.max_chars`，目前只有子 agent 回报设了 8k，与原先散落在 `completion.py` 的硬编码等价），**没有做尾部总预算裁剪**。理由是尾部真正会膨胀的只有子 agent 回报和重复的 drift 副本：前者已在源头设限，后者是为前缀缓存刻意不删的；而能被总预算裁掉的东西全是实时告警，丢弃它们正是这套机制要防的事。如果日后尾部确实堆积，正确的动作是让最旧的 drift 副本可回收，不是加一把无差别的剪刀。

---

## 六、回归防线

仓库已有 `test_system_prompt_stable_volatile.py` 守护"volatile 不进 system"，这是把原则固化成契约测试的范本。照它再加三条，三条原则即有自动防线。

| 防线 | 守住的原则 | 形式 |
|---|---|---|
| 约束存活测试（Phase 0.1） | 原则二 | 跨 rewrite 与 cycle 后断言用户约束原文仍在 |
| provenance 测试 | 原则一 | 向任何消息缩减函数喂入混合 origin 的消息，断言注入物未被标为 `User` |
| 提醒注册表测试 | 原则三 | 每条提醒必须在注册表声明其作废的假设，未声明则失败 |
| system 逐字节稳定性测试 | 原则三（位置维度） | 扩展既有测试：同一 session 连续两轮（含 `/skill` 轮）的 system prompt 必须逐字节相等 |

最后一条会直接锁死 F9 的回归。

## 七、泛化边界

**可移植**（换任何模型、任何 agent 框架都成立）：三条原则本身；账本模式（可推广到任何不可重建类，例如用户的批准与否决记录）；"作废什么假设"这个准入测试；把原则固化成契约测试的做法。

**不可移植**（绑死在当前选型，迁移必须重测）：20/40/50/55/75/90 的比例阶梯是针对具体窗口调出来的；DeepSeek 自动前缀缓存的行为（不需要 `cache_control`）换到 Anthropic 完全不同；12k 的 skills 预算、120k 的摘要器输入上限、2000 字符的逐条截断同理。

---

## 附：本次审核涉及的文件

**提示词**：`prompts/base.md`、`prompts/compact.md`、`prompts/cycle.md`、`prompts/modes/*`、`prompts/approvals/*`、`prompts/personalities/*`

**上下文引擎**：`engine/prompts.py`、`engine/context.py`、`engine/context_pressure.py`、`engine/capacity.py`、`engine/seam.py`、`engine/cycle.py`、`engine/turn.py`、`engine/tools.py`

**编排**：`engine/orchestrator/{core,maintenance,lifecycle,tooling}.py`

**输入与集成**：`state/context.py`、`integrations/{skills,plugins,hooks,lsp}.py`

**工具与序列化**：`tools/registry.py`、`tools/file.py`、`tools/runtime.py`、`client/{chat_messages,anthropic,deepseek}.py`

**既有相关测试**：`tests/engine/test_context_query_survival.py`、`test_system_prompt_stable_volatile.py`、`test_reminder_neutralization.py`、`test_context_compression_policy.py`、`test_long_session_reminder.py`、`test_git_snapshot.py`
