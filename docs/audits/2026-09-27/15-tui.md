# 第十五篇：TUI 生命周期、会话切换与交互呈现

更新：本篇记录修复前状态。2026-09-28 已落实 T01—T12 的最小修复，详见 [修复记录](15-implemented-fixes.md) 与 [验证结果](15-fixes-validation.json)。完整回合回退、增量过滤、跨工作区 Engine 重建等边界仍见修复记录，不代表全部扩展建议已实现。

日期：2026-09-28。接续第十四篇修复，本篇按业务链审查 `tui/` 的 **16 个 Python 模块，9,121 行**。覆盖各模块的入口、核心状态转换和相邻调用：启动/退出、会话切换、命令分发、审批/计划、事件消费、流式文本、工具/Agent 卡片、侧栏与配置。行数表示源文件范围，不表示所有路径已经动态覆盖。插件安装、文件存储、Engine 内部只追踪边界，不重复宣称重新完整审核。

本篇 **未修改 TUI 生产代码**。A＝本地可执行探针复现；B＝实现与调用链确认；C＝设计建议/扩展风险。探针断言用于记录缺陷现状，不能直接当成期望行为回归；后续修复需反转这些断言。

总体判断：`plan.py`、`cards.py` 把选择/状态与 Textual 控件分离，工具展示也有独立分类与模型，这些结构应保留。当前主要问题集中在 App 与命令层同时拥有 Engine 的可变会话、客户端和任务生命周期；事件消费又绑定于一次提交，跟后台任务的生命周期不一致。优先明确谁负责这些状态，再讨论拆文件和插件化 UI。

## T01 · P1：切换会话没有绑定工作目录，也没有运行中隔离（B）

位置：[app.py:373](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:373)、[app.py:1005](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:1005)、[app.py:1220](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:1220)。

`_load_runtime_thread` 从全局线程库载入任意 thread，替换消息、会话 ID、model、mode，却没有切换或核对 `thread.workspace` 与 `engine.tool_context.working_directory`。从 A 项目打开 B 项目历史后，文字显示 B 的会话，工具仍操作 A 的目录。这里不能仅改 cwd：权限根、插件上下文和 checkpoint 也属于工作区。

新建/加载会话也不等待当前 turn 停止；`action_new_session` 清空消息并换 ID，而旧回合仍持有自己的 working_messages，完成后可能回写旧结果。侧栏删除直接调用 `delete_thread_tree`，绕过 manager 的线程占用检查；文件存储锁只保护单次存储操作，不能代表活跃会话租约。

**建议**：第一步对运行中切换明确拒绝或经同一取消并等待路径执行；跨工作区恢复先拒绝并给出目标路径。新会话应统一清理 goal、压缩记忆、计数、UI 状态，而非只清消息。随后再把线程加载/删除和 lease 所有权收敛到一个会话服务。不要在 UI 回调里直接更改几个 Engine 字段就声称完成迁移。

验收：A/B 两个临时工作区；B 历史不能静默在 A 执行工具；暂停旧 turn 后新建/加载，迟到结果不进入新会话；另一运行时持有租约时删除失败且历史不变。当前尚未做真实文件写错目录的破坏性试验，结论来自字段和调用链。

## T02 · P1：异步命令绕开 Engine 顺序控制，会覆盖新增消息或关闭仍在使用的客户端（A/B）

位置：[commands.py:1527](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/commands.py:1527)、[commands.py:438](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/commands.py:438)。

`/compact` 拷贝消息后 await 压缩，然后把结果直接写回 `engine.session_messages[:]`。探针暂停压缩、追加一条消息再放行，新增消息确定丢失。任务由 `ensure_future` 启动，没有保存归属，也没有与回合、切换、退出协调。

`/provider` 直接替换 engine/turn_loop 的 client，并异步关闭旧 client，没有检查活动回合和子 Agent。提示声称正在运行的 Agent 保留旧 client，但旧 client 随后被关闭；是否影响某个子 Agent 取决于它是否共享该实例，不能仅靠提示保证。构建新 client 抛错时，先改的 config 也没有完整回滚。

**建议**：先使用一个统一命令执行入口，能够 await 同步/异步结果，并把 compact/provider 归入串行会话操作；忙碌时拒绝是最小方案。仅给 compact 加版本号可以防止覆盖，但解决不了 provider 和会话切换，因此作为补充，而非唯一措施。不要立刻把所有展示命令排入 Engine 队列。

验收：压缩期间提交、切换、取消；建 client 失败后 config/Engine 一致；旧实例在最后一个使用者结束后关闭一次；所有后台命令异常被观察。

## T03 · P1：退出入口和资源关闭顺序不统一（A/B）

位置：[app.py:1036](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:1036)、[app.py:604](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:604)、[app.py:987](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:987)、[app.py:215](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:215)。

`action_quit` 先执行 session_end，再调用 Engine.shutdown；后者经 shutdown_session 又执行一次 session_end。随后才取消 `_engine_task`，意味着生产任务停止前先关闭其依赖。close 抛错则后续取消/退出可能不执行。探针使用明确标注的 Engine 替身，记录为两次 hook → 资源关闭 → producer 停止；真实 Engine 的重复 hook 由调用链确认。

Slash `/exit` 和命令面板直接 `self.exit()`，不进入上述清理；原生框架 worker 的退出也不能替代对原始 `asyncio.create_task(engine.run())` 的所有权管理。启动中在 Engine 创建成功后发生异常时，catch 把 engine/task 引用置空，未收拢已经创建的资源。

**建议**：App 持有一个可重复等待的关闭流程，各出口都调用它；停止接收操作 → 取消并等待生产任务/命令 → 关闭 Engine → 退出。session_end 交给现有 Engine 所有者。启动用局部变量和 finally/退出栈，只有成功才转交所有权。已有 server/lifecycle 处理的是服务任务，不应为复用而让 TUI 依赖 HTTP 层。

Textual 本地安装源码还确认 `exclusive=True` 按 `group` 取消同组 worker，`name` 不能隔离。当前 startup/listener 未显式分组，后续应分别设置；不把这一点描述成已经通过完整启动 E2E 复现的丢任务事故。

## T04 · P1：配置按行改写破坏 TOML 表语义（A）

位置：[commands.py:937](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/commands.py:937)。

`_config_write` 不识别 TOML 表，遇到同名行全部替换。探针中 `/config set model=changed` 同时更改根 model 和 `[providers.demo].model`；新增 locale 追加在文件末尾，实际落入 provider 表。`_toml_value` 不转义引号，`quote"break` 写成非法 TOML。write_text 也没有原子替换。

**建议**：复用配置层的解析/序列化与原子发布入口，先明确定义支持哪些路径。最小实现只允许已知顶层键及明确指定的嵌套路径，校验完成后再落盘。需要保留注释时选 TOML 编辑库；不要求保留注释时使用现有结构化写入即可。禁止继续补更多字符串匹配分支。

验收：同名键位于不同表；引号/反斜杠/Unicode；新增、删除、写入失败；失败时原配置仍可读取。所有探针写入临时目录，没有改用户配置。

## T05 · P2：事件监听随前台回合结束，后台结果没有及时消费（A/B）

位置：[app.py:558](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:558)、[app.py:676](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:676)、[app.py:793](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:793)。

监听器只在用户提交后启动，遇到 TurnComplete/TurnCancelled 就 break。TurnComplete 明明提示后台结果稍后到达，却已经停止消费。探针送入完成事件和紧接着的 SessionActivityEvent，调用结束后后者仍在队列，直到下一次启动监听才处理。Goal 隐藏续轮、后台 Agent 消息和启动期间排队的多条提交都有同类边界。

`TurnCompleteEvent.success/error_message` 也没有参与最终状态，先前 error 文案可以被改回 ready，完成通知不能区分失败。`cards.apply_to_delegate` 则允许迟到 PROGRESS 将 COMPLETED 改为 RUNNING；探针能直接复现，但尚未证明当前有序生产路径频繁产生这种逆序。Transcript 在 finalize 时清掉 Agent 卡片索引，也妨碍跨回合更新。

**建议**：Engine 存活期间保持一个事件消费者；回合结束只收尾回合视图。会话切换用世代/身份过滤旧事件。Agent 状态依独立生命周期保存，终态重放幂等；若支持重启任务，明确新世代。先做一个常驻消费者，不引入通用 pub/sub 框架。

验收：无新用户输入时后台完成可见；两个连续 turn 都收尾；取消后仍可显示背景状态；失败完成保留失败状态；事件循环关闭无残留任务。

## T06 · P2：部分命令/快捷键给出的能力超过实际执行（A/B）

位置：[commands.py:309](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/commands.py:309)、[commands.py:902](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/commands.py:902)、[app.py:1192](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:1192)。

`/clear` 同步调用异步 action_new_session，未 await；探针获得“Conversation cleared.”，实际调用数为 0，并有 coroutine never awaited 警告。`/export` 只写标题、时间和占位句，文件不包含已有会话。Esc-Esc 有纯状态机，但 App 只显示 depth 状态，没有绑定选择/确认到实际 rewind；这是源注释承认的简化，仍与 onboarding 的 backtrack 提示不符。

**建议**：统一异步 command dispatch 后让 `/clear` 返回真实完成结果。`/export` 复用规范消息投影输出，至少包含用户与助手文本，并说明图片/工具细节的支持范围。回退先接已有恢复服务；接通前文案明确为未实现，不能把 `/undo` 单工具撤销当作完整回合回退。

## T07 · P2：流式过滤修改了旧前缀，控件却只追加（A）

位置：[transcript.py:608](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/transcript.py:608)、[sanitize.py:9](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/sanitize.py:9)。

分两片输入 `hi <deepseek:sub` 和 `agent.done>secret</deepseek:subagent.done>bye`：完整过滤结果应是 `hi bye`，实际控件成为 `hi <deepseek:subhi bye`。代码发现新内容不是旧内容前缀时，把完整过滤结果再次 append；已显示的半个标签没有撤回。

每个 delta 还会扫描整个累计 buffer；固定小 chunk 的长文本总扫描量随长度近似平方增长。FrameRateLimiter 只约束后续渲染，并不限制这次正则扫描，不能拿 120 FPS 配置当作预算保护。

**建议分两步**：先提供 replace_content，在前缀回退时替换控件，修复重复；若要求半个内部标签从不短暂可见，再用保留可能标签前缀的增量过滤器。增量方案更复杂，应验证不同 chunk 切分等价后再采用。没有依据本次探针宣称已测到真实终端卡顿时间。

验收：对每个标签切分位置组合测试，流式结果等于一次过滤；多个标签、未闭合标签、普通 `<` 正文；长输出按扫描字节数和渲染耗时分别测量。

## T08 · P2：Diff 正文被当作新文件头（A）

位置：[tool_cell.py:463](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/tool_cell.py:463)。

解析器在判断 hunk 正文前匹配 `--- ` / `+++ `。合法 diff 删除 `-- old`、新增 `++ new` 时，对应行正好是 `--- old` / `+++ new`，被识别成第二个文件。探针得到 2 个文件且 0 增删，实际应为 1 个文件、各 1 行增删。这影响用户核对变更，不涉及真实文件修改。

**建议**：根据 hunk old_count/new_count 消费正文，仅在文件边界解析头部，并重置 hunk。如果必须完整支持 rename、binary 和复杂 Git 扩展，再选成熟解析器；当前先修小状态机足够。验收同时覆盖零行 hunk、多文件、无末尾换行标记及正文恰似 header。

## T09 · P2：外部字符串与 Rich markup 边界不一致（A/B）

位置：[cards.py:97](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/cards.py:97)、[sidebar.py:81](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/sidebar.py:81)、[dialogs.py:268](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/dialogs.py:268)、[status.py:151](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/status.py:151)。

Transcript 用户消息与审批/输入问题已经 escape，Agent summary/actions、侧栏 title、picker label、状态 model 等仍直接插入 markup。探针让卡片 summary 为 `[/unknown]`，Rich 解析抛 MarkupError。常见 `[red]` 一类正文也可能被吞掉或改变样式。这是显示可靠性问题，不将其夸大为任意代码执行。

**建议**：动态文本使用 `Text(text, style=...)` 或对插入片段统一 escape；保留固定模板标记。不要给已经是 Text 的对象再次 escape，否则可能显示转义字符。验收覆盖合法方括号、孤立闭标签、路径和模型名，且原文可复制。

## T10 · P2：UI 线程同步扫描/进程调用，返回条数上限不能限制工作量（A/B）

位置：[dialogs.py:357](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/dialogs.py:357)、[app.py:463](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:463)、[input.py:212](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/input.py:212)、[commands.py:1568](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/commands.py:1568)。

FilePicker 先 `sorted(workspace.rglob('*'))` 再截 500，排除目录只在遍历后过滤，而且 glob_pattern 参数完全没用。探针设置 max_files=1，仍枚举 1000 个路径；指定 *.py 仍返回 txt。FileMention 是单层 scandir，不把它误写成递归全盘扫描，但每次输入也会同步遍历排序该层。

侧栏刷新每次构造 RuntimeThreadStore，再对最多 50 个 thread 分别扫描所有 turn 文件；构造器还扫描全部事件日志恢复高水位并写 state。这里包含第十三篇正确性修复带来的构造成本：需要在 TUI 复用 store，并把迁移/恢复和常规查询区别开，不能为提速删掉高水位保护。

外部编辑器用同步 subprocess.run，未 suspend Textual；等待编辑器期间整个 asyncio 循环无法推进。`/diff` 最长同步等 10 秒；技能远程/插件安装等同步 handler 也执行 I/O。FilePicker 和 `/diff` 默认进程 cwd，与 Engine 工作区不一定一致。

**建议**：文件枚举尽早剪枝、真正应用 glob，再限制数量；后台加载且丢弃旧查询结果。线程列表一次聚合计数或添加索引，先避免 50 次全表扫描。外部编辑器使用框架终端挂起能力并处理带引号的 editor 参数。移动工作到线程时仍需任务归属和取消收尾，不能用“fire-and-forget”遮盖问题。

## T11 · P2：Onboarding 标记完成，但 API key 未持久保存（B）

位置：[onboarding.py:75](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/onboarding.py:75)、[app.py:246](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py:246)。

Screen 约定调用者保存 key，界面也说 save；App 回调只设置内存 config.api_key，写 .onboarded 标记并重启 Engine，未写凭据存储。下次进程启动 key 丢失，但 marker 已存在，不再弹 onboarding。用户会得到已完成设置却无法使用的状态。

**建议**：调用现有 auth/config 层的凭据保存接口，成功后再标记完成；若只支持本次会话，明确临时且不要据此永久抑制引导。测试仅用假 key 和临时配置，不做真实凭据操作。这里不建议在 TUI 另造加密/凭据系统。

## T12 · P2：恢复投影没有完整清理旧状态，历史也不等价于现场显示（A/B）

位置：[session_restore.py:46](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/session_restore.py:46)、[transcript.py:906](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/transcript.py:906)、[session_restore.py:148](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/session_restore.py:148)。

`apply_messages_to_engine` 只在新历史带 bridge 时设置 `_compaction_summary_prompt`，不带 bridge 时遗留旧会话摘要；探针确认切换后仍为 old session summary。新会话清理同样缺少统一状态集合，属于 T01 的另一表现。

`hydrate_from_messages` 只看 TextBlock 和 role：图片/工具/思考块没有投影，纯图片消息消失；也不区分 REAL_USER 与 SYSTEM_REMINDER/GOAL_CONTINUATION，隐藏续轮可显示成人类输入。不是所有历史控件都必须复原，但应明确省略并保留来源。

审批 handler 等待 Future 被取消时没有 finally 撤掉对应 modal。没有证明每次取消都会造成操作误授权，但可能留下已经没有等待者的审批窗口；后续以 headless UI 测试核对屏幕栈。

**建议**：先原子准备恢复状态，再一次替换；缺失 summary 应显式清空。抽取纯消息→展示项投影，现场与恢复共用来源/图片/工具规则；无需先把完整 EngineEvent 存进 UI。审批取消只撤销自己持有的弹窗，不能无条件 pop 顶层用户窗口。

## 逐模块建议

| 模块（行数） | 通用性、边界与保留项 | 优先建议 |
|---|---|---|
| `__init__.py`（1） | 空包入口，没有额外初始化副作用。 | 保持简单，不增加自动注册。 |
| `app.py`（1439） | 单入口聚合合理，但同时掌管资源、会话字段、事件与存储；目前不是完整的生命周期所有者。 | T01/T03/T05；先明确常驻消费者和会话操作入口，再按职责拆，不能只拆出多个 mixin。 |
| `commands.py`（2047） | registry/resolve/结果对象可复用；同步 handler 契约与异步业务冲突，直接接触 Engine 私有方法。 | T02/T04/T06；统一 await 与任务归属，保留只读命令简单实现。插件命令继续使用既有发现层。 |
| `dialogs.py`（827） | 审批和多问题 state 可脱离 UI 验证，动态审批文案已 escape。 | T09/T10；picker 数据提供者和控件分开，实际应用参数；暂不抽万能弹窗框架。 |
| `input.py`（375） | 输入、粘贴、防误发送和工作区解析已有独立函数。 | T10；编辑器等待不能阻塞事件循环；补完整快捷键交互测试。 |
| `transcript.py`（963） | 多类 cell 与工具折叠边界清晰，但既管流缓冲又管历史投影和生命周期。 | T05/T07/T12；先修内容替换与恢复投影，再考虑拆分。show_thinking=False 目前仍有流中统计提示，结束才隐藏，不是推理正文泄漏。 |
| `sanitize.py`（20） | 完整字符串过滤小而明确。 | T07；保留纯函数作为基准，增量过滤若引入须与其等价。别堆更多全量正则掩盖分片状态。 |
| `tool_cell.py`（598） | inline/block 复用 ToolDisplay，状态和结果展示集中，兼容旧别名成本低。 | T08/T09；修 diff 边界，未知工具文本按正文渲染。更完整 Git diff 支持才考虑外部解析器。 |
| `tool_classify.py`（139） | 不可变 ToolDisplay、未知工具 fallback 合理。 | 与 presentation 的“语义分类”不同，不应强合并两个 enum；未来从工具元数据提供展示提示时保留默认表。暂未发现需独立高优修复的问题。 |
| `cards.py`（564） | DelegateCard、PagerState 与控件分离值得保留，动作列表有界。 | T05/T09；终态与动态文案先修，重放/重启世代再按真实需求引入。 |
| `sidebar.py`（948） | DTO、任务/Agent 过滤函数独立，可单测；实际慢查询在 app/store。 | T09/T10；让控件消费快照，避免把存储扫描下沉进控件；删除/归档应走同一会话服务。 |
| `status.py`（347） | monotonic 时钟限帧、OSC8 处理与状态渲染可分别验证。 | T09；动态状态/模型文本安全构造；不把限帧当流解析限流。没有必要新建通用动画引擎。 |
| `session_restore.py`（185） | 解析与 metadata fallback 集中，适合继续收敛恢复协议。 | T12；明确完整替换/合并契约；审批 Future 与 modal 一起收尾，未来可再拆审批适配器。 |
| `plan.py`（350） | 纯选择状态机、边界约束、枚举结果利于扩展。 | 保留；问题主要在 T06 的 App 接线。自定义 options 与固定字母快捷键不完全通用，仅在真有可变选项需求时处理。 |
| `onboarding.py`（186） | 三步流程和 key masking 简单清晰，屏幕不应拥有存储。 | T11；由调用者兑现保存约定；修正文件头与项目本地 marker 的文档描述。 |
| `notifications.py`（132） | 可注入 bytes sink，可在不操作真实终端的情况下测试，阈值与方式独立。 | 保留；先由事件路由区分成功/失败通知。当前生产调用是固定 done 文本，不将通用 msg 参数推断成已证实的终端注入。 |

## 最小方案横向比较

| 决策 | 方案 A | 方案 B | 本阶段建议 |
|---|---|---|---|
| 会话写操作 | 忙碌时拒绝，经统一 async 入口 await | 全部 Engine 操作命令化并支持队列/版本 | 先 A 修丢数据和资源顺序；确需排队后再 B，保留可迁移接口。 |
| 事件消费 | 一个 Engine 生命周期内的常驻 listener | 每个 turn 启停 listener 并额外背景 listener | A。B 会制造竞争消费和交接窗口。 |
| 文本过滤 | 前缀改变时替换 cell | 有限状态增量过滤、保留标签前缀 | 先 A 修正确性；B 经分片等价/性能测试后上，A 仍可能短暂显示不完整标签。 |
| 目录选择 | 早剪枝 + worker 内有界遍历 | 全量索引、文件监控和缓存 | 先 A。当前 max=1 仍枚举 1000 的操作计数已经证明限制位置错误，无需先建索引服务。 |
| 配置编辑 | 结构化解析、校验、原子保存 | 保留注释的 TOML 文档编辑器 | 复用配置层；是否要保留注释决定选择，不继续行替换。 |

## 验证与实施顺序

可重跑 [tui_probe.py](tui_probe.py)，结果 [tui-probe-results.json](tui-probe-results.json)。全部使用临时文件、内存队列和受控 UI/Engine 替身，不调用模型、网络、真实编辑器或真实通知。记录 15 个结果字段，包含同一问题的多个表现，不把字段数当独立缺陷数。纯字符串、合法 diff 和 config 结果是直接执行；完整 Textual 终端/键盘端到端尚未覆盖。

既有 TUI/Agent 展示、审批、状态持久化、恢复定向测试 **39 passed，0.44 秒**；其中部分 smoke 仅检查源代码/接口存在，不能因通过而宣称交互闭环无误。第十四篇扩大回归包含相关 TUI，但两组有重叠，不相加。详情：[15-validation.json](15-validation.json)。

推荐下一轮顺序：先 T01–T04（会话与数据、任务、配置），再 T05/T06（事件与命令闭环），然后 T07–T12（文本/Diff、边界、I/O、引导与恢复）。每组先补预期行为测试再修，保持已有状态机和控件 API，避免同时重写全部 TUI。

修复本篇后，下一功能体系为 **第十六篇：内置工具的文件、搜索、Shell、Web 与参数校验**。
