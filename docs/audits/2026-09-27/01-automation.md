# 01 · 自动化任务体系审核

审核日期：2026-09-27。对象：当前工作区实现，包含未提交改动。未修改业务代码。

本篇完整阅读 `automation/` 四个 Python 文件和 `tools/automation.py`，并追踪 `tools/runtime.py`、`tools/task/manager.py`、`tools/task/store.py`、`tools/task/models.py`、`server/runtime.py`、`server/routes.py` 中相关链路。任务管理器、HTTP 服务、权限和 Engine 的全模块结论留到各自篇章，不以本次局部阅读代替完整审核。

## 结论

**复用持久化 Task 执行自动化任务是正确方向，当前最需要修复的是持久化状态之间的断点，而不是增加更多设计模式。**

目前的主要风险是：运行记录与 Task 入队没有共同的幂等边界；任务完成与结果投递没有完整的恢复协议；状态同步依赖“最近 N 条历史”；调度器承担外部网络等待。这些问题会造成漏发、重复入队、旧任务状态长期不更新和后续任务延迟。

优先保留现有执行模型，先修状态转换与恢复，再拆职责。只有在历史规模、并发运行实例或事务需求得到确认后，才推进存储迁移。直接引入分布式任务框架不符合这个桌面应用目前展示出的需求。

### 四个评价维度

| 维度 | 已有优点 | 当前限制 | 建议 |
|---|---|---|---|
| 通用性 | Cron 和 HTTP trigger 复用 Task；存在 `DeliverySink` 协议 | `cwds` 接受多个目录却只用第一个；默认工作区没有在创建时固化；正文清洗绑定特定报告文风 | 收紧输入契约，明确工作区和最终正文来源 |
| 优雅性 | Schedule、Record、Run 分开；格式化集中 | 一个文件混合工具、模型、CRUD、调度；重复状态判定分散在两个层次 | 围绕状态转换和依赖方向拆分，避免机械拆成大量小文件 |
| 可扩展性 | 新渠道可实现 Sink；Task 执行可注入 | 渠道枚举/别名/校验分散；凭据缓存不区分应用；HTTP trigger 借用虚拟 automation | 先统一配置模型与渠道分发，等实际需求再推广通用触发模型 |
| 架构合理性 | 没有另起一套 Agent 执行器；区分定义与执行 | 原子文件写被误当成业务事务；调度、状态同步和网络投递耦合 | 明确运行幂等键、投递状态和持久化责任 |

## 当前调用链

```text
CronCreateTool / HTTP CRUD
          ↓
AutomationManager → automation definition JSON
          ↓ scheduler_tick
build_final_prompt → digest 预取 → TaskManager.add_task
          ↓                         ↓
      run JSON                queue JSON + task JSON
          ↓ reconcile_run_statuses
      Task 状态映射 → 先保存 run 终态
          ↓
try_deliver_completed_run → Sink → 邮件 / 飞书 / 企业微信 / 会话通知
          ↓
      保存 delivery_done / delivery_attempts
```

HTTP trigger 先创建 Task，再保存 `_http_triggers` 下的 Run。飞书入站另走 Thread/Turn 流程和等待回复逻辑。这三条入口并没有完全相同的恢复与投递语义。

## 已验证的问题

P1 表示优先修复的数据/执行一致性问题；P2 表示明确功能缺陷或具有触发条件的隔离问题；P3 表示契约和维护问题。优先级并不意味着所有问题都会在每次运行触发。

### A01 · P1：完成状态落盘之后，第一次投递可能永久丢失

位置：[reconcile_run_statuses](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1421)、[先持久化终态](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1495)。

运行完成后先保存 `COMPLETED/FAILED`，然后调用外部投递。如果这两步之间进程退出，持久化状态是终态、`delivery_done=False`、`delivery_attempts=0`。恢复逻辑仅为 `delivery_attempts > 0` 的终态记录尝试投递，于是这条消息永远不再发送。

离线探针重建这个磁盘状态并重新打开 Manager，模拟 Sink 的调用次数为 **0**。

最小修复：对于启用投递的终态记录，以“投递尚未终结”为选择条件，不能以“曾经失败”为条件。建议把投递状态明确为 `pending/sent/skipped/failed`，尝试次数仅用于重试策略。

注意另一方向：远端已收到消息、本地尚未保存 `sent` 时退出，恢复重试可能重复发送。修复漏发之后应明确采用至少一次语义；能传幂等键的渠道使用稳定 Run ID，不能承诺通用的严格恰好一次。

### A02 · P1：只同步最近 100 条，会永久遗漏旧的运行和待投递记录

位置：[最近 100 条截断](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1411)。

排序截断发生在状态筛选之前。只要一条尚未完成的 Run 前面出现 100 条较新的记录，该 Run 就不再被同步。即使对应 Task 已经完成，自动化页仍可永久显示运行中。旧的投递重试也受影响。

HTTP trigger 共用 `_http_triggers` 桶，因此不同触发请求也会互相挤出扫描范围。

探针建立 1 条旧 RUNNING 和 100 条新 COMPLETED，Task 已完成，但同步后的旧 Run 仍是 **running**。

最小修复：先筛选所有未完成/待投递项，再分页处理；“最近 100 条”只能用于展示历史。短期允许全扫描以恢复正确性，随后用待处理索引降低成本，不能用截断待处理集合换性能。

### A03 · P1：Task 入队成功而 Run 保存失败后，再次调度会重复入队

位置：[检查历史后入队](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1346)、[入队后才保存 Run](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1360)。

现有顺序为：检查历史 → 随机生成 Run ID → 创建持久化 Task → 保存 Run → 推进下一次时间。Task 创建成功后遇到退出或 Run 写入失败，下一轮仍看不到已触发记录，便再次创建 Task。

探针在 Task 创建后让 `save_run` 抛出磁盘错误，再执行一次 tick，观察到 **2 次 add_task**。这不依赖多个调度器，是单个调度器重试也能触发的窗口。

另外，两个重叠的 tick 在 await 处交错，会同时通过历史检查。最小并发试验：原实现生成 **2 个 Run**；外层共用 `asyncio.Lock` 后生成 **1 个 Run**。正常单实例 scheduler loop 自身是串行的，因此并发结果证明的是缺少重入保护，而非证明普通部署必然重复。独立 ToolRuntime/进程共享相同数据目录时需要进一步验证部署约束。

最小可靠方向：使用 `(automation_id, scheduled_for)` 作为稳定触发键，先记录派发意图，Task 创建接口接受同一幂等键并能恢复已有 Task。仅把 `save_run` 移到入队之前不够：目前没有 Task ID 的 QUEUED Run 会被同步器跳过，可能改成永久漏执行。

共享锁解决同一把锁覆盖范围内的并发；不解决跨进程和崩溃恢复。应把这些保证分别写清楚。

### A04 · P2：超时任务已映射为失败，但投递端拒绝发送

位置：[超时映射](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1486)、[只接受 TaskStatus.FAILED](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/pipeline.py:276)。

同步器把 `TaskStatus.TIMED_OUT` 转为 `AutomationRunStatus.FAILED`，而投递端重新读取 Task，仅接受 `FAILED`，遇到 `TIMED_OUT` 直接退出。

探针结果：Run 为 **failed**，Sink 调用 **0 次**，`delivery_done=False`。现有格式化代码已有超时提示，说明通知能力存在，但链路不一致。

最小修复：统一 Task → Run 的终态映射，并让投递消费规范化的执行结果。短期可补 `TIMED_OUT` 分支；长期避免下游重新解释一次已经转换过的状态。

### A05 · P2：飞书 Token 缓存只按域名隔离，切换应用仍复用旧 Token

位置：[_feishu_tenant_token](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/inbox.py:452)。

缓存命中只比较 `base`、token 和有效期，没有比较 `app_id`。同一服务域名下，进程先使用应用 A，再切换到 B，会继续使用 A 的 Token。

离线假客户端试验：先请求 A，再请求 B，返回相同 Token，HTTP 方法只被调用 **1 次**。未接触真实凭据和服务。

最小修复：缓存键至少包含 `(base, app_id)`，凭据更新时失效。实际支持并发刷新后，再增加每个键的刷新合并，不必提前设计全局认证框架。

### A06 · P2：合法报告内容会被启发式清洗删除

位置：[_drop_process_lines](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/delivery.py:123)、[_pick_report_section](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/delivery.py:134)。

报告按 Markdown 水平线分成多个部分时，清洗器会优先取最后一个符合标题模式的部分。探针输入“第一部分：收入增长”和“第二部分：成本下降”，输出只剩第二部分。以“首先/接下来/然后”开头的正常步骤也可能被整行移除。

这不是纯审美问题，而是通用内容被误删。任务要求教程、多部分报告时尤其明显。

建议：上游明确提供最终 assistant 正文；投递层仅处理必要控制标记、渠道长度与编码。保留原文，长度超限提供明确截断提示或附件策略。不要用中文句首词推断正文与过程。

### A07 · P2：未知渠道被视为成功投递

位置：[is_active](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/delivery.py:215)、[_sink_for_mode](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/pipeline.py:148)、[HTTP 创建透传 delivery](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/runtime.py:834)。

`DeliveryConfig` 将任意非 silent 字符串视为 active，分发器遇到未知值却返回 SilentSink，随后写 `delivery_done=True`。探针使用 `feihsu`，未发送任何消息却被标记已完成。

工具 JSON Schema 限定了枚举，但 HTTP/持久化边界接受任意字典，因此不能依赖工具 Schema 保证全链路正确。

最小修复：统一渠道枚举和别名规范化；在创建/更新入口拒绝未知值。只有用户明确选择的 silent 才静默。`notify` 缺少有效会话目标时也应明确反馈配置问题，而不是只有日志。

### A08 · P3：声明只支持五字段 Cron，实际接受六字段

位置：[AutomationSchedule.parse](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:694)。

代码只调用库的 `is_valid`，未检查本应用要求的字段数。当前安装环境下，探针 `* * * * * *` 被接受，与工具描述、错误文案和类注释的“五字段”契约不一致。

建议：显式检查五字段，或明确扩展产品契约并验证调度分辨率。当前轮询间隔至少 5 秒，不宜无意中接受秒级语义。此项验证的是本地依赖实际行为，没有依据外部最新版推断。

## 代码追踪确认、尚未端到端实测的问题

### A09 · P1：外部收件箱/邮件等待可以拖住整个调度循环

位置：[IMAP 建连](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/inbox.py:206)、[SMTP 建连](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/inbox.py:552)、[串行 scheduler loop](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1581)。

IMAP/SMTP 没有显式设置超时；`asyncio.to_thread` 能避免阻塞事件循环线程，但调用它的调度协程仍然要等待完成。Cron 入队之前等待摘要预取，reconcile 中等待实际投递，然后才进入下一轮。

因此一个外部服务长时间不响应，会让这条调度链上的其他任务无法及时启动/同步。飞书请求虽然有超时，多个失败投递也会串行叠加延迟。

建议分两步：先为同步网络客户端设置有界超时，并给预取和投递设置阶段预算；随后把投递交给独立、可恢复、有限并发的消费者。仅 `create_task` 后不追踪结果会丢失恢复能力；仅对 `to_thread` 外层取消也不代表工作线程已停止。

严重性基于控制流及缺少超时，未用真实不可达邮箱制造阻塞，未声称测得线上延迟。

### A10 · P2：工作区契约含糊，目录可能悄悄变化

位置：[CronCreateTool 创建](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:351)、[只取 cwds[0]](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/pipeline.py:210)、[Task 默认工作区](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/manager.py:188)。

工具描述 `cwds` 为多个执行目录，执行时只采用第一个。省略 `cwds` 时也没有把创建时 `ToolContext` 的工作区写进定义，而是执行时采用 TaskManager 默认值。

这使全局持久化的任务定义依赖后来启动的运行时环境。单一工作区时可能恰好符合预期，换工作区或不同入口创建时不再稳定。

最小方案：产品若只支持一个工作区，字段改为单值或显式拒绝多个；在创建边界固化解析后的绝对工作区。若确实需要多工作区，要先决定每个目录独立 Run 还是同一次 Run 的允许访问范围，不能只保留列表外观。

### A11 · P2：排队时即写入 started_at，运行时长统计混入排队时间

位置：[入队结果设为 RUNNING](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/pipeline.py:220)、[后续只在 started_at 缺失时补齐](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1458)。

`TaskManager.add_task` 返回 QUEUED，但 Run 立刻记录 RUNNING 和当前时间。后续同步会纠正 status，却保留旧 started_at；Task 真正启动时不会覆盖。

建议初始 Run 为 QUEUED，Task 进入 RUNNING 后再用 Task 的 started_at。若需要展示等待耗时，单独使用 created_at/scheduled_for，不要混用。

### A12 · P2：飞书回复等待没有绑定创建的 turn_id

位置：[wait_thread_turn_text](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/pipeline.py:542)、[run_feishu_inbound_agent](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/automation/pipeline.py:615)。

入口拿到了 `turn.id`，等待函数却只接收 thread_id，结束后读取 `thread.latest_turn_id`。如果同一会话发生新一轮执行，可能读取后来的回复。超时后也只是记录 warning，仍可取未结束轮次的文本并发送。

这是并发条件下的风险，未跑真实飞书端到端验证。应以固定 turn_id 等待并读取结果，明确区分超时、无正文和成功。外部会话身份映射最好由稳定键记录，不依赖可编辑的线程标题搜索。

## 性能测量与方案横向比较

### 观测一：limit=100 并未限制历史文件读取量

位置：[list_runs](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/automation.py:1209)。

当前实现读取所有 Run JSON、构建所有对象、全量排序，然后才切片。因此运行记录增长会持续增加每轮成本。由于调用发生在异步调度路径中的同步代码里，这段工作会占用事件循环线程。

本机 Darwin、Python 3.12.13，合成数据、临时目录、预热一次、每项 7 次取中位数：

| 历史条数 | limit=100 实际读文件数 | 当前最近100查询 | JSON全量筛选待处理 | SQLite索引筛选待处理 |
|---:|---:|---:|---:|---:|
| 100 | 100 | 1.584 ms | 1.615 ms | 0.006 ms |
| 1,000 | 1,000 | 15.957 ms | 16.121 ms | 0.006 ms |
| 5,000 | 5,000 | 91.846 ms | 89.160 ms | 0.006 ms |

两种“待处理”查询返回同一条最旧 RUNNING 记录并完成相同记录类型反序列化。当前最近100查询是额外基线，语义不同，不能和待处理查询直接当作等价替换。

限制：SQLite 是最小只读索引原型；不包含数据构建、索引维护、迁移、写入事务、fsync 和故障恢复；全部是温缓存、小记录。这里证明的是全量扫描成本及索引查询方向，不是“系统整体快多少倍”。没有为了得到更小的耗时并行执行基准，以免磁盘竞争混淆结果。

### 观测二：任务持久化存在写放大

位置：[_persist_all_locked](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/task/manager.py:780)。

新增、出队、完成等结构性变更都会写 queue 加所有内存中的 Task。底层 `write_json_atomic` 每文件执行 fsync。因此 N 个内存任务时一次结构性操作至少 N+1 次文件替换，不是只改本次 Task。

注释称“一次全写保证多文件间一致”，这个保证不成立：每个文件原子替换，仍可能只完成部分文件便退出。恢复逻辑能修复其中部分情况，但并不等同于事务。

本篇未单独测量 fsync 延迟；完整 Task 审核应验证恢复一致性与增量写路径，再决定优化。不建议在此处先凭感觉增添缓存。

### 可选方案

| 方案 | 能解决什么 | 代价/剩余风险 | 建议 |
|---|---|---|---|
| A. 保留 JSON，修状态机、稳定幂等键、共享锁，扫描待处理集合 | 快速修漏发、遗漏、单进程重入 | 崩溃恢复协议仍需明确；历史越多扫描越慢；锁不覆盖其他进程 | **优先作为最小修复** |
| B. JSON历史 + 持久化待处理索引 | 历史查询和恢复查询分离；减少热路径全扫描 | 索引与历史可能不一致；必须可重建，又增加一个恢复协议 | 小规模、单进程、重视文件可读性时考虑 |
| C. SQLite存定义/Run/待投递记录，唯一触发键 + 事务 | 查询、唯一性、原子状态推进更自然 | 迁移/备份/异步访问需要设计；Task仍在JSON时跨存储断点没有自动消失 | 长期运行、多实例或高历史量时更合适 |
| D. 外部队列/分布式调度框架 | 分布式容量和租约能力 | 运维、打包、开发复杂度大幅上升 | 当前证据不足以推荐 |

**推荐顺序：A → 根据真实规模决定 C。** B 看似折中，但可能为简单文件系统引入第二套一致性协议，不一定比 SQLite 更简单。选择 C 时优先把 Run 派发意图与待投递状态放进事务，同时继续通过 Task 幂等接口跨越存储边界。

## 模块级建议

### tools/automation.py

保留三个模型可见工具作为薄适配器。把 Automation 数据模型、Schedule、存取和调度移到 `automation/`，让 HTTP/工具共同调用同一个应用服务。当前 `automation.pipeline` 反向导入 `tools.automation` 的业务模型，迫使工具层承担领域依赖。

合理的第一轮拆分是 `models.py`、`store.py`、`scheduler.py`；暂不增加 repository 基类、通用事件总线或复杂依赖注入容器。拆分本身不解决 A01–A03，必须先建立回归测试。

### automation/pipeline.py

保留预取→入队与执行结果→投递两个明确用例。飞书入站会话桥接另放一个模块，避免把 Thread 生命周期混进通用调度。

`DeliverySink` 已经够用；若新增渠道导致分支持续增长，再用简单 mode→factory 映射。重试要有下一次时间和最终结果，不要覆盖执行错误来记录投递错误；现在达到重试上限时写 `run.error` 会模糊两类失败。

### automation/inbox.py

收件箱查询和发送渠道分开。账号选择、网络超时、Token 缓存和日期窗口需要有明确输入，不应在每一步重复发现全局配置。先修缓存与超时，不必一次性改造成渠道插件平台。

飞书 JSONL 当前全量读入，再筛选时间窗口，随着历史增长会增加内存与解析成本。可先按日期分文件或流式读取；不应把“加 async”误认为去掉了同步成本。摘要也应设置条数/字符预算，避免每封邮件都被无上限地拼进提示词。

`_window_bounds` 使用主机时区而非 Automation 的显式时区，两者可以不同。需要明确“local”指用户、任务还是主机。具体夏令时/邮件服务器日期边界尚未验证，不列为已确认协议缺陷。

### automation/delivery.py

保留统一格式化入口和面向用户的错误描述。删除或收紧会丢正文的启发式抽取；把配置校验与正文展示从同一文件中分离到模型与格式化模块。

`bool(raw.get("best_effort"))` 会把字符串 `"false"` 解释为真，应由共享强类型输入模型校验。不要仅依赖某个入口的 Schema。

### automation/__init__.py

当前公开导入会提前加载 inbox 和 pipeline，并且说明仍引用已合并的旧模块。改职责时同步收紧公共导出并更新文档即可；这个问题没有独立重构优先级。

### 与 Task/权限体系的边界

后台执行硬编码 `allow_shell=True, auto_approve=True`；无值守自动化需要预授权能力，但这必须作为定义/执行策略的一部分持久化，而不只是分散的布尔默认值。这里只记录设计债，不在未完成权限调用链审核前宣称存在沙箱绕过。

TaskManager 通过 prompt 是否以 `[cron:` 开头决定 Cron 并发限额。这把用户内容当执行元数据，改提示词即可改变分类。建议在 Task 上显式记录 origin 与 automation_id，用户文字不参与资源调度判定。

## 建议的修复批次与验收

1. **恢复正确性**：修 A01、A02、A04，保留原输入输出结构。验收：终态零次投递能恢复；第101条未完成项仍被处理；超时通知恰当终结。
2. **派发幂等性**：明确单实例所有权，建立稳定 slot/run/task 映射。验收：在“保存意图/Task入队/保存关联/推进时间”每个断点注入失败，恢复后不丢任务且不重复创建 Task；双进程验证另列，不能以 asyncio.Lock 试验代替。
3. **网络与内容边界**：修 A05–A07、A09，补渠道配置校验与超时预算。验收：账号切换不串 Token；多段报告不丢正文；一个慢渠道不阻止其他到期任务。
4. **工作区和计时契约**：修 A08、A10、A11、A12，针对输入/时间/固定轮次补用例。
5. **按职责拆分**：保持三个工具 schema 与 HTTP 路由兼容；现有测试和新回归全部通过。
6. **按数据决定存储**：用真实历史量、单条记录大小与可接受事件循环延迟重测，决定是否迁移 SQLite。原型数据不能替代产品规模判断。

## 验证记录

现有测试：

```bash
.venv/bin/python -m pytest tests/test_automation_manager.py tests/test_automation_pipeline.py -q
# 38 passed
.venv/bin/python -m pytest tests/test_cron_tools.py tests/test_delivery_format.py tests/test_durable_resume_trigger_api.py -q
# 28 passed
```

共 **66 passed**。没有跑全仓测试，也没有调用真实模型、邮件、飞书、企业微信。

新增审核工件：

- [automation_probe.py](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/automation_probe.py)：9 组问题现象与一个共享锁对照，均在临时目录/模拟端运行。断言确认的是当前缺陷现象，脚本成功不表示业务正确；正式修复时应转成期望正确行为的回归测试。
- [automation_bench.py](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/automation_bench.py)：JSON扫描与SQLite索引读路径的最小原型对比。

```bash
PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/automation_probe.py
PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/automation_bench.py
```

最先值得投入的工作是补全恢复状态机，而不是先把1602行文件拆得漂亮。结构改进应该让这些保证更容易表达、测试和维护。
