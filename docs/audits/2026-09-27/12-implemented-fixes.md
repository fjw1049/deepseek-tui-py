# 第十二篇修复记录：工作区、Git 与变更记录

日期：2026-09-28。接续 [审核文案](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/12-workspace-git.md)，修复 W01—W11 的已确认边界问题，并保留现有发布/恢复接口。本轮没有整体拆分大文件，也没有修改服务层状态机；后者继续在第十三篇审核。

## 改动与验收

| 问题 | 本轮实现 |
|---|---|
| W01 部分迁移失败清理源 | 仅清理已成功发布的路径；计划、写入和清理之间比较源签名，写入失败或源已发生后续编辑时保留源文件。 |
| W02 不可读哨兵相等 | 二进制/链接改用实际 raw 签名比较，无法读取的源跳过；不同二进制在非 force 模式下返回冲突。 |
| W03 补丁格式 | 只剥离精确 `./`，保留隐藏文件与 POSIX 反斜杠；对需转义的文件名引用，补齐 no-newline 标记；hunk 内统计增删，新增/删除补充 mode 头。测试实际用 Git 检查并应用补丁，覆盖空文件、无尾换行、中文、空格、引号和换行文件名。 |
| W04 失败污染账本 | failed/pending 留在历史中，但不会推进净变化；成功状态单独更新索引。 |
| W05 重复 diff | 增量缓存每路径折叠结果，仅重新计算变化路径；保留 commit 返回完整 snapshot 的接口。复制输入 mutation，历史保留完整 patch，展示快照单独截断。 |
| W06 Git 路径与基线 | 使用 porcelain/name-only 的 NUL 路径协议及 literal pathspec；停止从补丁文本反推身份；对账固定到回合开始 SHA，关闭 rename 推断，保留调用方排除集合。Git 输出按字节解码，避免 universal-newline 改写文件名。 |
| W07 新文件链接/大小 | 对账新文件复用受限读取：lstat、常规文件、512 KiB、父目录归属、打开后 inode 检查和有限读取；不读取链接目标。watcher 的 HEAD 内容也区分缺失与读取失败，按 blob 大小限额。 |
| W08 原始路径白名单 | 基于 workspace 解析实际目标后判断目录归属；项目位于 tmp 内仍执行源文件规则，目录链接不能靠 build/ 名称放行；保留项目外临时输出。 |
| W09 检查点 ID | JSON 与 sidecar 路径统一检查 ID，拒绝绝对/穿越/分隔符等名称；load 检查内容 ID 与文件请求一致。 |
| W10 恢复取消 | 恢复由独立任务持有，外层取消或重复取消先等待整个恢复形成结果，再传播取消；真实 raw sidecar + 文本混合回归验证两者都完成恢复。 |
| W11 回收杀进程 | 自动回收遇到占用进程返回保留；显式移除也报告占用。移除流程不再自动调用按 cwd 杀进程的 helper；独立显式 terminate API 保持原行为。 |

## 性能横向对比

[可重跑脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/workspace_benchmark.py)使用 `0eeaeb8c` 的旧 ledger 与当前实现对比，依赖同一补丁函数，固定数据、每组单次运行，记录 diff 次数及耗时。所有最终 snapshot 完全相同。

| 独立文件提交 | 修复前 diff 次数 / 耗时 | 修复后 diff 次数 / 耗时 |
|---|---:|---:|
| 1 | 1 / 0.000057 s | 1 / 0.000034 s |
| 100 | 5,050 / 0.038292 s | 100 / 0.001562 s |
| 1,000 | 500,500 / 3.978155 s | 1,000 / 0.055538 s |

这是本机微基准，包含 mock 计数开销，不是端到端吞吐保证；完整快照的排序、合并字符串和历史占用仍随规模增长。增量折叠比改变 snapshot 契约更小，暂不引入惰性事件接口。[实际结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/workspace-benchmark-results.json)

## 验证与边界

新增 [回归测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/workspace/test_audit_12.py) 最初 36 项全部失败，修复后加上空文件、超限、二进制与 ID 内容校验共 43 项通过。原测试的权限故障注入改到实际使用的 os.open；原“删除时杀进程”测试改为验证占用时保留，匹配明确调整的行为。

扩大回归第一次为 **448 passed、1 skipped、2 failed**；两项失败用临时源代码副本替换为修复前 workspace 后均原样复现：

- `test_start_turn_never_dispatches_without_checkpoint`：测试 Engine 替身缺少 `default_model`，未到检查点分支即报 AttributeError。
- `test_resume_thread_returns_detail`：未配置 DeepSeek API key，真实客户端构造失败。

最终排除这两个已确认基线失败项再验证，结果见 [机器可读记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/12-fixes-validation.json)。Ruff F 和 diff whitespace 检查通过。没有修改这两个无关测试或客户端逻辑。

剩余边界必须保留：

- 旧迁移 helper 仍非完整多文件事务；签名检查后至实际 Git 清理存在竞态窗口，建议在实际恢复调用中持项目锁，长期委托现行事务原语。本轮保证已复现的失败/后续修改场景，不宣称能阻止不合作外部进程在任意时刻写入。
- 固定 SHA 解决 HEAD 漂移漏记，但补偿对账仍是估计归属；其他进程提交需由调用方排除。逐文件 Git patch 增加子进程数，后续有证据再批处理；tracked Git 输出未实施整体字节限额。
- 文件读取在支持的平台使用 O_NOFOLLOW，并核对 inode；不是抵抗任意恶意并发目录替换的完整 dirfd 沙箱。Windows 原生行为未验证。
- 恢复取消现已等待文件事务完成，但服务层后续 isolate 同步、检查点消费、会话裁剪仍可能被取消打断；第十三篇单列此跨层边界。
- 自动回收依赖平台能枚举的 cwd 占用；没有增加应用进程登记系统。旧独立 terminate API 仍可明确结束进程，未改变它的产品权限语义。
- history 保留完整 patch 提高可追溯性，也增加长回合内存；展示截断不应被当作整个历史存储预算。

历史 `workspace-probe-results.json` 不覆盖，保留为修复前证据；不要继续运行旧探针并把异常当作失败，新行为由回归测试验证。
