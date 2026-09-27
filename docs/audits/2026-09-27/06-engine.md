# 06 · Engine 与工具调度审核（上篇）

**实施状态：E01—E08 已完成本轮修复，见 [修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-implemented-fixes.md)；后续上下文审核与优化见 [第六篇下篇](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-context.md)。以下问题描述、行号和探针结果保留为修复前历史基线，不代表当前代码仍有相同缺陷。**

原审核基线：2026-09-27 当前工作区，包含第五篇修复和用户已有改动。本篇最初审核回合调度、工具批次、事件交付、资源生命周期与用量归属，仅交付分析与复现；后续实施状态以上述修复记录为准。

**结论：保留 Engine → TurnLoop → ToolRegistry 的分层，优先修复状态与生命周期契约，再做局部拆分。** 当前主要风险不是函数长，而是同一回合的错误事件、返回结果、后台任务、用量账本和工具缓存可以给出互相矛盾的事实。

原索引中的 Engine 体系含 24 个 Python 文件，约 1.53 万行。为了按逻辑审核，本篇列出其中 17 个文件的回合/调度相关审查范围；上下文容量、压缩、提示词等 7 个文件以及下表注明的同文件剩余职责留给下篇。**不把这次调用链追踪写成 24 个文件全部审完。**

## 1. 应保留的设计

- Engine 管多轮和会话，TurnLoop 管一次流式采样，ToolRegistry 管工具协议与参数校验；边界方向合理。
- 工具执行核对当前请求实际携带的 catalog，避免异步发现工具后扩大本轮执行权限。
- 并行入口要求整个批次只读、支持并行且无需交互/审批；重复指纹回退串行。权限仍在实际执行入口复核。
- 串行与并行共用 `_finish_tool_result`，可以统一事件、上下文裁剪与副作用记账。
- 工具元数据/Schema 校验器缓存、稳定工具目录顺序、工具结果 spillover 有实际用途，不应为了拆分而删除。
- 子 Agent 复用客户端而不递归创建 Engine；第五篇已经修复 Manager 内部的执行与恢复边界。

| 维度 | 判断 | 推荐方向 |
|---|---|---|
| 通用性 | 工具接口与结果类型可复用，但“只读/可并行/可复用结果”尚未完全区分 | 先定义每一种能力的语义 |
| 优雅性 | mixin 减少单文件体积，却通过 self 共享大量未声明状态 | 提取少量有明确输入输出的协作对象 |
| 可扩展性 | 新增工具相对容易，新增终止条件会继续扩大 core 分支 | 统一回合结果和终止原因，避免独立布尔门互相覆盖 |
| 架构合理性 | 消息队列、运行任务、资源所有权与账本生命周期没有完全对齐 | 明确每种对象属于会话、回合还是后台执行 |
| 性能 | 只读工具确实并行执行，但结果可见性被最慢工具拖住 | 分离“完成即发布”和“按调用顺序提交上下文” |

## 2. 已确认的问题

### E01 · P1：第二条消息能阻塞操作循环，使排队取消无法被处理

位置：[Engine.run](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1807)。

已有 turn 正在运行时，操作循环收到第二个 SendMessageOp，会直接 `await turn_task`。这段等待期间不再读取操作队列，随后到达的 CancelRequestOp 无法执行 `turn_task.cancel()`。

**离线复现：** 第一回合等待一个可取消 Event；发送第二条消息，再通过公共 send_op 发送取消。取消仍留在队列，第一回合没有退出。探针最后主动取消 runner 回收任务。

这不是说所有停止按钮必然失效：`handle.cancel()` 会提前设置合作式 cancel_event，主动检查该标志的工作仍可停。但它无法替代操作循环的硬取消职责，尤其是等待外部 I/O 或其他不检查该标志的 await。

方案：

1. 操作循环维护待运行消息 deque；只在空闲时启动下一条，忙碌时继续消费取消。
2. 拆成消息与控制两条队列，控制信号优先；语义清楚，但需要统一关闭与公平性。

推荐方案 1 作为最小修复，保留当前队列 API。验收应包含 send/send/cancel、第一回合异常、排队消息顺序以及一次取消只影响目标回合。

### E02 · P1：停止 Engine 时遗留 next_op 任务，随后可能吞消息

位置：[创建 op_wait](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1775)、[run finally](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1824)。

正常竞争结束时，代码会回收没有完成的 op_wait；但 runner 自身在 asyncio.wait 处被取消时，finally 只清理 turn_task 和 coordinator，没有清理 op_wait。

**离线复现：** runner 退出后仍有 1 个名为 engine-next-op 的任务；向同一个 handle 发送新消息，该遗留任务取走消息，队列变空。即使产品没有重启同一个 handle 的路径，它也是一个没有所有者的后台等待任务。

建议把 op_wait 作为 run 作用域资源，在所有退出路径 cancel 并 await；不要仅依赖正常分支。TaskGroup 可作为后续方案，但这个缺口只需一个明确的 finally 即可修复。不要为它改写整个引擎。

### E03 · P2：邮箱之后仍有丢完成事件的通道，活动快照也不会归零

位置：[EngineHandle.try_emit](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/handle.py:164)、[邮箱转发](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/cycle.py:479)、[活动快照](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/cycle.py:455)。

Engine 事件队列容量 4096。coordinator 先从 Mailbox drain，再调用 try_emit；队列满时返回 False，但调用方忽略结果，也不恢复邮箱内容或安排快照重同步。

**离线复现：** 填满 Engine 队列后向邮箱写 completed，运行一次 coordinator；最终 Engine 没有 completed，Mailbox 也已空。第五篇保护了 Mailbox 内部终态，但不能自动保护下游这一次转移。父级独立完成通知仍可能收到结果，不能据此推断父 Agent 永久卡死。

另一个边界：`_emit_activity_snapshot` 在运行数从 1 变成 0 时先更新 last 值，再直接 return；订阅该事件的消费者只看到 `[1]`。发送失败时也已更新 last，下一次数量不变就不重发。

推荐：关键事件要么确认交付，要么显式标记需要权威快照重同步；进度允许合并。活动快照必须发送非零→零，且仅在成功入队后更新已发送值。单纯把 try_emit 全部换成 await emit，会把满队列问题变成关闭阻塞，不是完整方案。UI 最终一致可选快照重建；精确逐事件审计才需要持久化 outbox。

### E04 · P1：同批参数去重改变写操作语义，也能返回写入前的旧读取结果

位置：[ToolCallDeduplicator.classify](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/tool_dedup.py:134)、[串行调用去重](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:242)。

去重键只有 name + canonical args，同批所有工具都可以复用第一次结果。它没有工具副作用语义，也不会在中间写操作后失效。

**离线复现：**

- 两次相同 exec_shell 参数，第二次被判为 reuse。探针不执行 shell，只验证真实分类器；如果命令是增量写入，两次调用只会执行一次。
- 同批 `read_file(x) → write_file(x, new) → read_file(x)`，最后一次返回缓存中的 old。第二次读取本应验证刚完成的写入。

“只读”也不自动等于“本批次任意位置都可缓存”：task_output、进程状态、网络读取等结果会随时间变化。当前实现已对带图片的结果跳过去重，本篇不再声称图片一定丢失。

推荐最小方案：默认不复用有副作用或动态状态工具；允许复用的读取只在没有变更操作的连续区间内生效。若以后确实需要更细粒度缓存，再增加显式 cacheable/失效依赖。跨轮防死循环提醒可以保留，但应与同批结果缓存拆成两个独立策略。

验收：重复增量写执行两次；read/write/read 得到新内容；连续纯读取仍可复用；失败后重试、Hook 改变状态、动态状态查询不被错误缓存。

### E05 · P2：共享客户端的回合账本无法稳定归属跨回合后台用量

位置：[回合开始 reset](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:2247)、[TurnUsageLedger](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/usage_ledger.py:37)、[MeteredLLMClient](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/base.py:178)。

子 Agent 与 Engine 共享 metered client 和同一个可变 ledger。新的回合通过 clear 清空它；客户端在请求结束的 finally 把 Usage 写入当前这个对象，没有捕获所属 turn_id 或执行 ID。

**离线复现：** 在旧回合启动一个延迟的子请求，旧回合取总额为 0；reset 表示下一回合开始，然后释放子请求。3 个输出 token 被写入新回合账本。source=subagent 保留了来源种类，却没有保留归属回合。

如果旧回合结束后、下个 reset 前完成，统计是否被补记还依赖上层另一次读取；本篇不把它扩大成所有账户用量必然少算。已经确定的是“每回合账本”的归属契约不成立，Goal 当前回合预算也可能被别的回合子请求影响，需要沿实际产品定义复核。

方案比较：

- 请求开始时捕获不可变 usage_scope（session_id/turn_id/agent_id），完成后写入对应账本；后台费用可更新会话总账。推荐。
- 子 Agent 单独记账，父级按完成结果一次汇总；实现简单，但容易与共享 metering 重复计算，也会推迟长任务的费用可见性。
- 禁止后台跨回合：改变既有能力，不建议用它回避归属设计。

### E06 · P1：资源装配失败没有统一回滚，关闭中的一次异常会阻断其余清理

位置：[ToolRuntime 工厂](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/runtime.py:167)、[ToolRuntime.shutdown](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/runtime.py:88)、[Engine.create](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1116)、[shutdown_session](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1414)。

工厂先启动 TaskManager，再装配其他依赖。后面的子 Agent 记录加载、必需 MCP 启动、registry 或配置检查失败时，没有逆序释放已启动资源的统一路径。第五篇开始明确拒绝未来状态版本，因此这也有一个现实触发条件。Engine 外层在 runtime 已建好以后仍有技能发现、子运行时装配等可能失败的步骤。

shutdown 又按顺序直接 await；子 Manager 的一次异常会让 TaskManager、MCP、LSP 等后续清理不执行。Engine 的 session hook、客户端关闭也有类似分支。

**故障注入复现：** fake TaskManager.start 被调用一次，随后让 build_subagent_manager 抛错，TaskManager.shutdown 调用次数是 0。另让子 Manager.shutdown 抛错，后续 TaskManager.shutdown 次数同样是 0。这里验证的是清理契约，不伪称测到了真实进程或连接泄漏数量。

推荐 AsyncExitStack 或等价的明确清理栈：每成功获取一个“自有”资源立即登记释放；构造成功后才转移所有权。关闭时尝试每个资源、最后汇总错误，同时保留取消语义；借用的共享 runtime/client/MCP 不应被误关。优先沿已有 owns_* 标志完善，不必创建新的依赖注入框架。

### E07 · P1：工具轮次耗尽，错误事件与最终成功结果相矛盾

位置：[循环尾部返回](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:3442)、[TurnResult 默认值](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/turn.py:171)。

超出轮次上限后发出 `Tool round-trip limit exceeded`，然后构造没有 outcome 的 TurnResult。默认 outcome=SUCCESS，error_message=None，tool_round_count=0。上层又据 outcome 设置 TurnCompleteEvent.success、Goal 回合结束状态。

**离线复现：** 配置 max_tool_round_trips=0，假模型请求一个工具，工具返回成功；循环耗尽后同时得到错误事件、returned_outcome=success 和 returned_tool_round_count=0。不是模型调用失败，而是达到资源上限的结束结果被错误标记。

建议显式返回 FAILED 或独立的预算耗尽结果，保留已执行轮数和可恢复的部分结果。最小补丁只需修正循环尾部构造；后续再统一 Stop hook/checklist/子任务等待等停止门的原因模型。不要把“产生过错误事件”作为推断终态的唯一办法。

### E08 · P2：并行工具的快速结果要等最慢工具完成才能发布

位置：[_execute_tools_parallel](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:598)。

execute 确实并行，但 gather 全部完成以后，才按输入顺序逐个进入 `_finish_tool_result`。一个慢网络读取会延迟已完成文件读取的结果事件、后处理和反馈。不是批次根本没有并行，也不是总耗时等于各工具耗时相加。

20 组交替试验，两个假只读工具分别等待 40ms 与 3ms。当前侧调用真实 `_execute_tools_parallel`，只替换执行器与结果处理器；原型侧完成时立即通知、gather 仍按原顺序返回。两侧都核验最终结果顺序。

| 方案 | 快结果可见中位时间 | 整批结束中位时间 |
|---|---:|---:|
| 当前 gather 后发布 | 41.179ms | 41.181ms |
| 完成即通知的最小原型 | 3.474ms | 41.133ms |

原型只说明可见性延迟可改善，**没有提高批次总吞吐，也未验证真实 Hook、LSP、Goal 记账的并发安全**。推荐先把无副作用的结果通知与有顺序要求的上下文提交分开；如果全部 `_finish_tool_result` 并行，会把共享状态竞争带进来。并发上限/分块执行可另外考虑，但本次没有证明实际工具数量已经导致资源瓶颈。

## 3. 按模块给建议

“已审”在此指表中写明的职责，不延伸到同文件未列出的另一套功能。

| 文件/模块 | 本篇审查范围与建议 |
|---|---|
| engine/__init__.py、orchestrator/__init__.py | 公共导出层。保持薄封装，不因实现拆分而改调用方导入路径 |
| orchestrator/core.py | 回合操作循环、创建/关闭、工具多轮尾部、用量生命周期：E01/E02/E05/E06/E07。先修契约，再提取 TurnRunner 与资源装配；插件发现、上下文容量和 Goal 内部契约尚未在本篇完整审完 |
| engine/handle.py | 命令/事件通道：E01/E03。区分控制信号与排队消息；说明队列交付保证。无界 op/steer 队列是需要按真实流量评估的风险，本次没有负载证据，不以此强行设定容量 |
| engine/events.py | 检查事件类型与终态消费契约。类型拆分清楚；普通 frozen dataclass 并不深冻结 metadata，约定消费侧不修改即可，暂不做全面深复制 |
| engine/cycle.py | 只审 SessionActivityCoordinator：E03。cycle 归档/种子消息属于下篇上下文职责，尚未审完 |
| engine/turn.py | 单次采样、重试和 TurnResult 契约：E07；保留显式 outcome。中断重采样后旧可见文本不撤回，需在流式/UI 篇核验是否有明确替换协议；不能仅凭模型最终消息正确就断言界面正确 |
| orchestrator/tooling.py | 串/并行工具调度、统一结果处理、审批和 Hook 入口：E04/E08。保留公共后处理路径，分离通知与上下文提交。新增工具不要继续扩张按名称判断的大分支；已有 plan/用户输入控制工具可逐步建立专用执行适配层 |
| engine/tool_dedup.py | E04。纯逻辑可测试，应保留；把防重复循环和结果缓存拆开，后者默认保守 |
| engine/dispatch.py | 审查并行判定、Task→Engine 适配边界，结合第四篇的实际执行测试。文件同时容纳持久化任务执行与 JSON 参数修复，职责过杂；可以按调用方向拆成纯策略/执行适配/参数修复。文本修复器的全部容错规则留给协议篇 |
| engine/tools.py | 审查目录合并与可执行目录边界。native 优先、消除 MCP 同名条目合理；排序会原地修改传入列表，推荐纯函数语义。文本工具调用 fallback 的全部解析组合留给协议篇，当前不列为完整审核 |
| tools/registry.py | 注册、能力、校验、执行、缓存：保持 ToolSpec。坏 Schema 时日志后跳过校验属于明确的 fail-open 取舍，建议注册时失败或隔离坏工具；不能把额外属性兼容当作关闭整份校验的理由。to_api_tools 直接暴露可变缓存，建议约定只读或在边界复制；尚未复现具体调用者污染，故不列成已确认事故 |
| tools/runtime.py | 装配与销毁：E06。工厂应返回成功才移交自有资源；借用资源单独标记。没有 API key 时会退化成成功 stub：至少应让运行结果清楚区分 synthetic；这属于产品/测试模式边界，不能仅从日志判断是真实执行。spillover 具体策略留给状态/上下文篇 |
| engine/usage_ledger.py | E05。聚合计算容易测试，保留；记录所属请求/回合，让 reset 只更换视图或活动 scope，而非破坏后台写入归属 |
| orchestrator/lifecycle.py | Hook 上下文构造与 LSP 结果插入。保留统一适配；单文件 diagnostics 失败隔离合理。session_start/end 在执行前置 marker，失败后不会重试：应明确是 at-most-once 尝试，不应称可靠交付；没有本篇独立故障注入 |
| orchestrator/helpers.py | focus 前缀与白名单核对。纯 helper 保留，明确 focus 是目录选择而非权限机制；真实审批仍由执行入口兜底。插件匹配/别名细节会在插件篇继续审核 |
| engine/completion_requirement.py | 小型终止门纯函数。当前职责清晰，无必要重构；其上层所有停止原因如何统一由 E07 驱动 |

下篇继续：capacity.py、context.py、context_pressure.py、orchestrator/maintenance.py、prefix_probe.py、prompts.py、reminders.py，以及 cycle.py 的归档部分。它们涉及预算估算、压缩后请求保真、工作集、缓存前缀和提示词寿命，应放在同一逻辑体系内审核。

## 4. 验证材料与实施顺序

[离线探针](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/engine_probe.py) · [探针结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/engine-probe-results.json)

[并行方案对比脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/engine_compare.py) · [对比结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/engine-compare-results.json)

探针不请求模型、不执行 shell 工具、不连接 MCP；使用临时目录与假依赖。断言是“复现当前问题”，不是要求产品长期保留这些行为。生产修复后应转成正向回归。复现命令从仓库根运行，`PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/engine_probe.py`；建议同时把 DEEPSEEK_HOME、CLAUDE_PLUGINS_DIR 指向临时目录，与本次运行隔离方式一致。

第五篇修复及相关 Engine 测试合计 252 项通过、1 项已有 Goal 契约测试排除；此数字证明已运行场景未回归，不能抵消本篇新探针揭示的缺口。具体排除原因见 [第五篇修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/05-implemented-fixes.md)。

推荐实施顺序：

1. **E01/E02/E07**：先让取消、退出和终态一致；改动集中，使用可控 Event 验收。
2. **E04/E06**：保证工具调用语义与资源所有权；不要夹带纯格式调整。
3. **E03/E05**：确定事件最终一致策略和用量归属语义，再贯通 Server/UI 断言。
4. **E08 与局部模块拆分**：在正确性稳定后改善可见延迟和职责边界；不需要先建设通用调度框架。
