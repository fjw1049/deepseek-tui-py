# Goal 模式审计与优化建议

审计日期：2026-09-27。范围：当前工作区的 Python Goal 状态机、工具、Engine、Workbench 调度及界面。用户确认的主要症状是“过早宣布完成，任务没做完”。此次只新增审计文档，没有修改产品实现。

**结论：优先修复完成判定和跨回合待办保存，不需要重写整个 Goal 系统。** 当前已经有持久化目标、自动续跑、预算、中断、恢复、队列和过期工具调用保护。薄弱点是：目标完成主要依赖模型自报；回合结束会取消剩余 checklist；接受完成后又立即清空目标。这些机制叠加，会放大模型偶发的漏项和提前收尾。

审计发现可以解释这种症状，但没有读取用户某一次出问题的完整会话，因此不能断言该会话具体走了哪条路径。模型质量、上下文压缩也可能影响实际发生频率，需要后续轨迹评测区分。

## 证据与复现

已运行：

- `.venv/bin/python -m pytest tests/goal -q`：67 passed。
- Workbench 的 `chat-store-goal-resync.test.ts` 与 `composer-slash-commands.test.ts`：9 passed。
- 5 个额外本地探针：使用真实 GoalService、工具分发器和 Engine，模型输出由 mock 提供，不调用模型 API。它们证明运行时允许这些状态转换，不代表真实模型发生概率。

临时探针：[probe.py](/private/tmp/goal-mode-audit-20260927/probe.py)，输出：[results.json](/private/tmp/goal-mode-audit-20260927/results.json)。临时目录可能被系统清理，核心结果如下：

| 场景 | 实测结果 |
|---|---|
| 目标要求 pytest 通过；checklist 仍 in_progress；完成理由明确说测试仍失败 | UpdateGoal 被接受；返回“Goal completed successfully”；目标 dump 为 null |
| active Goal 的回合收尾调用通用 checklist reconcile | in_progress 变成 cancelled；开放待办查询变成空字符串 |
| 连续四次自动续跑仅输出“将继续工作”，没有工具调用 | 四次都设置下一轮续跑标志；Goal 保持 active |
| turn_budget=1 用完后 resume | 再次 blocked，should_continue=false |
| 第一轮直接 mark_blocked | 接受；三轮规则没有运行时计数约束 |

## 与 Codex、Claude 的对比边界

Codex 的官方 Goals 说明将目标定义为线程级持久状态：在空闲边界、没有排队用户输入和其他待处理工作时续跑；自动续跑回合无工具调用时抑制下一次续跑；完成要对照具体证据；预算耗尽与完成分开。[OpenAI：Using Goals in Codex](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)

Claude Code 的普通执行机制是“收集上下文—行动—验证”的循环；Stop hook 可阻止结束并给出继续原因，公开文档还描述了防止 hook 连续循环的保护。这是可扩展的停止检查机制，不能直接视为与 Codex Goals 相同的产品状态机。[Claude Code 执行机制](https://code.claude.com/docs/en/how-claude-code-works)、[Stop hook](https://code.claude.com/docs/en/hooks#stop-decision-control)

Anthropic 的长任务研究另外提出验收功能清单、进度记录和端到端验证，用于减少跨上下文遗忘及过早宣布完成。这是研究方案，不意味着所有 Claude Code 会话默认具备这些保障。[Anthropic：Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

| 维度 | 当前项目 | 应借鉴的方向 |
|---|---|---|
| 持久目标与生命周期 | 已有独立状态机、持久化、中断和恢复 | 保留这些基础 |
| 完成判定 | complete 直接提交，验收靠提示词 | 为可验证条件加运行时检查；保留模型对语义的判断 |
| 回合与目标的关系 | 正常回合收尾会取消开放 checklist | 剩余需求跨回合持续存在 |
| 自动续跑 | active、模式允许、预算未耗尽即可继续 | 加无工具续跑抑制和用户输入优先 |
| 长任务工作记录 | 原目标和聊天历史为主，没有 Goal 专属验收账本 | 保存需求、证据、剩余项及下一步 |
| 完成后的回看 | 发完成事件后清空当前 Goal | 留下可恢复的结构化结果 |

以上对比不证明 Codex、Claude 使用了某种未公开的独立验收器，也不能说明它们永不误判。建议的完成检查是本项目的工程改进，不是声称复刻其私有实现。

## 按优先级排列的发现

### P1：完成调用没有验收关卡，且返回值强化错误结论

位置：[UpdateGoalTool](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/tools.py:148)、[mark_complete](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:146)、[完成回复模板](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/injection.py:72)。

UpdateGoal 只要求 status，reason 可缺省。执行 complete 时直接调用 mark_complete；后者只检查当前目标是否 active，不检查 completion_criterion、未完成项、相关验证结果或必要后台工作。成功返回后又要求模型向用户声明目标已完成。

探针的返回文本甚至同时包含“Goal completed successfully”和“Tests are still failing”。这不是建议用关键词分析 reason；它说明运行时缺少证据输入和拒绝路径。

**建议：把 complete 当作完成申请。** 保留工具名称即可，先在工具适配层检查与该目标有关的未完成验收项、明确失败或缺失的必要验证，以及必要后台工作；通过后才提交状态。失败时保持 active，并返回具体未满足项和应做的检查。不要只增加一句“再检查一遍”。

对于研究、设计等不能靠测试退出码判定的任务，要求“要求→产物/来源→结论”的对应关系，清楚标注未知项。运行时只能验证证据存在、关联和时效，不能凭空保证语义正确。

### P1：通用回合清理破坏 Goal 的跨回合待办

位置：[回合收尾调用顺序](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:2358)、[reconcile_open_checklist_items](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/todo.py:180)、[开放待办检查](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:2683)。

Engine 在调用 `_finish_goal_turn` 之前执行通用 reconcile，把 pending/in_progress 改成 cancelled。下一轮开放项检查排除 cancelled。该逻辑的原意是避免空闲界面保留旋转待办，但业务数据被用于表达界面状态。

Goal 提示词恰好鼓励“完成一块工作就结束本轮”。因此正常的分段推进也会触发剩余待办取消。代码注释和提示词虽说明这不等于用户取消，但结构化状态仍被关闭，下一轮依赖模型从聊天中重建。

**建议：Goal 绑定的未完成项在轮次结束、暂停和中断时保留。** UI 是否旋转由线程执行状态决定。只有用户删减范围或有明确取消依据时才取消需求。长期应区分目标验收项和临时执行步骤，避免把某一轮计划直接当成完整需求。

### P1：验收标准在常用创建入口没有形成明确契约

位置：[Workbench/HTTP 创建路径](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3757)、[CreateGoal schema](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/tools.py:55)。

类型支持 completion_criterion，但 `/goal` 创建只传 objective。模型工具的 completionCriterion 也是可选，描述仅要求用户已提供时带上；没有后续补全验收标准的更新接口。这不表示原始 objective 中不能写验收条件，而是运行时无法稳定逐项追踪。

**建议：清晰任务从用户请求提取少量可检查的验收项并展示，然后直接开工。** 只有真正影响范围的歧义才询问。不要把每个 Goal 变成长表单审批，也不要让模型自行扩展需求。复杂任务可有 requirements 列表；小任务保留简短标准。

验收项的变更应可追踪：用户明确缩减范围后才能删除要求，不能为凑齐完成状态而把失败项取消。

### P2：完成等同清空，误判后的恢复代价过高

位置：[mark_complete 的 clear](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:165)、[恢复时丢弃 complete](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/persist.py:51)。

完成快照通过事件发出后，服务状态立即清空；持久化 dump 不再保存该目标，restore 也直接忽略 complete。历史事件及聊天文本仍可能保留，不能说所有历史丢失，但 GetGoal/目标栏没有可回看的完成记录。

**建议：完成记录保留 objective、验收项、证据、未解决说明和用量，直到明确替换/清除。** 提供“重新打开”作为误判恢复入口，重新打开要使不再适用的旧证据失效。队列推进先存档旧结果，再启用下一目标；无需第一版建立复杂历史系统。

### P2：续跑没有跨回合无进展保护

位置：[peek_continuation](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:357)、[续跑提示](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/injection.py:8)、[单回合工具去重](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/tool_dedup.py:1)。

四次纯文本自动回合都继续触发续跑。已有工具去重仅限单回合，不能保护“每轮重复同一次调用”的情况。默认不设置预算时，这类反复可持续发生。

**建议：先加简单可靠的底线。** 自动续跑回合没有工作工具调用、没有终态转换时抑制下一次续跑，展示原因；不要把它误标成完成。GetGoal 等控制/读取自身状态的调用不能单独算推进。再根据评测加入跨轮重复失败识别，避免一开始写复杂语义评分器。

“必须每轮只做一块”改成“持续推进到自然检查点，必要时跨轮继续”。合理拆分能帮助长任务，但无需人为拆短每个任务。结束条件应是全部约定要求满足，而非开放式的“没有任何有用的下一步”。

### P2：预算耗尽与阻塞混用，恢复按钮没有对应动作

位置：[resume](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:114)、[GoalStrip](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GoalStrip.tsx:19)、[token 统计](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:294)。

预算耗尽会标 blocked；UI 对所有 blocked 提供“继续”；原预算未变化时 resume 会立即再次 blocked。界面还没有展示 terminal_reason。现有 token 统计主要围绕 output_tokens，UI 却统称 tokens；token 检查发生在模型响应后，也不等于精确的生成上限。

**建议：增加 budget_limited，或至少加结构化 stop_reason。** 普通暂停显示“继续”，缺输入显示缺什么，预算耗尽显示“调整预算后继续”。说明预算统计口径；若要控制总成本，应单独使用输入、输出和缓存费用账本。不要无声自动增加预算。

### 待验证风险：用户队列与服务端续跑争抢空闲边界

位置：[服务端调度](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3886)、[前端排队](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2554)。

前端 busy 时把输入存在 queuedMessages；服务端回合关闭后立即尝试续跑，只检查服务端 active_turn 和续跑标志。这里没有统一的“用户待发消息优先”信息。可能出现用户追问等待下一轮的体验，但本次未完成浏览器与 SSE 的并发复现，故不列为已证实竞态。

后续应将用户待发输入纳入服务端调度，原子地决定下一项工作；相关后台任务也应按依赖关系等待，不能被任意常驻后台进程永久阻止。

## 建议的最小实现路线

**第一批：直接解决提前完成。**

1. 为当前 Goal 标识其验收项/待办，不在通用 turn-end reconcile 中取消它们。
2. 给 UpdateGoal complete 增加完成前检查，返回可行动的未满足项。纯函数状态转换仍放 GoalService；Engine/工具层提供观测证据，避免 Service 耦合整个引擎。
3. 完成状态先保留，不立即 clear；终态事件、持久化和 UI 一致。
4. 未通过验收时使用阶段进展消息；只有完成检查通过才能生成“目标已完成”的产品提示。

初版完成检查应覆盖少量明确事实：仍有必要未完成项、相关验证明确失败或尚未执行、依赖产物尚未返回。不要检查全仓库所有历史测试失败，也不要把 checklist 全绿当成充分条件。

**第二批：让目标有可审查的验收依据。**

保持现有 objective，增加少量 required acceptance items 与 evidence references。每条证据记录实际命令/产物/来源、结果、时间或对应文件状态。最后修改相关代码后，旧的通过结果不能继续当作新版本验收。研究任务使用来源和报告段落，不强塞 pytest。

完成申请概念上携带 `summary + evidence_refs + remaining_items`。运行时检查证据；没有机器可判定的条件才由模型做明确的逐项审计。初期无需额外评审模型；若实测仍有较多语义漏项，再试验独立审计回合，并测量成本与收益。

**第三批：稳定续跑与操作体验。**

加入无工具自动轮抑制、用户输入优先、预算恢复入口。三轮 blocker 规则目前只在提示词里，探针证明首轮仍可 blocked。若继续保留此规则，就用 blocker identity/连续轮数记录；但缺凭据这种只能由用户解决的条件没有必要原地消耗三轮，可在独立工作耗尽后停止，瞬时网络失败则进行有界重试。这是本项目可选择的策略，不必照抄其他产品的阈值。

界面优先展示“目标、验收完成数、剩余事项、停止原因、下一步”。Token 使用量是成本指标，不是任务完成百分比。完成后保留可展开的验收结果。

## 最低验收测试与行为评测

| 用例 | 期望 |
|---|---|
| 只写计划后 complete | 拒绝，目标仍 active |
| 3 条必要需求只完成 2 条 | 拒绝，准确指出剩余项 |
| 必要测试失败后 complete | 拒绝；无成功完成提示 |
| 测试曾通过，之后相关实现再次修改 | 旧证据失效，要求相关复验 |
| Goal 活跃时正常结束一轮 | 剩余需求保留，下一轮可见 |
| 暂停、恢复、上下文压缩 | 范围、验收项和证据关联不丢失 |
| 连续无工具自动轮 | 抑制续跑，保留未完成状态和原因 |
| 用户明确删减一条要求 | 留下变更依据后允许按新范围验收 |
| 预算耗尽后点击继续 | 明示需要调整预算，不假装恢复 |
| 用户消息与自动轮同时到达 | 用户消息优先，最多启动一个回合 |
| 全部必要验收通过 | 标 complete；持久化保留结果；只推进下一目标一次 |

现有测试证明既有状态转换稳定，但不能证明模型会正确完工。补充固定小型任务集，比较“普通 Agent / 当前 Goal / 改进 Goal”，保持模型、资源限额和任务相同，每类重复多次。

首要指标是**错误完成率**：宣布完成但独立验收未通过的比例。同时记录真实完成率、预算内完成率、人工催促次数、无进展自动轮数和消耗。若完成更慢但错误完成率显著降低，未必是退步；若只是回合变多而结果不改善，则不能视为优化。

首选落地顺序：**保护剩余需求 → 完成前验证 → 保留完成记录 → 改善续跑和预算体验。** 不建议先增加更多“不要提前停止”的提示词、默认多 Agent 审核，或重写整套编排架构。
