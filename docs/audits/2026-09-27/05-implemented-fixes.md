# 第五篇修复记录 · 子 Agent 与协作机制

实施日期：2026-09-27。基于包含用户已有改动的当前工作区；没有提交或回滚其他工作。原始问题、旧探针结果保留在 [第五篇审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/05-subagents.md)，本文件说明现在实际落地的行为。

## 已落地的修复

| 编号 | 实际改变 | 验证 |
|---|---|---|
| S01 取消/恢复竞态 | cancel 等旧 driver 清理结束才返回；清理期间仍占并发名额，resume 不允许重开。close 先 join 再删除记录和 transcript；启动前取消也发送一次终态和父级通知 | 可控清理事件交错；启动前取消；旧 driver 未退出时不能恢复 |
| S02 恢复预算耗尽 | 每次显式恢复获得新的 200 轮预算；steps 保留累计值。恢复重新开放工具，重置本次 max_steps_reached | 从累计 200 轮的检查点恢复，实际调用模型并到达 201 轮 |
| S03 准入不一致 | spawn、resume、send_input 重开终态共用并发准入；shutdown 后停止准入 | max_agents=1 时两个恢复入口均拒绝第二个活跃执行 |
| S04 注册表相互覆盖 | 新增 AgentStore，按 Agent 原子保存独立记录；按 Agent 获取本地执行锁。Server 用稳定 thread.id、持久化 Task 用 task.id 划分子 Agent 状态路径 | 两个 Manager 同时持有不同 Agent，磁盘保留两个记录；旁观 Manager 不能恢复或关闭仍被执行者持锁的 ID |
| S05 缓存淘汰丢历史 | 30 个终态上限只裁剪活跃句柄缓存；完整记录保留，get_result/resume 可重新装载。known_agent_ids 包含已淘汰历史 | 完成 31 个 Agent，首个结果、结构化数据和重启后的 31 条历史仍存在 |
| S06 邮箱丢终态 | 优先淘汰 progress/tool-call 事件；纯进度不能挤掉生命周期事件。关键事件也饱和时记录 dropped_events/resync，drain 追加 Manager 权威生命周期快照 | 完成事件之后写 512 条进度仍保留完成；关键事件饱和后重建真实 Agent 终态 |
| S07 结构化交付 | 新增 structured_received 区分 JSON null 与尚未交付；列表和公共结果 JSON 保留字段；父级完成消息包含结构化结果。结构化工具提前结束时补齐兄弟调用的“未执行”结果；强制收尾保留 structured_output 工具；构造时验证 Schema | null/object 完成、公共结果转换、未执行兄弟调用配对、历史恢复 |
| S08 坏记录与诊断 | 单条坏 JSON/字段异常被隔离并记录日志；未知版本明确失败；持久化 I/O 错误通过 storage_error 暴露，替代 print | 坏记录旁边的好记录仍恢复；未来 schema 版本拒绝 |
| S09 耗时与用量 | ended_at 冻结终态耗时；duration_ms 表示最近一次执行的耗时，steps_taken 仍为累计步数。邮箱用量累加每轮返回的 Usage，finally 在失败/取消路径也发布已有累计值 | 时间推进不改变终态 duration；两轮 Usage 后第三轮异常，仍得到前两轮总和 |

实现入口：[Manager](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py)、[AgentStore](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/store.py)、[子循环](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py)、[Mailbox](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/mailbox.py)。

## 方案取舍

本次采用“单 Agent 同时只有一个 driver，恢复前必须 join”。没有引入完整 attempt 数据库或通用事件总线。该方案直接消除已经复现的旧执行覆盖问题，也使并发名额包含清理阶段。代价是执行器如果拒绝取消并永不退出，cancel/close 会继续等待；不能一边允许旧代码继续写检查点，一边宣称资源已经释放。

状态存储采用独立记录与本地执行锁，不重写整个共享 JSON，也不要求整个 workspace 只能有一个 Manager。锁复用 TaskStoreLock 的平台实现，但粒度是单个 Agent。旧注册表只读，新记录优先，关闭写 tombstone 防止重新加载旧注册表中的同名记录。Server 的新线程命名空间不会自动把工作区旧记录复制给每一个线程，因为旧记录没有可靠的线程归属。

这不是一个跨进程实时同步数据库：已打开 Manager 的历史视图不会自动订阅别的 Manager 的修改。执行句柄缓存有界，但历史原始记录仍保留在内存；历史规模很大时，应进一步做按需索引。落盘和 transcript 写入仍是同步操作，本次没有无证据地引入后台写入队列。

## 等待机制与最小对比

wait 改为状态变化事件唤醒，保持 any/all/first 和超时语义。每次状态变化唤醒旧事件并换新事件，等待者在同一锁内捕获快照与事件，避免多个等待者互相 clear 导致丢唤醒。新增一个专门控制事件注册时序的回归测试。

20 组交替试验，假执行器 3ms，结果都核验 completed：

| 方案 | 中位返回耗时 |
|---|---:|
| 修复前 50ms 轮询，历史基线 | 51.115ms |
| 本次事件等待 | 3.854ms |
| 本次单 driver join 对照 | 3.862ms |

历史与本次测量发生在不同批次，不能视为严格吞吐基准。测试没有真实网络、模型或重磁盘负载，只说明短任务等待不再被固定轮询周期拖延。

[对比脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/subagent_compare_after.py) · [数据](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/subagent-compare-after-results.json)

## 验证与边界

新增 [14 项定向回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_subagent_audit_fixes.py)，并更新旧 schema 恢复测试的夹具，使其真正提供旧格式输入。相关子 Agent、Task、审批桥、路径隔离与 Engine 测试共 **252 项通过，1 项排除**；定向回归包含在这个数字中，不重复累加。Ruff 的 F 类检查通过。

排除的是此前已存在的 `test_hidden_internal_turn_carries_its_own_provenance[goal_continuation]`：测试要求没有活跃 Goal 时仍执行隐藏续跑，当前 Goal 代码明确拒绝。本次没有修改 Goal 契约来迁就该测试。没有运行真实模型或系统沙箱集成测试。

仍需明确的边界：

- 邮箱的快照补偿恢复生命周期状态，不是所有事件的可靠重放；极端关键事件饱和时，逐次 token_usage 和工具明细不能由状态快照重建。dropped_events 可以观察丢弃。Engine 下游还有独立的丢事件问题，见第六篇 E03。
- 邮箱累计的是子循环每轮拿到的 Usage；流式层内部重试、没有返回 Usage 的失败请求，不因此成为完整计费账单。计费以 MeteredLLMClient 为另一条独立链路；跨回合归属问题见第六篇 E05。
- 结构化输出仍主要服务程序化 SpawnRequest，未把 output_schema 新增为 AgentTool 的公开参数。本次修复已确认的交付断点，不宣称覆盖任意复杂 JSON Schema 方言/引用组合。
- 没有扩展为取消某个子 Agent 时自动取消它所有后代；根会话关闭仍由 Manager 统一回收。此类新增产品语义应单独定义。
