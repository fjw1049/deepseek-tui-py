# 05 · 子 Agent 与协作机制审核

审核基线：2026-09-27 当前工作区，包含已有改动，以及本轮对前四篇问题的修复。覆盖 tools/subagent 的全部 10 个 Python 文件，约 3,990 行；另追踪 Engine、ToolRuntime、Task 工具和持久化 transcript 的关联入口。关联入口的追踪不等于整个 Engine/Server 已审完。

**结论：保留“共享客户端、独立工具循环、结构化进度邮箱”的总体结构；下一步优先修正 Agent 身份与执行次数之间的关系。** 目前同一个 Agent 对象兼任长期会话、一次执行、取消令牌和恢复检查点，取消/恢复、预算、并发限制因而出现相互矛盾的行为。把更多代码拆成文件，无法解决这些问题。

本篇保留审核时的历史问题与离线复现；后续实施状态见 [第五篇修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/05-implemented-fixes.md)，不要把下文的旧行为当作修复后仍存在的问题。原审核阶段只交付审核与离线复现，不把第五篇的新问题混入前四篇修复。前四篇实施状态见 [00 · 修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/00-implemented-fixes.md)。

## 1. 当前设计中应保留的部分

- 子 Agent 不再创建嵌套 Engine；共享客户端、TaskManager 和根审批桥，避免重复连接和独立权限世界。
- 类型工具白名单在真实循环里与调用方子集求交；不能仅靠向模型隐藏工具名称。
- 输入中断优先打断生成/审批，正在执行的工具先结束再记录；比任意取消正在写文件的工具合理。
- 工具结果进入上下文前压缩；LLM stream 有独立 semaphore，工具执行不占该 semaphore。
- transcript 与展示 RunConversation 分开；完成通知包含报告正文与截断后重新读取的指引。
- 本轮已经补上子工具命令/网络策略、never 硬拒绝以及工具前后 Hook；这些属于前四篇修复，不再重复列成未修问题。

| 评价维度 | 判断 | 优先方向 |
|---|---|---|
| 通用性 | 支持不同角色、模型、插件 persona 和结构化输出，但结构化输出的交付链不完整 | 统一结果对象；空值与未完成必须分离 |
| 优雅性 | types/mailbox/completion 的纯逻辑容易理解；manager 和 loop 同时管理太多状态 | 区分 Agent 身份、一次 attempt 和完成结果 |
| 可扩展性 | executor 注入与角色工具集是有效扩展点；所有权和恢复规则分散 | 所有开始执行的入口共用同一个准入与代次校验 |
| 架构合理性 | 每个 Engine 拥有自己的 Manager/Mailbox 合理；持久化却按 workspace 共用文件 | 持久化命名空间与会话所有权一致 |
| 性能 | LLM 并发受控；同步整份持久化与 50ms 轮询仍有明确成本 | 先修正确性，再替换等待方式和测真实 I/O |

## 2. 已确认的问题

### S01 · P1：取消后立即恢复，旧执行器会覆盖新执行状态

位置：[manager.cancel](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:251)、[重新打开终态](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:268)、[driver 取消处理](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:444)。

cancel 先写 CANCELLED，再 task.cancel()，没有等旧 driver 完成。resume 随即把同一个对象改回 RUNNING，替换 cancel_token 和 task。旧 driver 从取消清理返回时，看到对象当前是 RUNNING，又把它写成 CANCELLED。

**复现结果：新 driver 仍活着，get_result 却返回 cancelled。** 这会提前释放并发名额、产生错误完成通知，结果也可能被旧执行覆盖。close 同样没有等待旧 driver：清掉 transcript 后，旧执行的清理仍可能把它重新写出。

建议：

- 最小方案：恢复前在锁外等待旧 driver 退出，锁内重新核验；保持一个 Agent 同时只有一个 driver。
- 更完整方案：每次执行分配 generation/attempt_id，driver 完成时仅能提交自己的代次。取消令牌、结果、完成事件也属于该代次。
- 推荐先保证 join，再增加代次检查作为状态提交约束；仅换一个新的 cancel_token 不足以隔离旧回调。

验收：用可控制的取消清理事件交错 cancel/resume；旧代次不得更改新状态、写新代次 checkpoint 或发送新代次完成通知。

### S02 · P1：达到轮次上限后，“恢复”实际不会继续工作

位置：[恢复累计 steps](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py:549)、[循环条件](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py:753)、[handoff 恢复建议](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/handoff_ledger.py:58)。

目前 DEFAULT_MAX_STEPS=200。恢复从 transcript 取出累计 steps，然后继续比较 steps < 200；耗尽预算的任务再次 resume 会直接越过循环。与此同时 handoff 明确告诉父 Agent 使用 resume 继续。

**复现结果：已耗尽预算的 transcript 恢复后调用模型 0 次，返回空文本，max_steps_reached 仍为 true。** send_input 也在 while 内消费，因而这种状态下追加指令同样不能进入模型。

两种有效契约：

1. 每次用户/父 Agent 明确恢复获得新的 attempt 预算，单独保留 total_steps 做统计。
2. 预算是 Agent 全生命周期硬上限；到顶必须明确拒绝 resume，并让 handoff 停止推荐不可执行的操作。

推荐第一种，因为它符合当前工具描述。不要简单清零唯一的 steps 字段而丢失历史统计；max_steps_reached 也应成为一次执行的结果，而不是永久粘在 Agent 上。

### S03 · P1：恢复与 send_input 重启绕过并发上限

位置：[spawn 准入](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:196)、[send_input](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:288)、[resume](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:316)。

只有 spawn 检查 running_count >= max_agents；其余两个入口直接重开并创建 task。

**复现结果：max_agents=1 时，先保留一个历史终态，再启动一个新 Agent，恢复历史 Agent 后 running_count=2。** LLM semaphore 只能限制流请求数，无法限制活跃工具、内存、审批和正在清理的 driver。

建议把“新建身份”和“申请执行名额”拆开；spawn/resume/send_input 对终态重启必须共用准入方法。达到上限时可明确拒绝，或排队等待；当前产品没有排队状态，先采用明确拒绝最简单。S01 修复前不能只靠 status 统计真实执行数。

### S04 · P1：同工作区的不同 Engine 会相互覆盖持久化注册表

位置：[每 Engine 建 Manager](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:1240)、[默认 state_path](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/runtime.py:143)、[按 workspace 定位文件](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/config/paths.py:206)、[整份保存](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:515)。

内存事件流按 Engine 隔离，但默认注册表路径只含 workspace hash。两个会话打开同一工作区，会各自从内存整份覆盖同一个 JSON；原子 rename 只能避免半文件，不能合并两份状态。

**复现结果：两个 Manager 先读取同一路径，A、B 各 spawn 一次；B 保存后磁盘只剩 B 的 Agent。** A 在内存还运行，不代表重启后能恢复它。

建议优先使用稳定会话/线程 ID 划分注册表，并保留工作区索引支持发现历史。不要使用每次启动变化的 boot_id 作为唯一恢复路径。另一方案是共享记录存储、独立事件订阅，但复杂度明显更高。把 Task 的“整个目录只允许一个调度器”直接套在这里，会阻止同工作区多个正常会话，不推荐。

### S05 · P2：内存淘汰会删除持久化索引，历史无法按 ID 恢复

位置：[终态淘汰](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:492)、[get_result](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:246)。

超过 30 个终态 Agent 后，从 _agents 删除最旧对象，再整份保存。被淘汰对象的 transcript 可能仍在，但没有注册表记录；get_result/resume 只查 _agents，不会从磁盘重新加载。

**复现结果：完成 31 个 Agent 后注册表剩 30 个，第一个 ID 消失。** 已发给父 Agent 的 task_output/resume 指引可能因此失效。

建议让持久化目录承担完整历史，内存只保留缓存；淘汰不得删除记录。若产品希望只保留最近 30 个，应实现明确的归档/保留期限，并同时处理 transcript 与界面提示。不能让缓存容量隐含决定用户数据保留策略。

### S06 · P2：邮箱满时没有保护生命周期事件

位置：[Mailbox.send](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/mailbox.py:189)。

代码注释说丢弃最早的 progress，但实际上无条件 get_nowait()，可能删除 started/completed/failed/token_usage。后来的一条 progress 就能挤掉完成事件。

**复现结果：先写 completed，再写 512 条 progress，completed 消失。** 直接子 Agent 另有 parent_completion_sink，所以不能把它夸大成“父 Agent 必定永远收不到结果”；受影响的是邮箱订阅者的 UI 状态、嵌套关系和统计一致性。

方案比较：

- 分离可靠生命周期流与可合并进度流：语义最清晰，适合后续扩展。
- 在有界缓冲中优先替换同 Agent 的 progress，并保留终态；无法保留时用 gap/resync 标记要求读取权威快照：最小可行改进。
- 无界队列：实现简单，但把数据丢失换成内存失控，不推荐。

这里不能只修改注释。事件丢失策略是消费者必须知道的接口契约。

### S07 · P2：结构化输出从生成到交付没有一致契约

位置：[StructuredOutputTool](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/structured_output.py:62)、[loop 提前退出](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py:1037)、[list_filtered](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:157)、[工具 JSON 转换](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/tools.py:88)。

离线确认三处断点：

1. JSON Schema 允许 null，验证工具返回成功；loop 用 None 同时表示“尚未返回”，最终却报 did not return structured_output。
2. 同一轮 structured_output 后还有兄弟工具调用时，loop break 掉剩余工具，但已把所有 tool_use 写入 transcript。复现留下一个没有 tool_result 的调用，后续恢复有协议风险。
3. get_result().structured 有值，list_agents() 重建快照时丢掉 structured 和 max_steps_reached；_result_to_json 也没有 structured。模型通过 task_output 不能按公共结果类型取到结构化交付物。

此外，强制收尾时 round_tools=[]，却发出“必须调用 structured_output”的提示，两者互相矛盾；这一点为静态确认，未单独跑生成场景。

建议使用独立的 structured_received 标志或专用 sentinel，允许所有合法 JSON 值。结构化终止应给未执行的兄弟工具补上“未执行”结果，保证检查点配对完整。统一 SubAgentResult 到公开 JSON 的转换，列表转换用 dataclasses.replace 修改 from_prior_session，避免手工漏字段。强制结构化收尾时仅保留 structured_output 工具。

当前 AgentTool schema 没有公开 output_schema；这些问题主要影响程序化 SpawnRequest 路径。应明确是公开能力还是内部实验能力，不能因为普通文本测试通过就声称结构化协作闭环已完整。

### S08 · P2：单条坏记录能阻断整个 Manager 初始化

位置：[加载注册表](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:554)。

整份 JSON 没有按记录隔离，嵌套字段直接索引。缺一个 agent_type/assignment/status 字段就抛错；文件截断也会直接中断初始化。

**复现结果：合法 schema_version 加一条缺字段记录，构造 Manager 抛 KeyError。** Engine 创建依赖它，风险不局限于历史记录面板。

建议：先校验外层版本，再逐条验证；损坏条目隔离并记录 ID/原因。未知未来版本应明确拒绝兼容，不能当作空历史覆盖。保存失败目前只 print，建议至少提供日志和 degraded 持久化状态，明确“本次工作无法保证恢复”。

### S09 · P2：统计字段混合了活跃时间、历史时间与最后一轮用量

位置：[snapshot.duration](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/agent.py:100)、[持久化 duration](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py:537)、[最后一轮 usage](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py:819)、[发送 usage](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py:1067)。

静态确认：

- 已完成 Agent 每次 snapshot 仍用“现在 - started_at”；完成越久，显示耗时越长。恢复还会重设起点，累计 steps 与耗时口径不同。
- 邮箱 TOKEN_USAGE 只在退出时发送最后一个有 usage 的轮次，而非多轮总和；异常退出路径不走该发送块。

需要区分两条账：MeteredLLMClient 可能已经记录实际多轮费用，本篇没有据此断言账户总费用必然少算；这里只确认邮箱事件不是完整 run usage。

建议冻结 ended_at，定义 attempt_duration 与累计 duration；usage 用独立累加器并在终态统一发布，明确重试费用和父级账本是否重复累计。对外尽量只保留一种默认耗时口径，额外累计值按需显示。

## 3. 性能与方案横向对比

### 等待：先用真实小负载验证，不据此改成通用事件总线

当前 manager.wait 每 50ms 重新获取锁并生成所有目标的快照。单次 LLM 工作通常数秒，50ms 延迟并不紧急；大量短任务和多个等待者会产生无效轮询。

在临时目录运行 20 组交替试验，假执行器每次 3ms 后返回，双方都验证 completed：

| 方案 | 中位返回耗时 | 最大返回耗时 |
|---|---:|---:|
| 当前 50ms 轮询 | 51.115ms | 51.172ms |
| 等待单个 driver 完成后读取快照 | 3.560ms | 3.685ms |

这是本机合成负载，**不是模型吞吐提升 14 倍，也不是 CPU 基准**。第二方案只演示单目标终态通知，尚未覆盖多目标 any/all、跨代次恢复和历史 interrupted 状态，不能原样替换生产实现。

推荐：完成 S01 的 attempt 身份之后，为每个 attempt 提供完成 Event/Future；wait 在其上组合 any/all，再读取权威快照。这样响应快，而且不把等待和结果存储绑在某个 asyncio.Task 的内部指针上。

### 存储：存在同步整份写，但本篇不虚构瓶颈规模

Manager 每次转换状态重写整个 registry，且更新所有记录的 duration/updated_at；loop 每个完整轮次同步保存全部 transcript。两个路径都位于事件循环上。恢复会使会话历史继续增长，30 个终态缓存上限不能限制单个 transcript 大小。

推荐顺序：

1. 先修 S04/S05 的所有权与历史正确性。
2. 将单 Agent/attempt 记录独立保存；纯进度可合并，关键状态转换必须明确确认。
3. 用串行写入者或等待完成的线程卸载，避免同一路径并发覆盖。
4. 有真实历史规模和查询需求时再考虑 SQLite；不建议现在为十个并发 Agent 引入外部消息队列或分布式调度系统。

## 4. 逐文件审核建议

| 文件 | 现有价值 | 建议 |
|---|---|---|
| [__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/__init__.py) | 对外统一导出、保留兼容入口 | 保持薄层；暂不因导出数多改目录。避免生产依赖测试 stub |
| [agent.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/agent.py) | 集中单 Agent 状态和快照 | 分离 attempt 的 task/token/起止时间；SubAgentExecutor 从裸 Callable 改为明确签名。快照不应暴露可变 assignment 引用 |
| [manager.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/manager.py) | 管理生命周期并注入 executor，适合离线测试 | 优先 S01/S03/S04/S05；让开始执行、提交终态成为两个明确入口。不要继续在各公开方法复制状态更新 |
| [loop.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py) | 无嵌套 Engine，输入中断、错误预算、压缩和工具执行比较完整 | 先统一 attempt 预算与输出状态；再提取有明确数据输入输出的轮次状态，不需要另造通用 workflow 框架 |
| [mailbox.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/mailbox.py) | frozen envelope、单调序号、有界缓冲 | 解决 S06；增加可观察的丢弃/重同步信息。不是所有事件都允许丢弃 |
| [completion.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/completion.py) | 通知载荷有预算，完整报告减少父级重复拉取 | SUMMARY 字符串是呈现约定，不宜作为唯一完成事实；逐步改为显式 outcome，再生成报告。数字“1”可以通过内容判据，不代表任务真的完成 |
| [handoff_ledger.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/handoff_ledger.py) | 纯分类与展示、XML escape、单成功任务不冗余 | 保留；修 S02 后再统一 resumable 能力判断，不能仅按“不是完成”就推荐 resume |
| [structured_output.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/structured_output.py) | JSON Schema 验证是合适的外部契约 | 修 S07；初始化时检查 schema，区分模型输出不合规与 schema 配置错误。对象 schema 转换目前省略部分约束/definitions，应验证 $ref 等复杂 schema |
| [tools.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/tools.py) | 统一 agent 工具，计划模式用能力子集，兼容旧参数 | 统一序列化，动作互斥尽量在输入校验表达；插件 allowed_tools=[] 当前被当作未指定，建议区分 None 与空集。外层取消 process wait 时需统一回收等待协程 |
| [types.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/types.py) | 角色白名单、模型选择与输出预算集中可查 | 保留角色策略；长期可把长提示词移至资源文件。不要指示模型把任意绝对路径截成文件名，这可能改变用户目标，应让路径解析器明确拒绝或映射 |

后两行提到的复杂 schema、空 allowlist、process wait 清理及路径提示属于静态改进建议，未计入上面的离线复现结论。没有因此自动修改生产代码。

还有一项需要明确的协作契约：当前只保留 spawn_depth，parent_agent_id 主要进入邮箱，取消某个中间 Agent 没有明确的后代级联管理。允许嵌套 Agent 长期运行时，应保存父子关系，并定义“停止一个分支”与“只停止当前执行”两种行为。授权范围在嵌套 spawn 时也应明确是否必须继续收窄，不能只依赖各层提示词。

## 5. 验证材料与边界

- [subagent_probe.py](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/subagent_probe.py)：10 项观察断言，确认缺陷特征，**不是修复后的验收测试**。
- [实际复现结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/subagent-probe-results.json)。
- [subagent_compare.py](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/subagent_compare.py) 与 [实际对比结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/subagent-compare-results.json)。
- 复现命令：在仓库根目录使用 PYTHONPATH=src .venv/bin/python，后接相应脚本路径。全部使用临时目录、假执行器或假模型；不调用真实模型或消息渠道。
- 既有子 Agent 回归与前四篇修复的最终测试结果统一记录在 00-implemented-fixes.md。
- 未做真实多模型、Windows、断电恢复、长时间后台会话压力测试。静态风险与离线确认已分开标注。

建议实施顺序：**先 S01/S02/S03，再 S04/S05，接着 S07/S06/S08，最后修统计和等待成本。** 第一批先定义 attempt，而不是同时重写 Manager、工具 API 和整个 Engine。

下一篇：Engine 与工具调度。
