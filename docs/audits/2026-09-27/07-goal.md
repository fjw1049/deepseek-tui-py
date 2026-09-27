# 07 · Goal 模式、目标队列与完成判定审核

**后续状态：已完成本轮局部优化，详见 [实施记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-implemented-fixes.md)。G01 为局部加固，G08 为契约澄清，不代表通用语义验收或三轮阻塞已获得硬保证。下文问题、行号和探针数据保留为修复前基线。[第八篇状态与媒体审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/08-state-media.md) 已交付。**

基线：2026-09-27 当前未提交工作区，包含此前 Goal 升级与第六篇上下文优化。审核 `goal/` 全部 10 个 Python 文件（原台账 9 个，加新增 workspace.py），并追踪 Engine 工具记账、续跑与 Server 晋升入口；不代表 Server、TUI 或 Workbench 全部审完。

**结论：保留状态、服务、工具适配三层；下一步优先完善证据时效与恢复事务，不建议继续堆叠完成提示词。** 已有完成审核字段、用户控制边界和确定性回归，比旧报告中的实现完整。但“引用有效工具记录”仍不同于“目标确实完成”，不能把 complete 状态当作外部验收真值。

本篇只交付审核与离线取证，没有修改 Goal 产品行为。历史报告 [Goal 第二轮审计](/Users/fjw/Desktop/deepseek-tui-py-main/docs/goal-mode-production-audit-2026-09-27.md) 已标为升级前基线；下面按当前代码重新判断，不直接搬用旧缺陷。

## 1. 已有设计与旧问题复核

| 维度 | 当前优点 | 主要改进方向 |
|---|---|---|
| 通用性 | GoalService 不依赖 UI；命令解析可供 HTTP/TUI 共用；角色和状态显式建模 | 代码、研究、文字交付需要不同证据类型，不能都归结为成功工具 ID |
| 优雅性 | state 负责状态/计时，service 负责业务，tools 负责协议适配 | service 同时承担证据保留、完成验收与续跑策略；先把完成检查提为无副作用函数，避免过早拆成多套服务 |
| 可扩展性 | requirements 与 checklist 分开，预算类型统一 | 补持久化版本、晋升事务和验收器接口；不要为每种任务增加独立状态布尔值 |
| 架构合理性 | 用户恢复/改预算受到运行时限制，旧回合有 goal_id/control_epoch 检查 | 目标完成与队列晋升尚无完整持久化提交边界；快照并非深度隔离 |
| 性能 | 长任务可跨回合，工作区内容指纹避免只看工具能力标签 | 每次工具前后全量扫描仓库；未解决失败记录可无限累积 |

复核已修复或已有明确保护的旧问题：

- 模型恢复 active、调用旧预算工具会被服务拒绝；预算工具不再出现在默认工具列表。
- 完成入口集中在 mark_complete → validate_completion；必须提交逐 requirement 的检查、有效证据、失败处理和取消步骤说明。
- 未完成 checklist 不能直接通过删除消失；证据版本、同签名较新结果、后台任务未完成等有检查。
- 动态时间预算、旧回合结果、外部内容改动和运行时异常形状已有回归，不能再写成原先的确定缺陷。
- 恢复 active → paused、未完成目标提升 work_revision、不可读工作区拒绝完成，是应保留的保守行为。

上述检查解决机械一致性，不证明任意任务的验收语义正确。

## 2. 当前发现

### G01 · P1：完成审核仍可使用无关成功记录覆盖所有需求

位置：[service.validate_completion](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:322)、[UpdateGoal](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/tools.py:268)。

真实 GoalService 探针创建“修复 checkout 并通过回归测试”，只写入一条合成的成功 pwd 记录，然后为每个 requirement 填写非空 explanation 并引用该记录，mark_complete 接受，结果为 complete。与旧版“缺审核也能过”不同：现在需要完整填写结构，但解释文字仍是调用者自报，记录没有足以核验需求关联的结果事实。

证据等级：服务层离线复现；没有执行真实 pwd、测试或模型轨迹，不能推算实际误完成率。Tool 入口也没有额外的语义审核器；正常 Engine 的稳定工作区检查不会让 pwd 自动变成有效业务测试。

方案比较：

1. 强化提示词：成本低，但不改变本探针成立的边界。
2. 为可以明确验收的任务保存检查结果和产物引用，按 requirement 运行专门校验；文字/研究允许文档、来源及人工判定。**推荐先做这类可核验子集**，不要强迫所有目标必须运行 shell。
3. 独立模型评审：覆盖面大，但有成本、相关性错误和自证风险；适合作为补充，不能当绝对真值。

验收：测试失败 + 无关读取、产物缺失 + pwd、文字任务合法交付三类正反例；必须用 Goal 状态以外的标准核验。预算耗尽不得冒充完成。

### G02 · P1：工作区指纹忽略执行权限，旧验证可在行为改变后继续有效

位置：[workspace.workspace_digest](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/workspace.py:23)。

函数哈希路径、文件内容、链接目标和删除状态，但没有 mode。临时目录中的 script.sh 从 0644 改成 0755，指纹完全相同；内容未变却已改变可执行行为。Goal 的 work_revision 依赖指纹变化，因而“内容相同”被扩大成“验证仍有效”。

推荐最小修复：纳入文件类型及语义相关 mode（至少可执行位），保持跨平台规则明确；不要把访问时间等无关元数据纳入。Git 工作区可比较带 mode 的清单，但仍要覆盖工作树尚未入索引的 chmod。新增可执行位、删除、符号链接、同内容不同 mode 的回归。

边界：Git 忽略产物、外部链接目标、依赖环境不在当前指纹保证内；对这些产物需显式验收范围。即使加入 mode，目录扫描也不是文件系统事务快照。

### G03 · P2：冻结的快照仍与内部审核字典共享嵌套对象

位置：[state.snapshot](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/state.py:59)、[types.GoalSnapshot](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/types.py:118)、[persist.state_to_dict](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/persist.py:17)。

completion_audit 只浅拷贝。探针修改 snapshot.completion_audit['checks'][0]['explanation']，再次读取服务快照时内部内容已被改写。dump 也直接暴露该字典。frozen dataclass 限制字段赋值，不能防止嵌套可变对象变化。

推荐在快照、dump 边界深拷贝这份 JSON 数据；比把整个领域模型改成递归 immutable 类型更小。验收应分别修改快照和序列化结果，并验证服务的证据/完成记录不变。当前没有证据显示外部模型能利用此路径直接篡改状态；这是进程内 API 隔离缺陷。

### G04 · P2：命令数字校验与整数解析不一致，异常输入可逃出解析器

位置：[commands.parse_goal_command](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/commands.py:26)、[_parse_next](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/commands.py:78)。

`next manage delete ²` 的 isdigit() 为真，int() 却抛 ValueError；`budget tokens` 加 5,000 位数字通过 isdecimal()，但触发 Python 的整数转换位数限制。两者均由真实 parser 复现为未捕获 ValueError，没有得到 ParsedGoalCommand(kind='error')。

建议集中一个有限长度的正整数解析函数，捕获 ValueError，明确零、负数、Unicode 数字和过大值的策略。不要在每个 UI 中分别补 catch；上层是否转换成 HTTP 错误另属适配层，本篇不把解析异常直接称作服务器崩溃。

### G05 · P2：完成后、晋升前的恢复缺少持久化待晋升阶段

位置：[service.mark_complete/consume_promoted/restore](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py)、[persist](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/persist.py)、[Server 晋升入口](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3929)。

探针完成第一个目标时第二个仍在队列；dump/restore 后状态为 complete、队列长度为 1，但 consume_promoted 返回 None、peek_continuation 为 false。队列没有丢失，丢失的是仅在内存中的待晋升意图。另一个阶段是新目标已创建而旧队列项尚未 acknowledge；这里需要按 item_id 去重，而不能仅比较 objective。

这与“重启后暂停自动执行”的安全选择不冲突：可以不自动启动，但应保存一个可检查、可显式继续的晋升阶段。建议持久化 completed_goal_id、queue_item_id 和阶段；在新回合成功认领后确认移除队列项。较小替代方案是恢复时显式标记待晋升，要求用户继续，不能悄悄把队列移除。

验收：分别在完成、创建下一目标、启动回合、ack 前后注入崩溃；验证不丢、不重复启动。当前探针只覆盖完成后恢复的服务路径，未声称已经重现整个 Server 的所有崩溃时序。

### G06 · P2：未解决失败记录没有总量界限，长期运行成本可持续增长

位置：[service.record_tool_result](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:241)。

保留最近 80 条之外，还保留所有未被相同 signature 后续结果覆盖的失败。这是合理的防漏验收策略，但没有总量限制。200 个不同参数的失败得到 200 条 evidence。每次写入重新构造 records、latest、retained，随后快照和 GetGoal 序列化也随它增长；长期唯一失败序列的累计维护成本可能为平方级。

建议分开“近期原始记录”和“按检查身份索引的未解决失败”，历史正文进入持久化日志。达到活动索引上限时明确报告需整理，不能静默丢弃失败后允许完成。不要简单将 evidence 全部切为最后 80 条，也不要把参数变化无条件当作同一次检查已修复。

### G07 · P2：每个工具前后全量哈希仓库，工作量与仓库大小乘工具次数相关

位置：[工具执行前](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:660)、[结果处理](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:417)、[workspace_digest](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/workspace.py:23)。

Goal 未完成时执行路径每次工具调用都读取仓库全体候选文件，结束后再次读取。to_thread 避免堵住事件循环，但没有消除磁盘读取量。合成 8MiB 文件集上 5 次直接调用中位数 7.523ms；这里只测指纹函数，不是完整工具延迟，也未证明大仓库的具体耗时。

方案：每工具完整哈希最保守但昂贵；按文件元数据缓存可减少读盘但有漏变动风险；按相关产物建快照更快但必须有明确范围。推荐先保存每次扫描的文件数/字节数/耗时，再选择“必要的验证边界做完整扫描，普通控制/读取工具复用会话观测”的设计；必须保留最终完成前的重新核验。不要用未经验证的缓存换掉当前保护。

### G08 · P2：三轮阻塞规则仅存在于提示词，不是服务契约

位置：[injection.GOAL_CONTINUATION_PROMPT](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/injection.py)、[service.mark_blocked](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:471)。

提示词要求同一非终局阻塞连续出现三轮，服务只检查 active 就转 blocked，没有阻塞身份或连续计数。无进展检测会在重复工具结果后暂停，但它不是同一个规则，不能拿来证明 blocked 被三轮门槛保护。此项为静态控制流确认。

先明确产品契约：若三轮只是模型判断指导，应在文档中声明无法机械保证；若必须强制，需要 blocker_key、观测回合和终局例外的结构化协议，再结合恢复重置测试。不要仅按总 turn 数大于三放行，那不能证明是同一阻塞。

## 3. 逐模块结论

| 模块 | 结论与建议 |
|---|---|
| __init__.py | 小型显式导出层合理；无需改成复杂依赖注入容器 |
| commands.py | HTTP/TUI 共用语法值得保留；优先 G04。自由文本 split/join 会折叠空白，若目标允许代码/多行约束，应保留原文片段 |
| injection.py | 原目标/准则/清单做转义且注明数据身份合理；G08 需区分提示指导和硬约束。减少重复说明前应实测模型漏项，不仅比较字符数 |
| persist.py | active 恢复暂停、旧预算状态迁移、字段筛选已有价值；补 schema_version、G03/G05。queue 恢复没有重用长度验证，异常超长状态需明确降级规则 |
| queue.py | 简单 FIFO 足够；pop(0) 在当前短队列不构成应立即修复的性能问题。优先晋升事务与 item_id 幂等，再考虑 deque |
| service.py | 用户控制、预算、验收单入口应保留；G01/G05/G06/G08。建议把完成校验变为纯结果函数，成功后一次提交证据和状态；不要仅按文件长度拆分 |
| state.py | 单调时钟累计、暂停结算方向正确；G03 深拷贝。completion criterion 超长直接截断会丢约束，宜与 objective 一样显式拒绝或保存原文 |
| tools.py | schema 与运行时双重状态检查、旧工具兼容拒绝合理；UpdateGoal 标 READ_ONLY 表示不写文件却会改领域状态，后续能力模型应区分，当前 supports_parallel=False 已避免直接并行执行 |
| types.py | 枚举和预算报告集中合理；frozen 不等于深度不可变。先修边界隔离，避免为了类型纯度重写整个模型 |
| workspace.py | 执行器无关的证据时效检查值得保留；优先 G02，再基于 G07 实测优化。纳入产物范围与环境身份需要独立契约 |

## 4. 验证与优先顺序

[离线探针](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/goal_probe.py) · [结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/goal-probe-results.json)。运行：`PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/goal_probe.py`。仅在临时目录写合成文件/修改权限，没有真实模型调用。探针刻画当前边界，输出 complete 不是验收通过。

本轮上下文与 Goal 相关回归 425 项通过（完整命令见 [验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-context-followup-validation.json)）；测试通过与上述未覆盖边界并存。没有做真实模型完成率实验，也未对桌面 UI 或全仓发布进行认证。

建议修复顺序：G02/G03/G04 确定性局部缺陷 → G05 恢复事务 → G01 可核验证据契约 → G06/G07 有界存储与成本优化 → G08 阻塞策略的明确化。状态、上下文持久化与媒体作为下一审核体系；本轮先交付 Goal 文案，等待按模块处理。
