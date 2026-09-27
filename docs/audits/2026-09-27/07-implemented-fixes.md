# 第七篇 · Goal 优化实施记录

日期：2026-09-27。基于当前工作区，保留已有 Goal/Workbench/其他审核改动。原问题描述留在 [第七篇审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-goal.md)，本文件说明实际实施范围与边界。

## 实施状态

| 问题 | 本轮行为 | 状态与取舍 |
|---|---|---|
| G01 无关成功可支持完成 | exec_shell 的 pwd/whoami/hostname/date/echo/printf/true 开头命令不再计为 verification；记录输出前 512 字符与完整输出 SHA-256，供审核引用 | **局部加固**：封住裸 pwd 反例，不能证明通用语义覆盖。命令包装可绕过分类，复合命令以这些词开头也可能被保守排除；不能当安全沙箱或任务验收器 |
| G02 指纹遗漏权限 | 哈希纳入文件类型与执行权限位；扫描前后校验 mtime、ctime、大小、mode、inode，发现变化拒绝该快照 | 已修复 chmod 反例；不声称目录扫描成为原子事务，Git 忽略产物与外部环境仍需单独验收 |
| G03 快照共享审核内容 | snapshot、dump、restore，以及快照序列化均深拷贝 completion_audit | 已修复嵌套 checks 被外部修改反向污染状态的问题 |
| G04 数字解析异常 | 统一有界正整数解析，命令接受最多 18 位 ASCII 十进制，拒绝零和非 ASCII 数字 | 三个数字入口均返回语法错误对象；合法数字不会触发 Python 的超长转换异常 |
| G05 晋升恢复 | 新目标持久化 queue_item_id；运行时创建下一目标时绑定队列 ID，回合认领时幂等确认移除。complete + queue 可通过用户 /goal resume 启动下一项；已创建目标恢复后继续同一 goal_id | 重启仍暂停，不自动开跑；覆盖完成后、创建后、认领后恢复。不承诺跨进程事务或外部工具副作用恰好一次 |
| G06 失败证据无限累积 | 近期 80 条外，最多保留 256 条未解决失败。超限暂停，设置持久化 evidence_overflow，禁止 resume/complete；恢复超量旧状态也标记不完整 | **有界且失败关闭**：不会因遗失失败而放行完成。需要用户检查原会话记录后创建替代目标；尚未建立可增量查询的历史证据库 |
| G07 控制操作整仓扫描 | CreateGoal/GetGoal/SetGoalBudget/checklist，以及非 complete 的 UpdateGoal 不再扫描；工作工具和完成边界仍扫描。增加扫描文件数、读取字节和耗时的 debug 记录 | 减少纯控制成本，未新增易失效的内容缓存。工作工具前后整仓读取仍存在 |
| G08 三轮阻塞提示 | 服务注释明确：三轮是模型对同一阻塞的语义判断指导，mark_blocked 本身不执行机械计数 | **契约澄清**，不是新增硬门槛。没有用总 turn 数冒充同一阻塞的出现次数 |

另将超长 completion criterion 从静默截断改为显式拒绝，避免丢掉用户验收约束。Goal dump 增加 schema_version=2、queue_item_id、evidence_overflow；旧文件仍按缺省值读取。此版本字段是格式标记，尚非完整的未来版本迁移/拒绝框架。

实现入口：[service.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py)、[state.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/state.py)、[types.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/types.py)、[persist.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/persist.py)、[commands.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/commands.py)、[workspace.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/workspace.py)、[Engine 晋升](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py)、[工具执行](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py)。

## 方案选择

- **快照隔离**选择边界深拷贝，没有将整个领域对象改为递归不可变类型。
- **恢复**选择用户显式继续和队列项身份绑定，没有在重启后自行启动模型。原 completed 目标和 queue 都存在时可恢复晋升；新目标已经持久化时复用其 goal_id。持久化调用仍依赖原有宿主回调，本轮没有新增日志事务层。
- **证据容量**选择显式暂停而非静默淘汰失败。固定容量针对内部索引，不修改用户 token/turn/time 预算。这个保守选择会让极端失败序列需要人工整理；未来证据日志方案可以替代此停止边界，但必须验证缺失日志时不会误完成。
- **完成语义**未引入一个自评模型来宣称所有任务已可自动验收。当前分类只改善已知弱证据的使用，后续仍推荐与需求绑定的测试结果、产物引用和领域验收器。研究和文字交付依然允许读取/来源记录作为证据，是否足以覆盖需求仍需审查。

## 最小横向对比

8MiB 合成文件集、10 组交替执行。当前侧使用真实 Engine 的 GetGoal 执行入口；对照侧在同一入口前后补上旧方案的两次完整扫描。两侧均断言工具返回成功。

| 方案 | 中位耗时 |
|---|---:|
| 原扫描方式模型 | 17.693ms |
| 当前控制入口 | 0.134ms |

这是控制操作的离线局部对比，不是整个 Goal 吞吐提升，也不是旧提交的完整引擎重放。实际验证工具仍保留扫描成本。

[脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/goal_compare.py) · [数据](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/goal-compare-results.json)

## 验证

新增 [16 项 Goal 回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/goal/test_audit_07.py)，覆盖非法数字、chmod、快照/dump/restore 隔离、三个晋升恢复阶段、pwd 拒绝、证据溢出、控制操作免扫描、超长验收准则、重排队列的身份确认和文档类正向证据。

相关测试合计 **408 passed**，包含 Goal、Engine、状态、文件上下文、粘贴、媒体、会话恢复及此前审核回归。两个既有测试替身补齐了 conversation 字段和虚拟客户端，保留原断言；没有通过修改产品逻辑去避开这些夹具问题。

编译、相关 Ruff F 与 diff 空白检查通过。没有真实模型调用、没有完整桌面构建。历史 goal_probe.py 描述修复前行为，当前 pwd 反例会被拒绝；不要把旧探针当成当前成功测试执行。具体命令见 [验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-validation.json)。

后续已交付 [第八篇：状态、上下文持久化与媒体](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/08-state-media.md)。
