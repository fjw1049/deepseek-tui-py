# 主会话消息「产生 → 渲染」端到端梳理（Subagent agent_7d537c8d 完整报告）

> 只读分析，未修改任何源文件。文中行号均来自当前工作树（含未提交改动）。

## 0. 链路总览

```
Python runtime(事件产生/持久化)
  manager._emit_event → store.append_event(分配 seq、JSONL 落盘)→ event_bus.send
  routes.stream_thread_events:先重放 backlog,再转发 live,输出 text/event-stream
Electron
  preload startSse('runtime:sse:start') → 主进程消费 SSE → 'runtime:sse-event' IPC 回推
Renderer 传输层
  deepseek-runtime.subscribeThreadEvents:解析 row{seq,event,payload} → ThreadEventSink
  item.delta 用 requestAnimationFrame 聚批
状态层
  chat-store.buildThreadEventSink:事件规范化为 ChatBlock[] + liveReasoning/liveAssistant
渲染层
  Workbench(useShallow)→ MessageTimeline(groupTurns 分 turn)→ MemoMessageTurn
  → ProcessStream(过程轨)/ MessageBubble(正文)/ FloatingComposer(审批、提问)
  → OperationContextDock(从 blocks 提取 todos/tasks/subagents)
```

- 事件产生与 seq：`src/deepseek_tui/server/threads/manager.py:6528-6542`（`_emit_event` 先 `append_event` 再 `event_bus.send`）；seq 在每线程写锁 + 全局 `_seq_lock` 下单调递增并周期 checkpoint：`src/deepseek_tui/server/threads/store.py:303-331`。
- SSE 端点：`src/deepseek_tui/server/routes.py:49-73`（backlog 重放 + live 队列 + 15s 心跳），`routes.py:586-615`（`since_seq` 参数 + StreamingResponse）。
- 传输桥：`packages/workbench/src/preload/index.ts:169-189`（`startSse/stopSse/onSseEvent/onSseEnd/onSseError`）。

## 1. 数据来源与事件协议

三种形态并存：

1. **快照**：`AgentProvider.getThreadDetail` 返回完整 `ChatBlock[]` + `latestSeq` + 轮次计时/turn-diff 账本（`packages/workbench/src/renderer/src/agent/types.ts:452-464`）。触发点：`selectThread`（chat-store.ts:2257-2306）、turn 完成后的 `reloadActiveThreadBlocks`（chat-store.ts:394-446，由 onTurnComplete 调用于 chat-store.ts:1449）。
2. **SSE 增量**：`subscribeThreadEvents(threadId, sinceSeq, sink, signal)`（types.ts:547-552；实现 `agent/deepseek-runtime.ts:1593-2252`）。事件面 `ThreadEventSink` 完整定义于 types.ts:397-436。流式 delta：`item.delta`（kind=`agent_message`|`agent_reasoning`）在 deepseek-runtime.ts:1699-1707 收集，经 `scheduleDeltaFlush/flushPendingDeltas`（1636-1656）按 rAF 聚批送达；其他事件到达前先 flush（1709）保证顺序。断线续传：`nextSinceSeq = max(nextSinceSeq, seq)`（deepseek-runtime.ts:1687-1695），指数退避 750ms→5s、连续 6 次失败后报错（2234-2240、2249-2250），重连从 `nextSinceSeq` 重放（2218）。
3. **乐观更新**：`sendMessage` 先插入 `u-<时间戳>` user block（chat-store.ts:2443-2487），`sendUserMessage` 返回 `userMessageItemId` 后用 `reconcileOptimisticUserBlock` 迁移 id/turnId/模型徽标（chat-store.ts:2622-2663；实现在 `store/chat-store-runtime-helpers.ts:250-268`）；SSE `item.started/completed` 的 `user_message` 再做二次对账（deepseek-runtime.ts:1711-1717、1749-1752）。

事件映射（deepseek-runtime.ts）：`item.started`→`onTool`(running) 或 `onUserInput`（1720-1743）；`item.completed/failed`→`onFinalAnswer`（1806-1817）、`onLiveSegmentComplete`（1818-1831）、`onTool`（1832-1870）、`onSystemStatus`（1786-1805）、`onPhaseNarration`（1754-1763）；`turn.completed`→`onTurnComplete`（1921-1972）；`turn.diff.updated`→`onTurnDiffUpdated`（1874-1919）；`approval.required`/`elevation.required`（auto-approve/trust/deny 先拦截，2113-2173）；`user_input.required`（2083-2099）；`subagent.mailbox`（2101-2111）；`thread.updated`（1984-2081）；`goal.updated`（1976-1982）。

## 2. chat-store 的职责与分支

`buildThreadEventSink`（chat-store.ts:754-1479）是唯一规范化入口；状态字段见 `store/chat-store-types.ts:83-150`（`blocks/liveReasoning/liveAssistant/lastSeq/busy/currentTurnId/currentTurnUserId/turnStartedAtByUserId/turnDiffByTurnId` 等）。

- **seq/连接健康**：`onSeq` 更新 `lastSeq` 并清"流恢复中"错误（chat-store.ts:759-765）；`noteBusyStreamActivity` 重置看门狗（708-716）。
- **用户消息** `onUserMessage`（766-804）：先 `flushLiveBlocks`（374-392）固化 live 文本；用 `currentTurnUserId` reconcile 乐观块（771-784）；`upsertUserBlock`（helpers 228-248，按 id 命中原位合并、未命中则 append）；置 `busy=true` 并记 `turnStartedAtByUserId`。
- **流式文本** `onDeltas`（805-889）：reasoning 累积到 `liveReasoning`；首个 `agent_message` delta 到达时把未固化 reasoning 落为独立块再累积 `liveAssistant`（858-868）；推进 `lastSeq`（813-819）与 reasoning 计时账本（844-855）。
- **工具调用** `onTool`（890-980）：按 `itemId` 命中→原位更新（meta 浅合并保留 started 时的 `tool_input`，934-945）；新工具→先 flush live 再 append（955-972）；完成后经 `applySpawnPromptsToSubagentBlocks` 回填子代理提示（951、972）。
- **审批/提权/提问/进化** `onApproval`（981-1018）/`onElevation`（1047-1079）/`onUserInput`（1080-1107）/`onEvolutionProposal`（1019-1046）：均按业务 id 查重防重复卡，append pending 块；`onUserInputStatus` 按 id/requestId 原位更新（1108-1131）；线程重载时 `syncRuntimePendingApprovals` 兜底补挂（418-423、2274）。
- **子代理** `onSubagentMailbox`（1254-1309）：`applyMailboxMessageTouched` 归约出全部被触卡片（含父卡 childIds/worker 归属），逐一 upsert `subagent-*` 块（1282-1303）。
- **段落固化** `onLiveSegmentComplete`（1310-1340）：reasoning→`appendLiveReasoningBlock`（265-293）；`agent_message` 一律按 `mid_turn_preface` 固化（1319-1336）；`onFinalAnswer`（1341-1349）→`upsertFinalAnswerBlock`（chat-store-runtime-helpers.ts:289-299，过滤同 id reasoning 临时块）。
- **叙述桥** `onPhaseNarration`（1350-1383）：reasoning 段未到达时先落空文本+`narration` 占位块，后续同 id upsert（SSE 重连/批处理竞态兜底）。
- **turn 收尾** `onTurnComplete`（1404-1452）：flush live、清 `currentTurnId`、保留 `lastCompletedTurnId` 供 turn-diff 查询（1419-1422）、`expireTurnApprovals`+`finalizeOrphanSubagentBlocks` 清悬挂卡（1426-1430）、随后 reload 对账 + `drainQueuedMessages`（1449-1451）。
- **排队/发送**：`sendMessage`（2370 起）busy 或有 pending 块时入队（2406-2438）；`drainQueuedMessages` 串行出队（2326-2340，模块级 `drainingQueuedMessages` 防重入）；发送前 abort 旧 SSE、warmup、`seqAtSend` 快照后重开订阅（2584-2682）。
- **选线程** `selectThread`（2233-2322）：快照加载→`threadSnapshotLooksRunning` 判 busy→挂账本→重开 SSE；离开 busy 线程登记 `watchTurnCompletion`（2243-2246）。

## 3. 渲染链路

- **store→Workbench**：`Workbench.tsx:292-330` useShallow 订阅；`Workbench.tsx:1650-1665 / 1755-1766 / 1825-1836 / 1906-1917` 四种布局分别挂载 `MessageTimeline`，传 `blocks、liveReasoning、live=liveAssistant`。
- **MessageTimeline**（`components/chat/MessageTimeline.tsx`）：
  - 分 turn：`groupTurns`（876-906）按 blocks 数组顺序线性分组——`user` 开新 turn，`system` 为独立分隔 turn（内部 subagent 交接文案剔除，885-893）；**无任何按 createdAt 排序，渲染顺序即 store blocks 顺序**。
  - 分页：`AUTO_COLLAPSE_THRESHOLD=24`、`TURN_PAGE_SIZE=18`（165-167），只渲染尾部 N 个 turn（301-308），顶部滚动/按钮加载更早（310-321、686-696）。
  - 每 turn 实例化（698-748）：`isLive` 按 `currentTurnUserId === turn.user.id`（700）；`processing = (busy && isLatestTurn) || turnPending || hasLiveStream`（720-721）；turn-diff 快照按 `resolveTurnDiffId`（`lib/turn-mutation-view.ts:97-104`：优先 `turn.user.turnId`，最新 turn 回落 current/lastCompleted）取自 `turnDiffByTurnId`（714-745）；key 为 `userId ?? turn-${index}`（724）。
  - **MemoMessageTurn**（1209-1223）：逐字段浅比较的自定义 memo，是流式期间保护历史 turn 不重渲染的关键。
  - turn 内分轨（1022-1088）：assistant 块经 `splitThink` 拆 think/正文；`agentSegment==='final_answer'` 进正文轨，其余进过程轨（`message-timeline-logic.ts:97-111`）；`reasoning/tool/approval/elevation/user_input/subagent/system` 属过程轨（`isProcessBlock`，930-940）；live 文本只在最新 turn 大气泡流式展示、不重复进过程轨（1059-1064、1091-1096）。
  - 过程轨 `ProcessStream`（2077-2146）：`visibleExecutionBlocks`（1684 起）剔除被 todo/subagent 摘要收纳的行→`groupProcessRows`（`message-timeline-logic.ts:175-199`）把相邻只读探针折叠为 `tool_batch`→`planProcessRenderChunks`（346 起）聚成可折叠摘要；思考指示符只落在最后一个未被后续工作覆盖的行（`trailingThinkingIndicatorId`，77-95）。**去重/合并主要在这两个纯函数，而非 store**。
  - 正文 `MessageBubble`（3156-3227）：user→`UserMessageBubble`；assistant→`AssistantMarkdown`（仅 live 解析未闭合 markdown，3169）；`approval` 返回 null（3212-3213）、`user_input` pending 返回 null（3205-3207）——pending 审批/提问由 `FloatingComposer` 顶部渲染（`FloatingComposer.tsx:419-446` 从 blocks 过滤 pending 列表），settled 后才回落时间线。
  - 滚动：stick-to-bottom + 用户滚动冷却（371-394）、ResizeObserver 同帧钉底（399-409）、发送时 tail-anchor 把用户气泡钉视口顶（429-434）、`scrollToBlockId` 手写缓动跳转（436-489）。
- **OperationContextDock**：`OperationContextDock.tsx:304-316` 订阅 `blocks/activeThreadId/threads/workspaceDirtyTick`；从 blocks 提取 todos（337）、tasks（341）、subagents（368）；`workspaceDirtyTick` 触发 git 状态刷新（336）。

## 4. 本次未提交改动对消息展示链路的影响（父会话 git 补充）

Subagent 沙箱内无法执行 git diff，以下由主会话用 `git diff --stat` 核实：

- `MessageTimeline.tsx` −430 行（净减最多）、`OperationContextDock.tsx` −101 行：展示组件瘦身，把可独立测试的逻辑拆到 lib/hook（对应新增的 `run-activity.ts`、`run-subagent-flow.ts`、`use-task-run-detail.ts` 等及测试）。
- `TaskRunDialog.tsx` 整文件删除（−314 行）：Task/子代理详情从弹出对话框迁往右侧栏 RunPanel 体系（`RunPanel.tsx`/`RunActivity.tsx`/`RunSwitcher.tsx` 为新增文件）。
- `Workbench.tsx` +17 行、`WorkbenchRightSidebar.tsx` ±21 行：接线新面板（runRequest 自动开右栏、lazy 挂载 RunPanel）。
- `chat-store.ts` 仅 ±1 行、`deepseek-runtime.ts` ±3 行、`types.ts` +2 行：消息规范化与事件协议本身几乎未动——本次改动集中在**展示层重组**，不动数据链路。
- Python 侧 `manager.py` ±8 行，与消息展示无直接关系。

## 5. 潜在问题（附 文件：行号 证据）

1. **旧线程 SSE 事件无 threadId 防护，线程切换窗口可能写脏新线程的 blocks**。`selectThread` 仅靠 `sseAbort?.abort()` 停旧流（chat-store.ts:2250），abort 不撤回已在 IPC 队列中的回调；`onSseEvent` 处理器无 `signal.aborted` 前置检查，`stopSse` 到下一轮循环才异步执行（deepseek-runtime.ts:1678-2180、2206-2216）；sink 各 `set` 处理器（如 onUserMessage chat-store.ts:766-804、onTool 890-980）闭包不带 threadId 直接写全局 state。缓解：创建 sink 时捕获 threadId，回调先比对 `get().activeThreadId`。
2. **`onUserMessage` 对未登记的用户消息一律尾部 append，可能破坏时序**。`upsertUserBlock` 未命中 id 时 `[...blocks, nextBlock]`（chat-store-runtime-helpers.ts:237-238），渲染顺序完全等同 blocks 顺序（`groupTurns`，MessageTimeline.tsx:876-906，无排序）。正常流事件有序故安全；但 user_message 事件迟到且 id 未登记的路径（如 deepseek-runtime.ts:1749-1752 的 completed 重放、或问题 1 的跨线程事件）会把用户气泡插到会话末尾。
3. **`onTurnComplete` 全量对账与 SSE 迟到事件互相覆盖**。turn 完成后异步 reload（chat-store.ts:1449），reload 的 set 只防线程切换、不防事件乱序（chat-store.ts:424）：reload 先落库会抹掉其窗口期到达的事件，后到达则基于新 blocks 应用——最终状态依赖完成时序。缓解：reload 期间暂存事件或完成后比对 `lastSeq`。
4. **turn 计时账本与乐观块 key 迁移依赖时序**。`onUserMessage` reconcile 乐观块 id 时不同步迁移 `turnStartedAtByUserId`（chat-store.ts:771-784 只改 blocks；迁移仅在 sendMessage 拿到 `userMessageItemId` 的路径，2633-2663）；若 SSE 先于 HTTP 响应且 `currentTurnUserId` 未命中，留下孤儿 `u-<t>` 键，`MessageTurn` 的 `liveStartedAt`/reasoning 时长（MessageTimeline.tsx:701-711、777-783）查不到，计时显示退化。
5. **历史 turn 的 React key 不稳定**。无 user 块的 turn 以 `turn-${index}` 为 key（MessageTimeline.tsx:724）；turn 数变化使 index 漂移导致整段重挂载、`workExpanded` 等本地状态丢失（1009-1013）。
6. **性能面：blocks 高频变更触发多订阅者全量重扫**。`onDeltas` 每个 rAF 批产生新 `blocks/liveAssistant` 引用（chat-store.ts:876-887），`Workbench`（useShallow 含 blocks，Workbench.tsx:292-330）与 `OperationContextDock`（OperationContextDock.tsx:309-316；337/341/368 三个 useMemo 依赖 blocks）随之重算；时间线靠 `MemoMessageTurn` 兜住，但 dock 的提取函数对大 blocks 数组是每 delta 全量扫描，长会话潜在卡顿。

### SUMMARY
主会话消息链路：Python runtime 侧 `manager._emit_event` 先把事件按单调 `seq` 写入 JSONL（`store.append_event`）再广播，`routes.stream_thread_events` 以「backlog 重放 + live 队列」输出 SSE；Electron preload 经 IPC 把事件送入渲染进程，`deepseek-runtime.subscribeThreadEvents` 解析 `row{seq,event,payload}` 并按 rAF 聚批流式 delta，回调 `ThreadEventSink`；`chat-store.buildThreadEventSink` 把每类事件规范化为 `ChatBlock[]` + `liveReasoning/liveAssistant`（用户消息走乐观块→runtime id 对账，工具按 itemId upsert，审批/提问/子代理按业务 id 去重追加，final answer/preface/reasoning 按 agentSegment 固化，turn 完成后全量 reload 对账）；渲染侧 Workbench 以 useShallow 订阅并传 `blocks/liveReasoning/liveAssistant` 给 MessageTimeline，后者 `groupTurns` 按 blocks 顺序分 turn、分页渲染，MemoMessageTurn 逐字段 memo，turn 内拆「过程轨（groupProcessRows 折叠探针）/正文轨（final_answer）」，pending 审批与提问由 FloatingComposer 顶部渲染，OperationContextDock 从 blocks 提取 todos/tasks/subagents。消息到达形态为快照、SSE 增量、乐观本地更新三者组合。主要风险：旧线程 SSE 事件缺 threadId 防护、`upsertUserBlock` 尾部追加可破坏时序、turn 完成后全量 reload 与迟到事件的覆盖竞态、计时账本 key 迁移时序依赖、无 user 块 turn 的 index key 不稳定、dock 对 blocks 的每 delta 全量扫描。
