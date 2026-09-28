# 第十六篇：内置工具修复记录

日期：2026-09-28。针对 [原审核](16-builtin-tools.md) N01—N11 做最小修复；历史探针和原验证数据保留，不改写成修复后的结果。未引入搜索服务、通用表单框架或新工具继承层。

## 修复与取舍

| 问题 | 本次行为 | 验证及保证边界 |
|---|---|---|
| N01 搜索路径 | 每个候选文件经 ToolContext 校验最终路径和敏感目标；合法仓库内链接保留，拒绝项计数。 | 临时真实链接验证越界、敏感别名、合法内部目标；resolve 与 open 之间仍有外部替换窗口。 |
| N02 文件版本 | ReadPage 携带同一次打开的前后 fstat；变化拒绝。记录读取版本，写前再核对；曾读取文件被删除视为过期。旧内容读取失败不再伪装文件不存在。写入 worker 取消后先等其收尾。 | 读取后变更、删除、阻塞写取消回归；原子 rename 防半写，不保证与外部编辑器的原子比较替换。取消落盘后的 mutation ledger 完整性仍需跨层验收。 |
| N03 工作量 | 已取得读取页后停止扫描，未扫完的 total_lines 为 None；无换行缓冲超过 1 MiB 明确失败。搜索增加 5 秒软期限、10 万遍历项和 64 MiB grep 总读取预算；file_search 达到 501 条就返回前 500 条及总数下界。路径建议最多评估 1000 项。 | 一行分页只读 64 KiB，不再扫描约 2 MiB 全文。grep 在预算内仍保留精确计数，超预算报错。os.walk/部分 Python 版本的 iterdir 底层枚举及阻塞文件系统调用不受硬期限抢占。 |
| N04 Shell 输出 | 管道 stdout/stderr 并行排空；PTY 共用 OutputCapture。每流内存头尾合计 64 KiB，超过后落盘，磁盘每流最多 8 MiB；失败或超限仍排空并明确输出丢失范围。PTY reader finally 关闭捕获文件和 master fd。 | 真实子进程双管道各 200 KB；模拟 PTY 1 MiB；缩小预算验证磁盘限额，目录解析/写入失败仍持续采集。不是 OOM 压测，尚无全局磁盘总预算。 |
| N05 工具名/schema | 删除裸 x+hex 猜测解码，保留带分隔符的编码协议；序列化前深复制 schema。 | 合法工具名往返一致。选择最小严格协议方案，放弃修补模型漏写分隔符的裸转义；未增加注册表候选猜测。 |
| N06 ignore | 无效 gitignore 规则逐条跳过；用户无效 glob 转 ToolError。 | 坏字符范围不再中断其他规则；匹配器仍是现有 Git ignore 子集。 |
| N07 问题结构 | header/id/question、选项 label/description 必须非空白字符串，问题 ID 唯一，复制 options。 | 错类型、重复 ID、引用隔离回归；不增加通用表单系统。 |
| N08 Web | URL 只规范 scheme/host 和去片段，保留路径大小写、查询参数、www 和尾斜线；POST 响应限制 2 MiB；非法 JSON 转 ToolError；结果数和文本长度要求正数并设上限。 | MockTransport 验证大响应和非法 JSON，URL 身份用例通过；无真实网络试验，DNS 检查与连接之间的窗口未变。 |
| N09 PlanMode | 仅删除 SYSTEM_REMINDER 来源且带对应标记的提醒；审批答案接受稳定值/明确完整历史标签，移除子串式放行；计划读取限 1 MiB。 | 用户正文含同样提示不再误删，拒绝模糊或否定答案。仍使用 origin+marker，未迁移历史事件格式。 |
| N10 Knowledge | 计划先原子写盘再发布 metadata；纯计划解析移到 tools/plan_state，sidebar 保留兼容导出；Skill 正文限 1 MiB，伴随文件枚举限 1 万项/1000 文件，只枚举一次；Notes 说明与用户级共享存储一致。 | 写盘失败保留旧文件/内存；未改变 Notes 存储位置。计划落盘仍同步，超预算明确报错而非默默省略文件。 |
| N11 Checklist | Task 持久化改为直接 await，Engine 回合末同步同样等待；工具调用持久化失败恢复原 metadata，允许再次提交。 | 延迟写必须等完，失败后可重试；没有扩张成跨进程、跨文件分布式事务。 |

新模块：[output_capture.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/output_capture.py) 只负责有界输出收集；[plan_state.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/plan_state.py) 只负责纯计划状态解析。前者统一 Shell 两种执行方式，后者消除工具层反向依赖 Textual 的问题。

## 验证

最初新增复现测试 **13 失败、2 通过**。最终定向与扩展回归 **389 项通过**，包含文件、搜索、Web、计划、Checklist、后台任务、插件、TUI 既有回归和 Shell 超时转后台。详细命令及计数见 [验证记录](16-fixes-validation.json)，新增用例见 [test_audit_16.py](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_audit_16.py)。

新增模块/测试/本轮探针 Ruff 通过；受影响工具及调用边界 F/E9 检查、compileall、git diff --check 通过。未声称整个仓库通过所有风格规则或全量测试。

性能比较使用相同类别输入下的实际读取量和保留字节数：分页由全文约 2 MiB 降到一块 64 KiB；PTY 1 MiB 输出只保留 64 KiB 原始头尾和提示文字，完整输出在预算内落盘。字节量差异不等于运行速度倍数，落盘仍有 I/O 成本。

## 保留边界

- 外部写者的 TOCTOU、写入取消后文件与变更记录一致性，需要调用层事务设计；不把 fstat+rename 说成完整事务。
- OutputCapture 的小块写盘仍在事件循环中；每流限额不是全局磁盘限额。正常取消已有进程组收尾，直接取消 PTY reader 或进程硬退出尚无完整孤儿进程验收。
- 超长行采取有界报错；全量 grep 计数在预算内继续扫描。软超时不能中断一个卡住的文件系统调用。
- Task 回合末 reconciliation、其他写者与持久化之间的事务仍是单独边界；本次没有修改未被调用的 task/helpers 同名旧 helper。

下一体系已完成审核：[第十七篇：配置、CLI 与基础设施](17-config-cli.md)。其问题本轮记录，尚未修改生产实现。
