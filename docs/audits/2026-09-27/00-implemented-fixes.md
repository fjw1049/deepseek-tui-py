# 前四篇审核的修复记录

实施基线：2026-09-27 当前工作区，保留原有 Goal、Server、Workbench 等未提交改动。未创建提交、未发布。原 01—04 篇是修复前的审核证据，保留原文；旧 probe 的断言确认的是旧缺陷，不应再用它们作为修复后的验收标准。

本轮采用局部修正，优先处理重复执行、硬拒绝绕过、进程清理、恢复丢失和正文误删。没有整体重写 Engine、Task 或 Hook。新增验收测试见 [test_audit_regressions.py](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_audit_regressions.py)。

**“已实施”不等于承诺所有故障下恰好执行一次。** 下表明确区分已修路径、缩小的故障窗口、尚需产品决策或更大迁移的部分。

## 1. 自动化任务

| 原问题 | 本轮实施 | 状态与边界 |
|---|---|---|
| A01 完成后首次投递丢失 | reconciliation 处理 delivery_attempts=0 的未投递终态 | 已实施；渠道已接收而本地确认失败时仍可能重发 |
| A02 最近 100 条截断 | 同步全部运行历史，旧的活跃/待投递记录不会被窗口排除 | 已实施；目前仍扫描历史文件，没有声称查询变成 O(1) |
| A03 调度重复入队 | 同一 Manager 的 tick 加锁；scheduled slot 使用稳定 run ID；先写 dispatch intent；Task 接受幂等键 | 已实施于定时调度。手动 run_now 和 HTTP trigger 仍未统一成事务化 outbox；客户端重试语义未改变 |
| A04 超时通知遗漏 | 投递端接受 TIMED_OUT 对应失败结果 | 已实施 |
| A05 飞书凭据串用 | token 缓存键纳入 API 地址、app_id、app_secret 的摘要 | 已实施；保留单缓存槽，没有引入多租户缓存体系 |
| A06 误删正文 | 去掉按叙述句开头和 Markdown 分段猜测正文的逻辑，只保留明确内部标记清理、空行与长度处理 | 已实施；旧测试两项改为保留合法正文，并增加多节报告测试 |
| A07 未知渠道静默成功 | 渠道别名集中规范化，未知值拒绝；best_effort 必须为 bool | 部分：notify 缺 thread 仍保留原 log-only 行为，未改变产品兼容语义 |
| A08 Cron 格式不一致 | 入口严格要求五字段 | 已实施 |
| A09 外部等待阻塞调度 | IMAP/SMTP socket 超时、digest/投递阶段超时；reconcile 与 tick 独立循环 | 部分：单个 tick 内 digest 仍串行，线程内阻塞操作不能靠取消协程立即终止；不是完整异步邮件客户端迁移 |
| A10 工作区含糊 | 创建/更新固化绝对目录；工具/HTTP 默认目录来自当前调用环境；多目录明确拒绝 | 已实施于新建/更新；没有批量改写旧配置 |
| A11 排队时间当执行时间 | 入队时为 QUEUED，started_at 从真实 Task 取得 | 已实施 |
| A12 回复串到其他 turn | 等待逻辑绑定创建时返回的 turn_id | 已实施 |

主要文件：[tools/automation.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py)、[pipeline.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/pipeline.py)、[inbox.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/inbox.py)、[delivery.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/delivery.py)。

不采用 SQLite 的原因：当前可以先明确“持久化运行意图 + Task 幂等键”，收益直接、迁移小。若下一阶段统一 scheduled/manual/HTTP 入口，再把它们收敛为一个可恢复 dispatch 协议，避免维护三套相似逻辑。

## 2. 权限、审批与沙箱

| 原问题 | 本轮实施 | 状态与边界 |
|---|---|---|
| P01 Engine 丢失显式只读 | 创建、每轮同步和模式切换均传递配置中的 sandbox_mode | 已实施；不改变既有 auto→trust 映射规则 |
| P02 复合命令丢换行 | TOML 策略接收原始 Shell 字符串，词法分割只供 fallback 启发式使用 | 已实施；其他策略仍兼容旧 token-list 接口 |
| P03 never 被缓存/子路径绕过 | 主审批缓存不覆盖硬拒绝；子工具先检查 never，再处理自动审批/审批桥 | 已实施；没有重写成新的权限框架 |
| P04 子工具丢策略 | SubAgentRuntime 及其子深度复制携带命令/网络策略，真实 ToolContext 使用它们 | 已实施 |
| P05 提权串答 | 每次提权生成独立 elevation_id，保留原 tool_call_id 供展示关联 | 已实施；重复 bridge 注册明确拒绝 |
| P06 发布竞争和记录泄漏 | 先注册再发事件；等待路径 finally 丢弃请求；线程取消清除完成/待处理元数据 | 已实施 |
| P07 网络提权新增文件写 | 在现有 sandbox policy 上只修改 network_access | 已实施；read-only 可允许网络而不获得 writable roots |
| P08 Cron 授权指纹缺字段 | 指纹包含规范化排序的完整参数 JSON | 已实施；不同默认/省略写法可能增加一次审批，这是保守选择 |
| P09 网络 cache/redirect 边界 | 硬 deny 在会话缓存之前；fetch 原目标、代理提取目标、重定向逐跳检查 | 已实施于已接入 NetworkPolicyDecider 的工具；没有声称全系统默认网络防火墙 |

主要文件：[exec_policy.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/exec_policy.py)、[network.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/network.py)、[sandbox.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/policy/sandbox.py)、[server/approval.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/approval.py)、[orchestrator/tooling.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py)、[tools/web.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/web.py)。

暂不改的产品行为：auto 与 trust 的既有耦合、缺少 OS 沙箱时的降级、纯文件工具与 Shell 沙箱的不同执行层。这些需要配置迁移、界面解释和平台验收，不能只改一个 bool 就宣称完成能力隔离。

## 3. Hook 生命周期

| 原问题 | 本轮实施 | 状态与边界 |
|---|---|---|
| H01 取消/超时遗留进程 | POSIX 创建独立进程组，取消/超时/输出超限统一杀组、排空管道并回收 | 已实施且有真实子进程回归；Windows 仅保留单进程 kill，未承诺清理进程树 |
| H02 错误跳过后续守卫 | pre/message_submit 的必需 Hook 出错且 continue_on_error=false 时直接形成阻断决定 | 已实施；显式允许继续的 Hook 保留原意 |
| H03 子工具缺 Hook | 子 Agent 加前后 Hook、继承 shell_env executor；HTTP direct tool 入口也执行配置 Hook | 已实施于这些入口；插件动态装载仍使用既有路径 |
| H04 别名在守卫之后解析 | 主工具、子工具、HTTP direct 在 Hook 前规范化兼容名称/参数 | 已实施 |
| H05 exit-code 条件无数据 | 把实际 returncode 填入后置 HookContext | 已实施 |
| H06 输出消费者不完整 | 主生命周期 systemMessage 发为状态消息；session_start 上下文进入会话且标为系统来源；前置上下文与后置反馈并入工具结果；会话开始/结束去重并下沉到 Engine | 部分：子循环中所有事件的 systemMessage/additionalContext 语义尚未完全统一；需要逐事件契约 |
| H07 文件工具方言 | Claude 文件工具参数补充 path→file_path 转换 | 已实施于已支持字段，不承诺全部第三方 Hook 方言兼容 |
| H08 缓冲/环境超限 | stdout/stderr 各 256KiB 上限；过大 tool_args 走 stdin，环境只留提示标记 | 部分：没有给全部 Hook 输入/模型上下文建立独立 token 预算 |
| H09 后台任务无主 | executor 跟踪后台 task，关闭时取消并等待；并发上限 16；非零退出记录；决策型 Hook 禁止后台运行 | 已实施；慢同步守卫仍需等待它的有界超时 |
| H10 观测端串行等待 | 同一事件的各 sink 并发发送；异常分开记录；补充 close 路径 | 部分：每次 emit 仍等待最慢 sink，未引入带背压的异步队列 |

同时修正：enabled=false 不再装配 dispatcher sinks；显式单 Hook timeout 优先于全局默认；未知 when 条件拒绝而非猜测。

主要文件：[integrations/hooks.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/integrations/hooks.py)、[orchestrator/lifecycle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/lifecycle.py)、[subagent/loop.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/subagent/loop.py)、[server/runtime.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/runtime.py)。

选择并发 sink 而非观测总线，是因为当前有界改动已能消除各 sink 延迟相加；独立队列必须同时设计丢弃、重试和关闭语义，不能只做 fire-and-forget。

## 4. 持久化 Task 与恢复

| 原问题 | 本轮实施 | 状态与边界 |
|---|---|---|
| T01 多调度器重复领取 | Task 目录持有进程级文件锁，生命周期由 Manager 管理；第二个活动调度器明确拒绝 | 已实施；是单所有者方案，不是多进程共享消费协议 |
| T02 提交失败仍可执行 | task record 先持久化再发布到内存队列；queue.json 作为可重建索引；resume/cancel 写盘失败回滚内存 | 已实施于这些公开转换；不是多文件事务 |
| T03 worker 被存储错误杀死 | worker 捕获 OSError、记录 storage_error、暂停并重试持久化，避免重新调用 executor；修复 teardown 取消被吞后继续循环 | 部分：storage_error 未增加前端展示；非合作 executor、跨文件 artifact 失败仍需更完整运行状态协议 |
| T04 完成窗口导致重做 | Engine 写独立完成回执；恢复先查回执；Task completed 落盘之后才清 transcript/回执 | 缩小完成窗口；工具副作用与 checkpoint 之间仍是至少一次恢复，不能承诺 exactly-once |
| T05 坏记录/格式 | 隔离坏嵌套 Task 记录；拒绝未来 transcript 版本、错误 cursor/messages、坏 JSON；展示历史坏 blocks 可重新构建 | 部分：消息语义和 tool_use/tool_result 配对尚未统一严格验证；未知 TaskRecord 版本仍明确拒绝启动 |
| T06 初始化后加载泄漏 | 完成回执与 transcript 在创建客户端/运行时之前加载；事件消费者失败时监督并停止生产 turn | 已覆盖此次恢复读取与采集器失效路径；没有全面改写资源管理为 AsyncExitStack |
| T07 历史受缓存影响 | list/count/prefix resolution 使用磁盘历史加活动记录，淘汰不丢查询范围 | 已实施；换来正确历史，查询仍为文件扫描 |
| T08 全量写放大 | 缓存已持久化快照，仅写有变更的 task record，queue 单独写 | 部分：比较仍需序列化/遍历，保存仍有同步 I/O，内存保留快照也有成本 |
| T09 detail 丢失 | 正常成功结果的 detail 保存为 artifact，写 result_detail_path | 已实施正常存储路径；没有增加跨文件 artifact 事务 |

主要文件：[task/manager.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/manager.py)、[task/store.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/store.py)、[durable_transcript.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/durable_transcript.py)、[run_conversation.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/run_conversation.py)、[engine/dispatch.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/dispatch.py)。

新增限制是有意的：同一 Task 数据目录不能被两个独立 Manager 同时调度；已有进程持锁时，新进程明确报错。需要多个前端时，应连接同一个运行时，而不是各自抢占同一队列。

## 5. 验证记录

综合选择集：**446 passed、2 skipped、7 deselected，6.36 秒**。覆盖自动化管理/投递/API、Task 恢复/取消/审批、权限/提权、Hook、Web、子 Agent 和协作相关回归；不是全仓库测试。

7 个 deselected 的组成：

- 5 个 TestSeatbeltIntegration 真实系统沙箱测试，本轮未运行。
- 旧子 Agent 测试的 goal_continuation 参数项：原有 Goal 改动会拒绝没有活动 Goal 的内部续跑。它在本轮开始前保存的工作区 diff 中已存在；未放松生产拦截以迁就旧测试。
- test_add_task_default_auto_approve_true：HEAD 中 Task 默认已为 False，该旧断言仍要求 True。保留原测试并在此记录失配，未改生产默认权限。

新工具守卫会无条件读取 ToolSpec 的审批契约，因此把一个压缩测试的空 SimpleNamespace 工具替身换成真实 FileSearchTool；压缩断言仍保持不变。两个既有 Engine.__new__ 测试补上原有 GoalService 所需的空 snapshot；未绕过实际 Goal 权限检查。

在综合集之后，额外收紧了损坏 transcript 的读取行为；恢复、取消、轮次预算、Hook 及新增回归的相关复测为 **78 passed，2.32 秒**。这些用例与综合集有重叠，不相加宣称独立测试数量。新增 HTTP direct 工具别名守卫验收后，新回归文件最终为 **32 passed，1.07 秒**。

静态检查：涉及的模块通过 Ruff F 类错误检查与 compileall；不是声明全库 lint/style 全部通过。新增回归使用隔离 DEEPSEEK_HOME/插件目录、假 API 与临时文件；真实子进程测试仅验证 Hook 的进程回收和输出上限。

未验证：真实模型/邮件/飞书消息投递、Windows 进程树和文件锁、断电、跨主机共享目录、整个前端构建。没有实际发送消息。

## 6. 本轮后的优先顺序

前四篇剩余的最大架构工作是：统一各自动化触发入口的可靠派发、明确权限能力上限、统一 Hook 输出消费者、完善 Task 跨文件完成协议。它们都需要独立的迁移和验收，不能把本轮局部修复包装成整个体系已无风险。

用户要求的下一篇已完成：[05 · 子 Agent 与协作机制](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/05-subagents.md)。第五篇的新问题先交付建议，未自动实施。
