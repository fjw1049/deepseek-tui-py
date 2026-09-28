# 第十五篇修复记录：TUI 生命周期、会话与呈现

日期：2026-09-28。对应 [原审核](15-tui.md) 的 T01—T12；本轮修复已落到代码和回归测试。原审核与旧探针保留为修复前证据。没有提交或推送，工作区中此前各篇的改动保持不变。

## 逐项结果

| 编号 | 本轮落地 | 验证与边界 |
|---|---|---|
| T01 | 会话切换前统一检查活动回合、队列、后台 Shell、Agent/Task 和命令；跨工作区或 provider 恢复明确拒绝；TUI 持有 ThreadLease，删除/归档检查占用。 | 跨工作区恢复不替换消息；排队期间新建被拒绝；两个运行时竞争同一租约。未实现跨工作区重建 Engine。 |
| T02 | 增加可 await 的命令入口和命令归属；压缩提交前检查 Engine、会话 ID 和原消息；provider/endpoint 切换检查空闲，构建失败回滚，复用 Engine 的路由设置。 | 暂停压缩后插入消息，旧结果被丢弃；provider 构建失败配置恢复；旧客户端关闭任务受退出流程管理。 |
| T03 | 统一异步退出；先等待命令和生产任务停止，再关闭 Engine、释放租约。启动失败回收已创建资源；原生卸载也走同一流程。 | 无窗口测试验证先停止 producer 后关闭资源、重复退出只关闭一次、启动失败关闭 client。session_end 交由 Engine，移除 App 的重复调用。 |
| T04 | 配置设置复用 state.secrets 的结构化、带锁和原子写入入口；API key 走已有凭据接口，返回值不回显密钥。 | 同名 TOML 表字段互不覆盖，包含引号的值可重新解析，嵌套 ui.locale 正确写入。不是保留原 TOML 注释的编辑器。 |
| T05 | 一个事件消费者随 Engine 持续运行，完成/取消只结束回合视图；失败完成保留错误；Agent 卡片索引跨回合保留，终态拒绝迟到进度。 | 完成后后台事件仍可见，失败状态不被成功提示覆盖；终态重放测试。旧事件通过切换前清空工作边界隔离，尚未引入全协议世代号。 |
| T06 | `/clear` 等待真实动作；`/export` 输出实际历史文本；退出命令进入资源清理；纠正 Esc-Esc 与 onboarding 的未实现回退提示。 | 清空动作确实被 await，导出包含可见消息。完整回合 rewind 未接通；`/undo` 仍只代表已有的工具撤销。 |
| T07 | 流式过滤导致已显示前缀变化时，替换助手控件内容。 | 59 个分片位置验证最终结果与完整过滤一致。全量正则扫描仍存在，未宣称增量过滤或零闪现已实现。 |
| T08 | Diff 解析按 hunk 行数消费正文，在文件边界识别 header。 | 正文恰为 `--- old` / `+++ new` 时仍得到一个文件、各一行增删；已有展示测试通过。 |
| T09 | 转义 Agent 卡片、侧栏、状态等动态插值；picker 使用纯文本标签。 | Rich 孤立闭标签不再抛错；仍保留固定样式模板。 |
| T10 | 文件 picker 使用剪枝遍历、实际应用 glob、达到上限即返回；后台加载。复用线程 store，一次聚合 turn 数量。部分 I/O 命令后台执行；外部编辑器 suspend 终端并正确拆分带引号参数。 | 3 个线程、9 条记录：原查询读取 27 次，聚合读取 9 次，结果相同。工作线程取消时等它完成后再释放所有者。FileMention 单目录扫描与部分存储操作仍同步。 |
| T11 | onboarding 先保存 key 再写完成标记；缺少 key 时可再次引导；工厂允许的免 key provider 不被前置拦截。 | 替身测试验证保存顺序，不写真实凭据、不调用真实模型。 |
| T12 | 清理旧压缩摘要、goal、计划批准、读文件指纹、工具快照、成本与展示状态；恢复和导出共用消息投影；审批取消使对应 modal 失效。 | 隐藏内部消息，保留图片/工具占位；有另一弹窗覆盖时不误关闭它，过期审批在恢复前台时退出。 |

## 实现位置

生命周期及会话入口：[app.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/app.py)、[lifecycle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/lifecycle.py)。命令：[commands.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/commands.py)。恢复及弹窗：[session_restore.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/session_restore.py)、[dialogs.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tui/dialogs.py)。其余呈现修改限于 input、transcript、cards、tool_cell、sidebar、status、onboarding。

相邻边界只增加 EngineHandle 的队列查询和 RuntimeThreadStore 的计数聚合，没有再造事件总线、通用任务框架或另一套配置存储。

## 验证

[回归测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_audit_15.py) 先在修复前运行：32 失败、36 通过；随后增加生命周期和边界测试。修复后扩展回归 **308 通过**，范围包括该文件、TUI/presentation、Agent 展示、审批、持久化、恢复、多 provider、上一篇协议回归和 goal 测试。

新增文件通过 Ruff；TUI/Handle 的 `F,E9` 检查排除历史已有的 `F541` 后通过。该 F541 位于 tool_cell 的无插值 f-string，HEAD 中也存在，没有顺手清理。修改的生产文件通过编译检查，`git diff --check` 通过。具体命令见 [验证记录](15-fixes-validation.json)。这不是全仓库测试通过声明，也没有真实终端、外部编辑器、在线 provider 的端到端验证。

## 后续边界

关闭流程会等待已经进入线程的 I/O；不能保证任意第三方阻塞操作都能立即结束。流式 sanitizer 的累计扫描复杂度、FileMention 大目录同步枚举、完整回合 rewind、跨工作区 Engine 重建仍是独立后续项。T10 的聚合计数为一次全表扫描，历史量继续增长时才考虑持久索引。

接续：[第十六篇：内置工具](16-builtin-tools.md)，本轮仅审核，不混入新的工具行为修复。
