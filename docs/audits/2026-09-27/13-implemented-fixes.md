# 第十三篇修复记录：HTTP 服务、线程存储与事件流

日期：2026-09-28。对应 [13-server-threads.md](13-server-threads.md) 的本轮修复；历史探针及 `server-probe-results.json` 保留，不以修复后的输出覆盖历史证据。工作区此前的第十一、十二篇改动保持原样，未提交或推送。

## 实施结果

| 审核项 | 本轮实施 | 验证与准确边界 |
|---|---|---|
| S01 事件序号 | 使用存储目录外的 OS FileLease，把读 state、预留序号、追加事件串行化；每次预留原子落盘，事件 flush/fsync。构造时扫描旧日志恢复高水位，导入后同样恢复。保留实例内线程事件锁，避免并行广播倒序。 | 重启、两个 store、两个真实 Python 子进程并发验证；允许预留失败留下序号空洞，不允许成功事件复用序号。存量日志末尾半行与新事件分隔，坏行不吞掉后续事件。不是跨 runtime 的实时消息总线。 |
| S02 广播溢出 | 订阅先按 thread 过滤，溢出保留 lag 标记和首个被丢事件；从磁盘按当前游标补放，去掉重复；首个丢失事件已无法恢复时发送 `stream.resync_required` 并结束本次流。 | 容量 1 的跨线程过滤、溢出回放、缺失历史提示均有测试。客户端必须处理该控制事件并重取快照；此次未修改 Electron/其他客户端。并发压缩下任意历史缺口的完整检测仍需要日志 generation/低水位协议。 |
| S03 delta 完整性 | 不再把原始增量替换成 preview；实时和持久化均保留完整 payload。batch flush 仅移除已确认发送的内容，失败/未发送内容按旧→新顺序还原；保护整个 flush，取消不会重新发送已确认内容。延迟 flush 异常被观察并保留缓冲。 | 覆盖中途失败、发送期间新文本、重复取消、合批与并发 flush。旧日志中的截断 delta 返回重新同步提示。日志会比旧版大；显式压缩仍保留。写入完成但 OS 返回失败等不确定 I/O 不宣称 exactly-once。 |
| S04 ID 边界 | 六类记录路径共用 ID 校验，拒绝路径分隔符、点目录、NUL、冒号；拒绝存储子目录和记录叶子的符号链接；直接读取和 listing 校验记录 ID 与文件名一致。关联 ID 在保存时检查。 | 参数化路径逃逸测试及符号链接追加保护。模型仍不是跨记录事务；导入图校验另见 S05。 |
| S05 导入 | 解包后先校验声明目录、JSON/TOML、thread/turn/item 引用及 checkpoint 所属关系；对每个目标准备同文件系统 staging，完成后替换，发布失败按逆序回滚。回滚失败保留备份路径并记录错误。导入线程历史时拒绝持有 ThreadLease 的运行线程；store 记录操作与导入使用同一文件锁。 | 缺失目录的 replace 不删除旧数据，第二个目标发布失败还原第一个；已有 merge/replace 合约通过。checkpoint 的 `.raw` 附件随元数据复制。保证普通异常回滚，不保证进程被 kill/断电后的跨目录原子恢复；不对旧 TUI session 写入者承诺完整并发事务。媒体内容寻址写入可能留下无引用资产，不删除既有内容。 |
| S06 归档边界 | 导出/备份拒绝符号链接与特殊文件，导出使用独立临时 ZIP 并在失败后清理；拒绝把输出放在正在归档的源目录中。解包拒绝逃逸/重复路径/ZIP 链接，限制成员数、单成员及总解压字节，实际流式复制再次计数。 | 静态链接泄漏、越界路径、压缩内容大小限制有回归；普通备份/export/import 合约通过。限额为 100,000 个成员、单个 256 MiB、合计 2 GiB。没有在受恶意进程持续替换源目录的条件下证明无 TOCTOU，也未模拟磁盘耗尽的所有 OS 行为。 |
| S07 usage 锁 | 复用 OS FileLease；mtime 不再代表存活状态，不 unlink 锁文件；超时只是等待失败。 | 活持有者锁 mtime 改成过去，竞争者仍超时，释放后能重新取得。保留账本格式。 |
| S08 关闭归属 | manager 提供幂等可等待的 `aclose()`；阻止新 turn/engine，等待受保护变更，收拢加载和 warmup，停止引擎、唤醒 monitor 完成 turn 收尾，再关闭 session、provider 和释放 lease。LRU eviction 等待 engine/session。ASGI lifespan 与 HTTP finally 等待 manager；HTTP 初始化 worker 取消也先收拢。AppRuntime 用退出栈保证一个资源关闭失败不跳过后续资源。 | 测试关闭等待变更、客户端只关闭一次、monitor 先于 session 收尾、一个资源关闭失败仍关闭其他资源。外部注入 AppRuntime 的嵌入式调用方仍拥有该 runtime；CLI 创建的 runtime 由 CLI finally 关闭。不是对全部深层初始化失败和任意第三方永不返回 close 的形式化保证。 |
| S09 恢复取消 | 以 manager 持有的受保护任务覆盖整个 rewind/restore_code 和分享导入服务操作，而非只保护文件 restore 或 to_thread；调用取消等待操作及状态收尾完成。HTTP 导入/导出/备份 worker 同样纳入任务归属。 | 重复取消测试、服务层 files→同步→消费检查点→更新状态边界测试、现有真实 rewind/workspace 回归通过。未增加持久 operation journal，进程崩溃后的分阶段恢复仍是后续事项。 |
| S10 I/O 与伸缩 | SSE 每页最多 256 条，在 worker 逐行解析，不再一次 read_text 整份日志；保留兼容 `events_since` 列表 API。inventory、导出、导入、备份移到 worker。事件压缩与追加共享文件锁。 | 这是局部优化：查找 since_seq 仍线性扫描，单条事件没有新的字节上限；thread→turn 索引、全局 active lock 的恢复临界区、同步 optimize/部分 CRUD 尚未改造。避免把存在读改写竞态的清理操作直接丢进线程。 |

## 方案取舍

事件序号选择“每次持久预留 + 追加”，没有采用进程预留区间：区间虽减少 state 写入，但会让多个实例按不同区间交错产生事件，影响游标的顺序含义。本轮优先保证正确性，既有 delta 合批继续减少写入频率；没有声称 fsync 路径比旧版更快。

导入采用 staging + 备份回滚，避免立刻迁移整个文件存储格式。相比只做预校验，它也覆盖普通发布失败；相比持久事务 journal，它还不能处理所有崩溃窗口。若下一阶段要求在线多写入者、完整恢复与索引查询同时成立，SQLite/明确事务层值得独立设计，不应继续给 manager 堆零散锁。

恢复取消使用进程内任务归属，接口不增加 operation ID。用户断连不丢掉当前操作收尾，但硬杀进程仍需要 checkpoint/日志和后续恢复逻辑。这个区别没有用“已保证原子性”掩盖。

## 验证

- 扩大回归：**456 passed，1 skipped，2 deselected，55.57 秒**。覆盖 HTTP/认证、事件、线程、导入导出、分享、rewind、usage、delta 合批和 workspace。
- 扩大回归之后补充 legacy 截断重放提示及发布备份路径边界；最终相关定向回归：**56 passed，1.22 秒**，包含本篇新故障测试、事件流、归档、inventory、合批。与上一集合有重叠，不将数量相加。
- 新增 [test_audit_13.py](/Users/fjw/Desktop/deepseek-tui-py-main/tests/contract/test_audit_13.py)：路径参数化、跨进程序号、磁盘损坏尾行、溢出回放、发送失败/取消、导入故障回滚、链接/解包边界、活锁、关闭顺序等。服务取消测试明确使用受控阶段替身，真实文件恢复由原有 rewind/workspace 测试覆盖。
- `compileall` 和 `git diff --check` 通过。修改核心模块及新测试的定向 Ruff 检查通过；整个 server 原有的 data_inventory 未使用导入/旧 `__all__` 名称、manager 未使用局部变量没有顺手修改，也不宣称全仓 lint 通过。
- 扩大回归排除第十二篇已确认的两个旧失败：`test_start_turn_never_dispatches_without_checkpoint` 的替身缺少 default_model；`test_resume_thread_returns_detail` 缺少 API key。未改断言绕过它们，未调用真实模型或网络。

详细命令与结果：[13-fixes-validation.json](13-fixes-validation.json)。下一篇已交付：[14-protocol-presentation.md](14-protocol-presentation.md)。
