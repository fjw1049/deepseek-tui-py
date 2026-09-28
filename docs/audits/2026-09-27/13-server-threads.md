# 第十三篇：HTTP 服务、会话、线程与事件流

日期：2026-09-28。接续第十二篇修复，按当前目录覆盖 server 的 **27 个 Python 模块**；索引原计数 26 已过期。本篇追踪认证、运行时资源、线程操作、存储、事件分发、导入导出和分享的核心路径，提供逐模块意见。**本篇保留审核时的历史证据；2026-09-28 本轮修复及剩余边界见 [13-implemented-fixes.md](13-implemented-fixes.md)。**不包含前端 reducer、真实部署、所有 HTTP 参数组合与 Windows 端到端测试，也不把核心路径审核等同于 17,024 行代码的形式化验证。

整体判断：分层雏形清楚，models/store/items 与 manager 分离，发布和恢复已有 thread/project lease，认证也采用默认拒绝；主要薄弱点是“单次成功”与“跨重启、跨进程、取消后仍一致”之间的差距。优先明确事件序号与资源/事务的持有方，再收缩 manager，当前直接引入通用事件平台或全量数据库迁移成本过高。

证据分级：A 为离线探针复现，B 为代码控制流确认但没有完整端到端验证，C 为架构建议。[探针](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/server_probe.py)及[结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/server-probe-results.json)只使用临时 JSON/ZIP、模拟事件与故障，不连接真实服务，不导入用户备份，不发送消息。

## S01 · P1：事件序号检查点滞后导致重启重复（A）

位置：[threads/store.py:58](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/store.py:58)、[append_event:336](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/store.py:336)。next_seq 每 16 个事件或间隔达到阈值才保存；构造 store 仅读取 state.json，没有从事件日志恢复最大序号。探针追加 seq=1 后直接重开 store，再追加仍得到 seq=1，`events_since(thread, 1)` 返回 0，新增事件被客户端游标跳过。

正常终结路径 flush 可以缩小窗口，但不能保护崩溃；独立 runtime 的 asyncio.Lock 也不能协调共享 store 的序号。建议先采用跨进程锁下预留序号段，允许空洞但禁止复用，并在启动时核验日志高水位。更大方案是 SQLite 事务持久化事件与序号，能解决更多一致性问题但需迁移。不要单纯缩短 flush 间隔当作正确性修复。验收：预留/写入各步骤崩溃、两 store 并发、已有损坏末行、断线游标恢复。

## S02 · P1：慢 SSE 消费者静默丢事件，其他线程也能挤掉本线程事件（A）

位置：[threads/broadcast.py:18](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/broadcast.py:18)、[routes.py:46](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/routes.py:46)。每个订阅者收到全局事件，HTTP 取出后才按 thread_id 过滤；队列满时移除最旧一条，局部 lagged 计数没有通知消费者。随后 SSE 直接推进 last_seq，没有补发。

容量 2 的探针中，当前线程 seq=11 被其他线程事件挤掉，下一帧直接到 seq=14，没有 gap/resync 信号。subscribe-before-backlog 和 finally unsubscribe 是正确的，应保留。

方案一：按线程订阅，溢出标记要求客户端重新加载快照/日志；改动小、语义明确。方案二：队列只作唤醒，消费通过持久游标拉取日志，可靠性更强但需有界分页与索引。不要仅调大 1024 容量。全局序号本来允许不同线程造成空洞，不能直接把所有 seq 跳跃当成本线程丢包。

## S03 · P1：存储截断污染实时 delta；flush 失败丢失待发文本（A）

位置：[store.py:369](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/store.py:369)、[manager.py:6683](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:6683)、[metrics.py:275](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/metrics.py:275)。大于 2,048 字符的 delta payload 被替换为 preview 字典；append_event 返回这个对象，manager 又原样广播，实时消费者拿不到 delta 字段。探针输入 3,000 字符，返回仅 `_truncated/_original_chars/preview`。

另外 TurnDeltaBatcher 在 emit 前清空缓冲，emit 抛 OSError 后重试 flush 返回 0，待发文本消失。单个 item 完成时可能以完整快照修正 UI，但不能保证中断期间流式内容和回放完整，前端最终恢复范围留给后续篇。

建议实时事件与磁盘压缩表示分离；持久省略时记录可恢复 item 引用，不能把截断字典伪装成可拼接 delta。batcher 对失败的未发送批次保留数据并规定幂等/重试语义。简单“失败后整批重发”会重复已成功部分，需要逐项确认或批次 ID。验收长 delta、首项失败、中途失败、并发 append、取消重试。

## S04 · P1：通用线程 store 缺少 ID 路径边界（A/B）

位置：[threads/store.py:88](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/store.py:88)。thread/turn/item/events/baseline/audit 的 ID 直接拼文件路径。探针 `save_thread(id="../escaped")` 在 threads 目录外写入 JSON（A）。load 也未核验记录 ID 与请求身份一致。

通常创建接口生成 UUID；本篇没有证明任意未认证 HTTP 请求可以利用，认证仍有效。风险在复用 store、外部导入与引用链边界（B）。建议复用第十二篇检查点的 ID 规则，覆盖读写删与所有 sidecar，并验证文档关系。替代方案摘要文件名增加迁移成本，首轮无需引入。验收必须测每类路径、绝对 ID、分隔符、内容 ID 不符和恶意引用。

## S05 · P1：replace 导入在完整验证前删除旧会话（A）

位置：[data_bundle.py:163](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/data_bundle.py:163)。只通过 manifest format/version 即可进入 clear_conversation_history；没有确保声明的 threads 内容存在、记录可解析、引用完整。探针构造仅包含合法 manifest 且 includes.threads=true 的 ZIP，replace 后旧线程被删除，报告成功且导入 0 个。

建议先在 staging 验证完整图、ID、schema 和所有资源，再以可回滚目录切换发布；缺少声明的数据目录应失败。另一方案仅禁止空导入可挡住这个探针，但拷贝失败、孤立引用及中途磁盘满仍会破坏旧数据，不充分。manager 的 replace 仅驱逐当前进程的 active engines；跨 runtime 批量操作锁、磁盘 next_seq 合并后内存 state 更新也需要一起设计（B）。验收失败前后原库字节不变，成功后所有引用闭合，重复导入可预测。

## S06 · P1：导出跟随外部链接；解包没有资源限额（A/B）

位置：[data_bundle.py:349](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/data_bundle.py:349)。`_zip_tree` 通过 is_file 后 zf.write 跟随符号链接。临时源目录中的 link 指向外部文本，导出 ZIP 包含目标内容（A）。本篇只证明进归档，不声称已向外网传输。

`_safe_extract` 的目录穿越检查值得保留，但 infolist + extractall 没有限制成员数、解压后总量和单文件大小（B，未做压缩炸弹压力测试）。固定 `<destination>.zip.tmp` 也不隔离并发导出（B）。建议只接受声明支持的常规文件/链接语义，验证实际根归属、唯一 staging，预检限额并在流式解压时再次计数。只看 ZIP 压缩大小不能限制展开资源。

## S07 · P1：用“锁文件变老”判断持有者死亡，可能并发写账单（A）

位置：[workbench_usage_ledger.py:77](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/workbench_usage_ledger.py:77)。超过 timeout 即 unlink 锁文件，未验证 owner；长事务仍在运行也会被夺锁。探针在外层锁仍有效时把 mtime 设为过去，第二个锁正常进入，两个上下文同时持有“排他锁”。旧持有者 finally 还可能删除新持有者的锁文件。

建议复用 OS advisory FileLease，死亡由内核释放，超时只表示等待失败。另一个方案是带 owner token 和续租的租约，但状态和时钟复杂度明显更高，单机文件账本没有必要。mtime 调旧是加速复现，不代表真实账本通常耗时超过 30 秒。验收长持有、崩溃、等待取消与三进程交接。

## S08 · P1：应用关闭没有完整收拢线程 manager（B）

位置：[app.py:529](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/app.py:529)、[run_http:748](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/app.py:748)、[manager.py:544](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:544)。lifespan 只有启动 reclaim 和 yield，没有 finally；CLI finally 只关闭 AppRuntime。manager.shutdown 为同步方法，设置标记并 create_task 关闭 provider client，既不等待这些关闭，也不统一收拢 active engine、monitor、warmup、事件刷盘与 lease。

在短命进程中 OS 会清资源，不能因此推断 ASGI 重载/嵌入式生命周期没有泄漏。本篇尚未做真实进程退出复现。建议单一 async close owner：停止新请求、取消并等待任务、flush、关闭共享/独占资源，最后释放 lease；lifespan 必须等待完成。避免每个路由自己加清理。验收 lifespan 连续启停、部分初始化失败、关闭时 pending approval、关闭被取消。

## S09 · P1：文件恢复与服务层收尾仍跨两个取消边界（B）

位置：[manager.py:3259](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3259)、[3388](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3388)。第十二篇已保证 checkpoint.restore 收拢完整文件事务，但取消传播之后，服务层可能未执行 isolate resync、检查点消费、thread 状态更新和 rewind 会话裁剪。检查点仍保留使重试有恢复基础，故不应把它直接描述为不可恢复数据丢失。

建议以持久 operation 状态把“文件已完成、待同步/会话裁剪”记录下来，或由一个受保护服务任务持有整个用户操作并返回 operation ID。仅屏蔽 HTTP 断连不足以覆盖进程崩溃。share_routes.restore 同样直接 await to_thread(restore_project)，取消时 worker 可能继续创建共享 worktree，线程导入却不再执行（B）；应采用同样的任务归属策略。验收恢复每阶段取消/崩溃后重试，结果与剩余可恢复状态均明确。

## S10 · P2：事件重放和批量存储操作同步阻塞事件循环（B/C）

位置：[store.py:416](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/store.py:416)、[manager.py:2755](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:2755)。events_since 即使 since_seq 很新也 read_text 整个日志再解析；线程列表相关调用常为每线程扫描全部 turn 文件。async 的导入/导出/优化方法直接执行同步 ZIP/遍历/原子写；运行时恢复还在全局 `_active_lock` 内等待文件恢复与同步，可能拖慢其他项目。

建议先分页/限制重放和为 store 建最小线程→turn 索引，将耗时 I/O 移到受事务锁保护的 worker。仅 to_thread 不保证一致性：compact_events 当前重写文件未与 append_event 的 asyncio 锁共享，直接移到线程可能引入新的丢写竞态。更大方案 SQLite 可统一索引与事务，但应先测 10/1,000/10,000 turn 的解析次数、事件循环延迟，再决定迁移。本篇没有量化该服务性能，不引用账本微基准作为此项证据。

## 逐模块审核文案

| 模块 | 通用性、已有优点与最终建议 |
|---|---|
| [server/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/__init__.py) | 稳定公开入口；当前导出 app 会提前加载较多服务依赖，若出现 CLI 启动成本再测量后惰性导出，不先造插件系统。 |
| [app.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/app.py) | HTTP/stdio 复用 AppRuntime 合理，Workbench 与 legacy 前缀分离；先修 S08，明确 app 与 runtime 的创建/关闭所有权。短轮询 legacy SSE 和实时 SSE 的兼容语义应写清。 |
| [auth.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/auth.py) | 默认拒绝、header-only token、health 例外边界清楚；建议使用常量时间比较，与 share_service 一致。缓存 token 文件首次生成的跨进程竞争和权限失败应独立测试，不把 localhost 等同于无认证。 |
| [approval.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/approval.py) | approval/elevation/user-input 三种桥的职责清楚，turn/thread 定向清理有价值；register 的重复 ID 行为不一致，UserInputBridge 覆盖旧 future，而另两类拒绝，应统一。保留显式 bridge，避免为了减少行数合并不同审批语义。 |
| [agent_segments.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/agent_segments.py) | 纯文本提取与 segment 常量范围小；保留。推理兜底应明确可展示字段约定，避免一般回复与内部推理在恢复时混合。 |
| [metrics.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/metrics.py) | trace 分段和 delta 合批有价值；修 S03 的失败确认语义。延迟应统一使用 monotonic，用户时间仅用于跨端展示，避免时钟调整影响 duration。 |
| [phase_bridge.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/phase_bridge.py) | 意图提取、gate、plan 校验、展示分开，可替换 narration 模型且有 timeout/fallback；保留。模型调用的 usage 与取消所有权应接到主回合账本，不因“仅旁白”遗漏资源核算。 |
| [runtime.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/runtime.py) | 提供 HTTP/stdio 共享薄业务入口，工具执行复用 registry；legacy 内存 ThreadStore 与 durable manager 并存会造成身份/状态概念重复。先明确 legacy 兼容边界，再迁移入口；共享 tool runtime 的 shutdown 所有权见 S08。 |
| [routes.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/routes.py) | typed request 与错误码映射方向合理，SSE 在 finally 退订；修 S02，给重放分页和 resync 契约。拆分宜按 thread/turn/storage/ingress 业务资源，不机械按路由数量。 |
| [sessions.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/sessions.py) | TUI/Workbench 列表统一与追加完成回合有用；`persist_tui_thread` 以 user-message 数量对齐完成 turns，需要明确压缩/删改历史后的语义。显式 path 导入可保留，但 session_id 不应同时成为任意路径。 |
| [session_snapshot.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/session_snapshot.py) | 分享重新生成 thread/turn/item ID，不复制机器 trust/auto-approve，资源校验和安全路径检查是优点；metadata 内嵌的引用尚需独立重映射清单。来源会话与项目快照不是单个持久事务，保留尺寸上限并补全导入失败测试。 |
| [share_routes.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/share_routes.py) | origin 绑定凭证、读取外部链接不带凭证、禁重定向和流式限额合理；修 S09 的后台写入取消归属。对外部读取 origin 的本地网络访问策略需产品明确，不能仅凭 URL 合法就宣称网络隔离。 |
| [share_service.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/share_service.py) | 与本机工具运行时独立，能力 token、上传密钥比较、HTML 转义/CSP 做得明确；过期数据只在被读取时删除，需有界清理策略，避免长期无人访问的分享无限保留。schema/磁盘损坏响应应可控。 |
| [data_bundle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/data_bundle.py) | 清晰区分 conversations/settings/all；优先修 S05/S06，先完整验证再发布，保留旧目录用于恢复。不要在只修解包路径后就称为安全导入事务。 |
| [data_inventory.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/data_inventory.py) | 显式保护活线程和孤立检查点，职责清晰；批量优化/清空与其他 runtime 的协调不足，需服务级存储操作锁。文件数量/总大小扫描重复，先共享一次 inventory 快照。 |
| [workbench_usage_ledger.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/workbench_usage_ledger.py) | 按 turn ID 幂等、日聚合与一年保留合理，损坏账本拒绝覆盖有价值；修 S07。写整个年账本的成本增长应测量后再决定是否改追加日志/数据库。 |
| [threads/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/__init__.py) | 兼容导出层维持公共 import 很实用；部分私有测试名也作为导出扩大耦合，后续新测试依赖公共行为，不在本轮清理旧接口。 |
| [threads/models.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/models.py) | Pydantic 记录与请求模型统一，schema_version 明确；ID/引用和有限状态目前大量用任意字符串，优先补 S04 对应边界，避免一次把所有 str 改 Enum 破坏兼容。 |
| [threads/store.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/store.py) | 原子单记录写、跳过损坏列表项、按线程事件锁合理；优先 S01/S04，明确单文件原子性不等于多记录事务和跨进程锁。查询索引见 S10。 |
| [threads/broadcast.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/broadcast.py) | 小型同步 fan-out 简洁、调用成本可控；修 S02，不可让容量限制静默改变事件可靠性。capability 只需订阅/退订/溢出状态，不必引入消息中间件。 |
| [threads/errors.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/errors.py) | 错误类型携带 code 避免字符串分类漂移；保留，逐步让新路径都使用该类型。 |
| [threads/items.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/items.py) | 恢复过滤未完成工具轮、真实用户来源与紧凑化工具结果方向正确；metadata 为任意 dict，损坏 input_message/images 可中断恢复，宜定义少量边界校验。展示分支和模型重建已不同，应保持明确接口。 |
| [threads/manager.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py) | thread/project lease、活动回合预留、发布日志、重启恢复已有扎实基础；6,828 行涵盖线程 CRUD、引擎、发布恢复、存储管理、计费与事件。优先 S08/S09，随后按“引擎会话生命周期 / 项目发布事务 / 存储运维”拆分，保持单一锁协议。 |
| [threads/rewind_audit.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/rewind_audit.py) | 先归档再删除及内容 fingerprint 有价值；不等于可以直接自动回滚整个 rewind。大归档在 worker 中完成已有考虑，需与 S09 的操作 journal 关联，并限制长期保留成本。 |
| [threads/soft_resume.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/soft_resume.py) | 对恢复候选列表做局部截断，提示 resume 而非重复 spawn，易理解；总候选数仍无上限，增加总预算比不断调小单条长度更通用。 |
| [threads/titles.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/titles.py) | 纯函数生成标题、保留用户标题、查询首条消息合理；中英文启发式不必抽象成通用 NLP 层，补 URL/代码首行样例即可。 |
| [threads/usage.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/usage.py) | 使用 engine ledger 优先、事件兜底、按模型聚合合理；`bool` 也会被部分 numeric helper 接受为计数，与 workbench ledger 不一致。统一数值入口并覆盖多模型混合，不把估算费用当实际账单。 |

## 优先方案与下一步

1. 先保证数据不丢：S01、S03、S05、S07；每项以崩溃/写失败/并发复现验收。
2. 再明确事件可靠性：S02 的线程订阅、溢出 resync 与持久游标；与未来前端篇联合验证。
3. 收口持久化与资源边界：S04/S06、S08/S09。先明确事务 owner，再做文件拆分。
4. 最后量化 S10，决定小索引还是 SQLite。不要把一次微基准当作全面重构依据。

本轮相关扩展测试包含 workspace 与 server contract，首次为 448 通过、1 跳过、2 个已复现的基线失败；具体限制见第十二篇修复记录。新篇探针用于揭示覆盖缺口，原测试通过不能抵消这些缺陷。下一篇按既定顺序：**协议、事件模型与展示归约**。
