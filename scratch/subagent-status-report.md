# Task/Subagent 状态更新流程（Subagent agent_53aa06c7 完整报告）

> 只读分析，未修改任何源文件。文中行号均来自当前工作树（含未提交改动）。
> 删除文件原文（use-dock-subagents）由主会话以 `git show HEAD:` 补充核实。

## 1. 状态来源与事件流（谁产生、走什么通道）

**Subagent 状态：引擎内产生 → mailbox → 引擎事件 → HTTP 持久化 + SSE → 渲染层。**

1. **产生（引擎侧）**：子代理对象创建即 `running`（`src/deepseek_tui/tools/subagent/agent.py:77`）；spawn 时 `SubAgentManager` 向 mailbox 发 `child_spawned`（有父时）与 `started`（`tools/subagent/manager.py:231-241`）；子代理循环发 `progress`（每轮叙述，`tools/subagent/loop.py:782-784`）、`tool_call_started/completed`（loop.py:875-915）、`token_usage`（loop.py:953-958）；终态由 `_drive_agent` 发出：`cancelled`（manager.py:415-420、250-262）、`failed`（manager.py:423-429）、`completed`/`cancelled`（manager.py:451-456）；取消/恢复（resume）路径重发 `started`（manager.py:301-306）。
2. **汇聚（mailbox）**：所有生产者共享一个进程内 `asyncio.Queue`（上限 512，全局单调 seq），`Mailbox.send` 满时丢最旧的进度包保终态包（`tools/subagent/mailbox.py:172-207`）。
3. **引擎事件化**：每个 Engine 的 `SessionActivityCoordinator` 每 0.4s 排空 mailbox 并逐包转成 `SubAgentMailboxEvent`，同时发 `SessionActivityEvent`（running_subagents/running_tasks 计数）（`engine/cycle.py:404,455-477,479-497`；事件定义 `engine/events.py:112-117`）。事件经 `EngineHandle.try_emit` 非阻塞入队，队满即丢弃（`engine/handle.py:163-175`；容量 1024，`server/threads/models.py:14`）。
4. **服务端桥接（threads manager）**：`_monitor_turn` 消费 `SubAgentMailboxEvent`，过滤上一轮遗留的 foreign agent 后，`_persist_subagent_mailbox` 把信封写成一条 `TurnItemRecord(kind=status, summary="subagent:{agent_id}", metadata={subagent_mailbox:true})` 并对外发 `subagent.mailbox` 事件（`server/threads/manager.py:5973-5980`、4692-4723）。turn 收尾三连：`_cancel_orphan_subagents` → `_flush_pending_subagent_mailbox`（补排空）→ `_reconcile_subagent_cards`（按 manager 权威快照重发终态信封，seq=0）（manager.py:6109-6117、6022-6030、4806-4851）。
5. **传输到渲染层（双通道）**：
   - **实时 SSE**：`GET /v1/threads/{id}/events?since_seq=`（`server/routes.py:49-66,592-615`），先重放 backlog 再直播。前端经 `window.dsGui.onSseEvent` 收流（`agent/deepseek-runtime.ts:1678-1697`；重连循环 :2218），`subagent.mailbox` 事件映射为 `sink.onSubagentMailbox`（deepseek-runtime.ts:2101-2110）。
   - **hydrate/重放**：线程详情里的 status item（`metadata.subagent_mailbox===true`）被识别（deepseek-runtime.ts:681-684），从 detail JSON 还原信封（deepseek-runtime.ts:710-739），逐条重放进同一归约器（deepseek-runtime.ts:1203-1214）。
6. **渲染层落地**：`chat-store.onSubagentMailbox` 用 `applyMailboxMessageTouched(subagentCardsFromBlocks(blocks), msg)` 归约出卡片，把 touched 的每张卡 upsert 成 `subagent` 块，并回填 spawn prompt（`store/chat-store.ts:1254-1308`）。

**Task 状态：引擎后台 worker 产生，无推送，前端轮询 + 工具结果元数据两条路。**

1. **产生**：`TaskStatus` 由 `tools/task/manager.py` 独占迁移：入队 `queued`（task/manager.py:191）、resume 重置 `queued`（:282）、worker 取到即 `running`（:590）、终态 `TIMED_OUT/CANCELED/FAILED/COMPLETED`（:665-707）；重启恢复时 stale running→`FAILED`，否则回 `queued`（task/store.py:167-186）。
2. **通道 A（快照进对话）**：task 工具结果的 `metadata.tasks` 被 `task_tool_metadata_from_result` 写进工具块元数据（`server/threads/items.py:424-449`；来源 `tools/task/tools.py:341-348`），前端 `extractTasksFromBlocks` 按 task id 去重取最后一次触碰的状态（`lib/extract-tasks-from-blocks.ts:99-108`）。
3. **通道 B（轮询覆盖）**：`useLiveTasks` 在存在 active 任务时每 2s `GET /v1/tasks` 覆盖状态，全部终态后停表（`hooks/use-thread-tasks.ts:11,234-251,263-309`）。
4. **详情轮询**：`useTaskRunDetail` 对可见的那一个 task 每 1.5s `GET /v1/tasks/{id}`（prompt/timeline/时长），非 active 即停（`hooks/use-task-run-detail.ts:14-37`；请求封装 use-thread-tasks.ts:54-76）。

## 2. 状态机：状态集合与迁移定义位置

- **引擎 SubAgentStatusKind（权威源）**：`running / completed / interrupted / failed / cancelled`，`tools/subagent/types.py:401-435`。迁移点：spawn→running（agent.py:77；resume 重置 manager.py:288-297）；cancel→cancelled（manager.py:250-262,413-421,433-436）；异常→failed（manager.py:423-429）；成功→completed（manager.py:437-441）；进程重启后磁盘 running→interrupted（manager.py:542-548）。注意 `interrupted` 不在 UI 生命周期类型里，只作为残留状态参与降级（第 6 节 R7）。
- **mailbox 消息种类（传输层状态机）**：`started/progress/tool_call_started/tool_call_completed/child_spawned/completed/failed/cancelled/token_usage`（mailbox.py:16-25）。
- **UI SubagentLifecycle**：`pending / running / completed / failed / cancelled`（`lib/subagent-mailbox.ts:6`）。迁移：`pending` 仅由 `child_spawned` 建卡（subagent-mailbox.ts:566-569,490）；`started/progress/tool_*`→`running`（:350-370，中途建卡兜底 :594-604）；`completed/failed/cancelled`→同名终态（:372-385）。fanout 卡聚合：任一 failed→failed；有 running/pending→running；全 completed→completed；全 cancelled→cancelled；混合终态→cancelled（:640-651）。
- **TaskStatus（引擎）**：`queued/running/completed/failed/canceled/timed_out`，`is_terminal`/`is_resumable`（resumable=canceled/timed_out/failed）在 `tools/task/models.py:42-64`。
- **TaskStatus（前端归一）**：`lib/extract-tasks-from-blocks.ts:3,45-51,53-64`（`normalizeTaskStatus` 兼容 done/error/timeout/cancelled 拼写）。
- **UI 映射**：`isRunActive`（running/pending/queued 算活跃，`lib/run-activity.ts:56-58`）、`runStatusKey`（含 `timed_out`，run-activity.ts:60-67）、`RunStateIcon`（`components/right-sidebar/RunActivity.tsx:10-16`）。

## 3. subagent-mailbox 机制与 run-panel-store 的关系

- **消息入**：`applyMailboxMessage(cards, msg)` 唯一入口（subagent-mailbox.ts:548-614）。路由：① `child_spawned` 永远先接父（delegate 父挂 childIds，fanout 父收 worker，:558-582）；② 无卡且被某 fanout 认领的 worker 消息并入父卡（:586-593，认领查找 :513-523）；③ `CARD_BOOTSTRAP_KINDS` 允许中途建卡（SSE 重连错过 `started` 的场景，:499-511,594-604）；④ 其余按 delegate/fanout 归约（:608-613）。
- **步进条目**：工具行按 `tool_call_id` upsert，缺 id 回退 `step+name` 临时行并晋升（:158-192,215-254）；生命周期行尾项去重（:281-300）；进度行按归一化 label 去重（:302-330）；上限 steps 200 / 预览 3 条（:84-86,153-156,139-151）。
- **出（持久化形状）**：`subagentBlockFromCard` 转回 `subagent` ChatBlock 并维护 startedAt/finishedAt（:726-770）；反向 `subagentCardsFromBlocks`（:688-724）。touched 语义保证重建式写者不丢父卡更新（:616-638；依赖方 chat-store.ts:1277-1281、deepseek-runtime.ts:1208-1210）。
- **孤儿清理**：`finalizeOrphanSubagentBlocks` 把轮次已结束仍 pending/running 的卡强改 `cancelled`（subagent-mailbox.ts:782-822），chat-store 在 hydrate、busy 清除、turn-complete 三处调用（store/chat-store.ts:413-415,474,1426-1427,2126-2132,2269-2272）。
- **与 run-panel-store 的关系：无直接依赖**。`run-panel-store` 只存选中目标 `{threadId, kind, id}` + request 计数（`store/run-panel-store.ts:4-22`），不含运行状态；状态全在 `chat-store.blocks`。mailbox 归约只发生在 chat-store（实时）与 deepseek-runtime（hydrate），run-panel 侧只读。

## 4. UI 消费与多 run 切换

- **订阅源**：RunPanel 订阅 `useChatStore` 的 activeThreadId/blocks 与 `useRunPanelStore` 的 target/open（`components/right-sidebar/RunPanel.tsx:23-30`）。选项列表 = `extractTasksFromBlocks` + `useLiveTasks` 覆盖 + `extractSubagentsFromBlocks`（RunPanel.tsx:27-34；subagent 抽取 `lib/extract-subagents-from-blocks.ts:102-120`）。
- **RunDetail**：task 走 `useTaskRunDetail`（1.5s 轮询），subagent 走 blocks 卡片；状态优先级 task=`detail.status`→选项状态，subagent=`worker.status`→`agent.status`（RunPanel.tsx:67-75）。时间线：task 用 `timelineToFlowItems(detail.timeline)`，subagent 用 `resolveSubagentFlowItems`（RunPanel.tsx:79-82）。恢复：task `resumeTask`，subagent 对 failed/cancelled 逐个 `resumeThreadAgent`（POST `/v1/threads/{tid}/agents/{aid}/resume`；引擎入口 `server/threads/manager.py:2629-2650`）（RunPanel.tsx:86-105、use-thread-tasks.ts:79-126）。跟随滚动 ResizeObserver + following ref（RunPanel.tsx:106-121）。
- **RunActivity**：纯展示，`groupRunActivity` 把「一条 narration + 其后动作」分组，活跃组默认展开、历史组折叠（RunActivity.tsx:18-63；分组 `lib/run-activity.ts:10-27`）；动作行展开显示 input/output 与批量目标（RunActivity.tsx:65-97、run-activity.ts:50-54）。
- **RunSwitcher（多 run 切换）**：按 `isRunActive` 分 Active/Done 两组，menuitemradio 单选语义，选中即 `onSelect`→`open({threadId, kind, id})`（RunSwitcher.tsx:83-105、RunPanel.tsx:35-37）。跨线程隔离两层：`current = target?.threadId === threadId ? target : null`（RunPanel.tsx:30），切线程自动关 runs tab（`components/Workbench.tsx:636-640`）。选中态持久于 store（run-panel-store.ts:12-17），重开面板读到关闭期间积累的进度（测试 RunPanel.test.ts:61-67）。
- **打开路径**：`openRunPanel` 取 activeThreadId 落 target（run-panel-store.ts:19-22）；调用方 MessageTimeline subagent 块（MessageTimeline.tsx:1776）、OperationContextDock 行（OperationContextDock.tsx:206,252）；Workbench 监听 runRequest 自动开右栏切 runs tab（Workbench.tsx:336-337,629-633）；RunPanel lazy 挂载（WorkbenchRightSidebar.tsx:36,159-161,207-208）。
- **层级切换（嵌套）**：`buildSubagentTreeNodes` 沿 childIds/workers 递归建树（`lib/run-subagent-flow.ts:14-68`），RunPanel 渲染按钮组切换 selectedId（RunPanel.tsx:70-72,154-161）；fanout 根缩进拼接 worker 轨道、单选 worker 只显示该 worker（run-subagent-flow.ts:70-113；测试 run-subagent-flow.test.ts:12-25）。

## 5. 删除 `hooks/use-dock-subagents.ts` 后职责去向

原文件（67 行）职责：从 blocks 抽取子代理列表 + 终态后短暂驻留渐隐（HOLD_MS=8s，FADE_MS=450，TICK_MS=200）。本次改动后职责拆分去向：

1. **「从 blocks 抽取列表」→ 共享纯函数库**：`lib/extract-subagents-from-blocks.ts:102-120`（dock 行数据，标题/激活态 :4-24）与 `lib/extract-tasks-from-blocks.ts:99-108`。OperationContextDock 自行 `useMemo` 调用（OperationContextDock.tsx:341-342,368），RunPanel 复用同一抽取器（RunPanel.tsx:27-29）——数据源从 hook 私有收敛为「chat-store blocks 单一事实 + 共享选择器」；task live 轮询统一收敛到 `useLiveTasks`（use-thread-tasks.ts:263-309）。渐隐驻留逻辑未迁移，随 hook 一并移除。
2. **「点击跳转/详情」→ run-panel-store + 右侧栏 RunPanel**：dock 行点击改 `openRunPanel({kind, id})`（OperationContextDock.tsx:206,252），详情由 RunPanel/RunActivity/RunSwitcher + `useTaskRunDetail` 承接（第 4 节）；选中态由 run-panel-store.ts:13-21 替代原 hook 局部 state。测试同步迁移为 `RunPanel.test.ts`、`run-subagent-flow.test.ts`、`use-task-run-detail.test.ts`、`run-activity.test.ts`、`subagent-mailbox.test.ts`。

## 6. 风险与疑点（附证据）

- **R1 事件队列静默丢弃**：`SubAgentMailboxEvent` 走 `handle.try_emit` 队满即丢（engine/handle.py:163-175；容量 1024 server/threads/models.py:14）。`_reconcile_subagent_cards` docstring 自认会让卡片卡在 running（server/threads/manager.py:4813-4822）。缓解只在 turn 收尾（manager.py:6109-6117）；turn 中途丢的 `progress/tool_call_*` 不可恢复。
- **R2 mailbox 满丢最旧信封**：mailbox.py:199-206 可能丢 `tool_call_started` 只留 `tool_call_completed`。前端回退匹配能吸收「有 id 补挂无 id 行」方向（subagent-mailbox.ts:175-192）；反向「completed 先到、started 后到」会生成两条历史（completed 分支直接追加 :265-277）。
- **R3 跨 turn 的 background 子代理信封被丢弃**：每 turn 开始把 manager 已知 agent 标记 foreign 并丢弃其信封（manager.py:5460-5473、5973-5975；flush 跳过 :6026；reconcile 基于只收非 foreign 的 `seen_subagent_ids`）。`background=True` 的子代理（tools/subagent/types.py:493-496）在后续 turn 完成的终态不会持久化为卡片更新，遗留 running 卡最终被 `finalizeOrphanSubagentBlocks` 强改 `cancelled`（subagent-mailbox.ts:787-803）——后台子代理的 `completed` 可能被 UI 显示为 cancelled，是取舍还是缺陷需产品判断。
- **R4 双轮询窗口不一致**：同一 task 同时被 `useLiveTasks`（2s，use-thread-tasks.ts:299）和 `useTaskRunDetail`（1.5s，use-task-run-detail.ts:29）轮询，终态判定来源不同（list vs detail endpoint）。`useTaskRunDetail` 有 `cancelled` 标志 + `state.id === taskId` 回读校验防错位（use-task-run-detail.ts:22-37）。
- **R5 hydrate 假活跃卡住 running**：`threadStatusLooksActive` 为真时跳过孤儿清理（chat-store.ts:413-415,2129-2132），依赖 `isThreadTurnActive` 确认后清 busy（chat-store.ts:448-480）；确认失败则 stale 卡保留到下次 turn-complete（chat-store.ts:474,1426-1427）。
- **R6 seq=0 合成信封**：reconcile 以 seq=0 重发终态（manager.py:4851），`nextStepId` 对 seq=0 走 max+1 回退（subagent-mailbox.ts:201-213）；无 seq 的 progress 重复只能靠文本去重（:307-330），极端情况可能产生重复 id 的 progress 行（React key 冲突，低概率）。
- **R7 状态词汇不一致**：引擎 `interrupted`（types.py:404）不在 UI `SubagentLifecycle`（subagent-mailbox.ts:6）中，仅 `terminalResidualStatus` 认识它（:830-840）；若某路径把 `interrupted` 直接写入 block.status，fanout 聚合会落入 cancelled 分支（:640-651）而非显式处理。

### SUMMARY
Task/Subagent 生命周期链路：subagent 状态由 `tools/subagent` 的 manager/loop 产生，写入共享进程内 Mailbox（单调 seq、512 上限、满丢旧），由每 Engine 的 SessionActivityCoordinator 每 0.4s 排空并转为 `SubAgentMailboxEvent`，经 threads manager 持久化为带 `subagent_mailbox` 元数据的 status TurnItem 并以 `subagent.mailbox` SSE 事件推送（turn 收尾另有 cancel-orphans/flush/reconcile 三重兜底）；前端 hydrate 与 SSE 双通道汇入同一归约器 `lib/subagent-mailbox.ts`（delegate/fanout 卡、tool_call_id upsert、孤儿清理），状态落在 `chat-store.blocks` 的 subagent 块；task 状态由 `tools/task/manager.py` 后台 worker 迁移（queued→running→completed/failed/canceled/timed_out，含重启恢复），前端靠 2s 列表轮询、1.5s 详情轮询与工具块元数据快照三路呈现。UI 侧 `run-panel-store` 只存「选中哪个 run」，RunPanel/RunActivity/RunSwitcher/use-task-run-detail 全部从 chat-store blocks 与轮询 hook 现读，多 run 切换按 active/done 分组、以 threadId+kind+id 定位并有跨线程守卫；嵌套层级由 run-subagent-flow 建树切换。被删除的 `use-dock-subagents` 职责已拆为共享选择器（extract-*）+ `openRunPanel` 导航 + RunPanel 详情视图（渐隐驻留逻辑未迁移）。主要风险：事件队列与 mailbox 满载静默丢包只靠 turn 收尾 reconcile 兜底、跨 turn 的 background 子代理终态信封被 foreign 过滤丢弃导致可能显示为 cancelled、task 双轮询窗口期不一致、引擎 `interrupted` 与前端状态词汇不一致——每条均附 文件：行号 证据。
