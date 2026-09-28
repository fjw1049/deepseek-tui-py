# 第十二篇：工作区、Git 与变更记录

日期：2026-09-28，延续 2026-09-27 审核批次。范围为 workspace 下 10 个模块，沿“执行目录 → Shell 写入观察 → 变更账本 → 发布 → 检查点恢复 → 回收”审核核心路径。本篇交付审核与离线取证，**正文保留修复前证据；2026-09-28 修复状态见 [修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/12-implemented-fixes.md)**。服务层如何授权恢复、HTTP 参数能否直达底层路径、Windows 真实进程管理留给后续审核。

结论：现行发布路径已有签名校验、写前日志、失败回滚和跨进程锁，值得保留。主要风险是旧接口、补偿观察器、展示账本各自定义路径与文件状态，正确性保证没有覆盖所有入口。建议先统一路径、缺失/不可读状态和恢复事务边界，再逐步拆分大文件，不适合整体重写。

证据：A 为离线探针复现，B 为静态控制流确认但未做完整端到端复现，C 为设计建议。[探针](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/workspace_probe.py)和[结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/workspace-probe-results.json)只操作临时普通 Git 仓库，不修改用户工作区、不结束真实进程、不创建实际工作 worktree。现有工作区测试 **224 passed，11.49 秒**，说明原有契约仍可通过；这些新发现属于覆盖缺口。

## W01 · P1：部分迁移失败后，源文件仍被清理（A）

位置：[managed_worktree.py:368](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/managed_worktree.py:368)，尤其 `handoff_changes` 最后的 `_restore_to_head`。

目标写入逐文件捕获 OSError 后继续；只要任一文件成功，move 模式就把全部 planned 文件恢复到源 HEAD，包含写入失败的文件。探针让 a.txt 成功、b.txt 写入失败，返回 skipped 包含 b.txt，但源 b.txt 的新内容已消失，目标也没有它。

建议最小补丁只清理确认成功的路径，并在清理前验证源文件仍等于发布时内容，防止擦掉随后编辑。更好方案是将这个旧接口委托给现有签名/快照发布原语，使计划、写入、清理具备一致语义。仅把循环改成遇错停止仍会留下部分成功，需要明确返回和恢复协议。

当前 `src` 中未发现该函数生产调用点，仅定义与测试；这是可复现的公开底层接口数据丢失缺陷，不能据此声称当前 UI 发布一定走到这里。验收需故障注入每个写入/清理步骤，确认未发布内容始终至少存在一份。

## W02 · P1：两个不可读哨兵被当成二进制内容相等（A）

位置：[managed_worktree.py:394](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/managed_worktree.py:394)。同一旧接口的 `ours == theirs` 在两边都为 `_UNREADABLE` 时成立。探针使用不同的 NUL 二进制内容，在 force=False 下目标被覆盖且无 conflicted。

最小修复用 raw 类型/模式/内容签名判等；无法确认时拒绝。不要把两个“读取失败”当成相同文件。长期与 `apply_raw_path_images` 共用状态模型，避免每条路径重写三方合并。可达范围与 W01 相同。验收加入二进制双边修改、链接目标变更、权限读取失败和真正相同二进制四组。

## W03 · P2：补丁合成破坏文件名、行边界和统计（A）

位置：[diff_synth.py:15](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/diff_synth.py:15)。`lstrip("./")` 删除任意数量的前导点/斜杠，`.env` 被写成 env；POSIX 下反斜杠也被当作分隔符。无结尾换行时，直接 join difflib 输出产生 `-old+new`，新增行计数变成 0。统计函数又把 hunk 中以 `+++`/`---` 开头的真实内容当作文件头忽略。

建议只移除精确 `./` 前缀，保留合法文件名；逐行处理缺少换行的记录并输出标准 no-newline 标记；统计只在 hunk 内识别增删行。另一方案委托 Git 生成补丁，格式可靠但纯内存写工具会多出临时文件/子进程成本，优先保留修正后的纯函数。验收必须实际 `git apply --check`，不能只断言补丁含某段字符串；文件不存在与空文件应使用显式 op/状态区分。

## W04 · P2：failed/pending mutation 污染净变化（A）

位置：[mutation_ledger.py:254](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/mutation_ledger.py:254)。commit 无条件更新 `_net_by_path`，折叠仅过滤 history 的 applied 状态，却仍使用后来的失败状态净内容。探针先成功 a→b，再失败 b→c，最终展示 a→c。

建议失败记录留在 history，但只有 applied 能推进净状态。另一方案分别建尝试事件与生效事件，语义更强但首轮无需扩大模型。验收四组：只有失败、成功后失败、失败后成功、成功后 pending；账本不能把未发生的变化展示成磁盘结果。

## W05 · P2：节流只减少通知，未减少全量 diff 重算（A/C）

位置：[mutation_ledger.py:292](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/mutation_ledger.py:292)。每次 commit 即使 emit=False 也 snapshot，重新遍历历史和所有路径并生成补丁，之后才节流回调。

| 独立文件提交数 | 实测当前 diff 合成调用 | 增量更新的目标调用数 |
|---|---:|---:|
| 10 | 55 | 10 |
| 100 | 5,050 | 100 |

这里测的是调用次数，右列是每路径一次的设计目标，**没有实现或实测替代方案，也不代表 50 倍总耗时收益**。方案一缓存每路径折叠结果，commit 只重算变更路径，保持当前返回 snapshot 的契约；方案二惰性 snapshot 能进一步减少合并字符串成本，但需要改变调用者消费时机。建议先方案一，并测 1/100/1,000 文件混合更新。history 截断还会原地修改传入 mutation，且注释称完整内容可另取却未在本模块保存；应区分展示限额与持久记录契约（B）。

## W06 · P1：Git 对账的路径与基线不稳定（A）

位置：[git_reconcile.py:29](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/git_reconcile.py:29)、[解析:132](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/git_reconcile.py:132)。status 使用非 NUL 格式，再用 unicode_escape 解释 Git 八进制 UTF-8 路径；diff 又以不同方式解释引号。预先修改的“中文.txt”被记录成乱码基线，最终作为本轮新变化错误归属。

另一个探针在 capture_baseline 后修改并 commit，最终 HEAD 相对 diff 为空，本轮变化完全漏记；baseline.head 已保存却没用于 diff。简单改用原 SHA 可以修复此复现，但并发其他任务提交时仍需归属规则，不能把基线以来全部提交都无条件记到本轮。

建议通过 `--name-status -z`/`--porcelain -z` 获取路径集合，补丁仅作为内容，不反向承担路径身份解析；使用稳定基线并明确并发归属不确定时的返回状态。替代方案直接共享 shell watcher 的路径解析和 pre-image，复用更好但需保留“排除回合前脏文件”契约。验收覆盖 Unicode、换行、引号、rename、POSIX 反斜杠及回合中 HEAD 移动。

## W07 · P1：对账新文件会读取链接目标，且没有大小上限（A/B）

位置：[git_reconcile.py:110](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/git_reconcile.py:110)。对新 untracked 文件直接 read_text。探针在仓库中创建指向仓库外临时文本的链接，外部内容进入 mutation diff（A）。大文本同样全量读取和 diff，截断发生在生成之后，不能限制峰值内存（B，未做内存压力测试）。

建议复用 watcher 的 lstat、常规文件与读取限额，链接按链接目标字符串记录或明确跳过，不展开目标内容；超限返回简短状态。仅检查 resolved 路径不够表达链接本身的变化，也不解决检查到打开之间的竞态。验收包括链接、特殊文件、超限文本、读取中替换。这里只证明进入账本，没有声称已经通过网络泄露。

## W08 · P2：Shell 写入白名单按原始字符串判断（A）

位置：[shell_write_guard.py:126](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/shell_write_guard.py:126)。`build/../src/main.py` 命中 build/ 前缀而放行；真实归属已经离开允许目录。`.deepseek/tmp/` 的前导点也被 lstrip 删除，可能误拒。`/tmp/` 直接允许意味着位于 tmp 的整个项目源文件也进入白名单。

建议先基于 workspace 解析路径再按目录归属判定，统一相对路径与绝对路径；遇到目录链接按实际目标归属处理。此模块是启发式工具路由，不应承担完整 Shell 沙箱承诺。Git 子命令只读列表也要区分命令与参数（例如允许 diff 并不证明其所有参数无副作用）；后续用只读命令矩阵补齐，不在这里引入完整 Shell 解释器。验收相对 ..、目录链接、tmp 内项目与合法缓存写入。

## W09 · P2：检查点 ID 直接组成存储路径（A）

位置：[turn_checkpoints.py:307](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/turn_checkpoints.py:307)。JSON 与 raw sidecar 路径直接拼 turn_id。探针 `begin_turn("../escaped", ...)` 在 checkpoints 外创建 escaped.json。load/delete 使用同样入口。

建议 store 边界统一拒绝空 ID、绝对路径、分隔符与父目录段，并验证 load 中对象 ID 与请求一致。替代方案用 ID 的摘要做文件名，可兼容任意逻辑 ID，但需磁盘迁移，不是首选。当前通常由服务生成 turn ID，未证明 HTTP 可直接利用；它首先是持久化 API 边界缺陷。验收所有读写删操作使用同一校验，不能只修 begin_turn。

## W10 · P1：恢复事务取消路径没有同等回滚保证（B）

位置：[turn_checkpoints.py:978](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/turn_checkpoints.py:978)，结合 [managed_worktree.py:33](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/managed_worktree.py:33)。raw 写线程被取消时会先等实际写入完成再抛 CancelledError，这避免锁提前释放；但上层 restore 只捕获 Exception，取消跳过后续文本恢复、回滚分支与显式临时目录清理。因此底层完成单批写入不等于上层整个恢复事务完成。

尚未做多 raw batch + 文本混合取消端到端复现，优先级按潜在部分恢复后果评估。推荐恢复事务由独立任务持有，外层取消时等待它形成完整结果/持久状态再传播；另一方案在取消分支回滚已尝试批次，但二次取消与回滚冲突需要单独处理。验收在每个 await 边界取消、重复取消，最终必须是完整成功、完整回滚或明确可恢复状态，不能静默部分完成。

## W11 · P2：回收按 cwd 终止进程，缺少启动归属（B）

位置：[managed_worktree.py:302](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/managed_worktree.py:302)、[回收:2318](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/managed_worktree.py:2318)。自动回收会终止 cwd 位于目录下的其他 PID；用户打开的终端/开发服务器也可能符合条件。干净目录只说明磁盘状态，不证明无人使用。进程枚举有平台差异，未在真实进程上执行验证。

建议只结束本应用登记的进程组；遇到未知活跃进程保留目录并报告占用。另一个方案是所有占用都保留，最保守、改动小，但自动回收率下降。不建议把扩大 PID 检测当作归属证明。验收使用模拟 PID/kill，覆盖自身、已退出、应用子进程和外部用户进程。

## 逐模块最终建议

| 模块 | 通用性与已有优点 | 架构、优雅性、扩展与性能建议 |
|---|---|---|
| [__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/__init__.py) | 纯导出层，依赖小 | 保留；后续统一公开变更/快照接口时再调整，不增加启动副作用。 |
| [execution.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/execution.py) | 集中区分 project 与 execution root，跨工具复用合理 | 存在的目录不等于验证过的 managed worktree；空路径落到 cwd 的默认语义需由入口明确。不要为了两个路径立即造复杂 workspace 对象。 |
| [diff_synth.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/diff_synth.py) | 小型纯函数，便于测试 | 修 W03；明确补丁究竟可应用还是仅展示。建议可应用补丁为基础，展示截断单独处理。 |
| [mutation_ledger.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/mutation_ledger.py) | 历史与净变化分开，支持恢复原状后取消净记录 | 修 W04/W05；将状态推进与展示生成分离，按路径缓存，保持完整记录与展示截断的区别。避免先引入事件数据库。 |
| [git_reconcile.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/git_reconcile.py) | 作为漏记补偿层合理，排除已有脏路径和其他任务路径 | 修 W06/W07；集中 Git 路径协议及缺失/失败状态，保持补偿层地位，不把它当精确所有权来源。 |
| [shell_mutation_watch.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/shell_mutation_watch.py) | NUL 路径、文件类型检查、512 KiB 上限优于 reconcile | `_head_content` 将 Git 错误/解码失败与不存在都返回 None，影响 before image（B）；逐文件 git show/mode 调用适合批量 cat-file 优化，但先测进程次数和典型改动规模。建议与 reconcile 共用读取结果类型。 |
| [shell_write_guard.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/shell_write_guard.py) | verdict 简单，规则透明，调用成本低 | 修 W08；明确启发式边界，区分产物目录判断与命令解析。继续增加样例矩阵比构造庞大正则更易维护。 |
| [project_lease.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/project_lease.py) | OS advisory lock、异步取消收拢、永久错误快速失败合理 | 保留；锁仅协调本应用，不替代签名校验。Windows 分支需原生 CI，当前未发现要求立即重构的独立问题。 |
| [managed_worktree.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/managed_worktree.py) | 当前 raw/text 发布有签名、快照、回滚，保留未发布劳动和不可达提交 | 修 W01/W02/W11；2,619 行混合 Git 操作、文件事务、回收与恢复。优先让旧接口复用已验证的事务原语，再按“发布/同步”和“生命周期”拆分，不机械按行数拆文件。 |
| [turn_checkpoints.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/workspace/turn_checkpoints.py) | durable raw sidecar、模式位、写前日志、恢复前预检与冲突保护有价值 | 修 W09/W10；1,809 行承担存储/计划/执行，适合先明确事务 owner 再拆层。实例内 Lock 不等于跨实例事务，调用层是否始终持 project lease 留给服务篇核验；list/prune 全量读 JSON 后续测量再建索引。 |

## 实施顺序与验收边界

1. 先处理数据完整性：W01/W02 的旧接口收口、W10 取消状态机；每项独立故障注入。
2. 再统一路径/内容状态：W03/W06/W07/W08/W09，以及 watcher 的 missing/unreadable 语义。
3. 然后修账本生效规则和缓存：W04/W05；先确认结果一致，再测成本。
4. 收紧进程回收归属 W11；最后依据调用关系拆 managed_worktree/checkpoints。

原有测试命令：`DEEPSEEK_HOME=/tmp/audit12-baseline .venv/bin/pytest -q tests/workspace tests/test_worktree_process_cleanup.py`。探针：`PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/workspace_probe.py`。A 级探针是缺陷特征记录，修复后应转成断言正确行为的测试，不能要求旧缺陷结果永远不变。

下一篇建议：**服务运行时、线程与事件流**，重点核验项目锁实际调用范围、publish/rewind 的取消与持久状态衔接、HTTP 输入和广播背压。
