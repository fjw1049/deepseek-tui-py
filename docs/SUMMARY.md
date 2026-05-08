

### 三、集成债清单之外，还需要实现的功能

这是你问的核心问题。我按 Phase 逻辑梳理债清单没有覆盖、但 Rust 中确实存在且属于"百分百复刻"范围的功能：

#### Phase A 遗留

| 缺失功能                           | Rust 规模    | 说明                                                         |
| :--------------------------------- | :----------- | :----------------------------------------------------------- |
| State 时间戳类型                   | ~50 LOC 改动 | Rust 用 i64 Unix epoch，Python 用 TEXT ISO 8601。数据格式不兼容 |
| ThreadMetadata 19 字段             | ~100 LOC     | Python 只有 10 字段，缺 rollout_path, ephemeral, model_provider, cli_version 等 9 字段 |
| Session index JSONL 追踪           | ~200 LOC     | Rust StateStore 有 10 个 session 相关方法，Python 缺失       |
| Config 12+ 缺失顶层字段            | ~150 LOC     | memory_mode, approval_chain, namespace, use_realtime_api 等  |
| NetworkPolicyToml                  | ~100 LOC     | 网络策略配置段                                               |
| MemoryConfig / NotificationsConfig | ~80 LOC      | 配置子段                                                     |

#### Phase B 遗留（Engine 深层）

| 缺失功能                            | Rust 规模  | 说明                                                 |
| :---------------------------------- | :--------- | :--------------------------------------------------- |
| engine/context.py — Token 会计      | 382 LOC    | 上下文窗口管理、token 计数、截断决策。当前 Python 无 |
| engine/dispatch.py — 工具路由       | 354 LOC    | 工具调用分发逻辑。当前直接在 Engine 简单处理         |
| engine/tool_execution.py — 执行门控 | 298 LOC    | 工具执行前的检查（权限/sandbox/approval）            |
| engine/tool_catalog.py              | 475 LOC    | 工具目录管理（与 Registry 互补）                     |
| capacity_memory.py — 状态持久化     | 323 LOC    | capacity 的 canonical state 持久化                   |
| coherence.py — 状态机               | 149 LOC    | Intro→Depth→Consolidation 对话阶段追踪               |
| session_manager                     | ~1,339 LOC | 多会话持久化与恢复                                   |
| cycle_manager                       | ~1,071 LOC | 对话周期边界、briefing、归档                         |
| seam_manager                        | ~700 LOC   | 上下文回退/分叉恢复                                  |
| runtime_threads                     | ~4,413 LOC | 后台任务协调、cancellation token 传播                |
| network_policy                      | ~701 LOC   | 网络访问策略+审计日志+session cache                  |
| workspace_trust                     | ~286 LOC   | 工作区信任持久化                                     |
| error_taxonomy                      | 477 LOC    | 错误分类+重试提示                                    |
| Engine 集成测试框架                 | 1,477 LOC  | Rust engine/tests.rs                                 |

#### Phase C 遗留（未实现的工具）

| 工具                                | Rust 规模          | 优先级 |
| :---------------------------------- | :----------------- | :----- |
| web_run (浏览器自动化)              | 1,763 LOC          | P0     |
| web_search (搜索引擎)               | 558 LOC            | P1     |
| fetch_url (HTML→text)               | 509 LOC            | P1     |
| rlm_query (递归 LLM)                | 406 LOC            | P1     |
| review (代码审查)                   | 540 LOC            | P1     |
| remember (用户记忆)                 | 138 LOC            | P1     |
| skill_load                          | 365 LOC            | P1     |
| plan_update                         | 406 LOC            | P1     |
| note                                | ~60 LOC            | P1     |
| recall_archive                      | 723 LOC            | P1     |
| revert_turn                         | 205 LOC            | P1     |
| validate_data                       | 316 LOC            | P1     |
| run_tests                           | 253 LOC            | P1     |
| truncate                            | 613 LOC            | P1     |
| request_user_input                  | 260 LOC            | P1     |
| checklist_write/add/update/list     | 630 LOC            | P1     |
| finance                             | ~1,068 LOC         | P2     |
| GitHub REST API (替代 gh shell-out) | 587 LOC            | P1     |
| Automation cron 调度                | 382 LOC (真正调度) | P1     |
| read_file PDF 提取                  | ~100 LOC           | P1     |

#### Phase D 遗留（基础设施深层）

| 缺失功能                 | Rust 规模  | 说明                                               |
| :----------------------- | :--------- | :------------------------------------------------- |
| App Server 剩余 21 路由  | ~2,000 LOC | 当前只有 7/28 路由                                 |
| RuntimeThreadManager     | ~4,413 LOC | 线程/Turn 状态机。App Server 28 路由中大部分依赖它 |
| MCP stdio server         | 625 LOC    | Python 只有 client，无 server                      |
| MCP tool 名 hash 截断    | ~50 LOC    | >64 字符的 qualified name 需截断                   |
| Hook conditions 完整实现 | ~200 LOC   | ToolName/ToolCategory/Mode/ExitCode/All/Any        |
| Hook shell 执行          | ~300 LOC   | timeout/background/continue-on-error               |

#### Phase E 遗留（表面层深层）

| 缺失功能                          | Rust 规模 | 说明                       |
| :-------------------------------- | :-------- | :------------------------- |
| project_context + project_doc     | 605 LOC   | 项目上下文加载器           |
| settings store                    | 597 LOC   | 设置存储                   |
| memory store                      | 197 LOC   | 记忆存储                   |
| eval harness                      | 742 LOC   | 评估框架                   |
| composer_history + composer_stash | 479 LOC   | 输入历史/暂存              |
| snapshot/repo + paths + prune     | 936 LOC   | 工作区快照系统             |
| REPL runtime                      | 877 LOC   | REPL/非交互运行时          |
| features.rs                       | 244 LOC   | Feature flag 表            |
| palette/theme                     | 610 LOC   | 颜色主题                   |
| localization (i18n)               | 1,863 LOC | 国际化字符串               |
| pricing 完整版                    | 177 LOC   | V4-pro 折扣+cache-hit 会计 |
| retry_status                      | 201 LOC   | Retry-After 解析           |
| logging                           | 72 LOC    | 日志框架                   |

### 四、关键发现：被遗漏的系统性问题

以上逐条列举之外，有几个系统性问题值得你特别关注：

1. "Stage 2 Integration Commit" 从未执行

HANDOVER 第三节明确写了 Stage 2 审核后需要 4 步 integration commit（tool_parser→turn_loop、compaction→Engine、capacity→Engine、command_safety→ExecShell），但从未执行。这意味着 Engine 的三大核心模块（capacity/compaction/tool_parser）仍是孤岛，虽然代码存在，但运行时从不被调用。这是当前系统最大的功能性 bug。

2. 缺少"中间层管理器"

Rust 有 ~30,000 行的 top-level sub-managers（session_manager, cycle_manager, seam_manager, runtime_threads, working_set, error_taxonomy 等）。这些不在任何 Stage 的明确路线图中（HANDOVER 路线图 Stage 2–6 都没有专门提到它们），但它们是 Engine 真正跑起长对话的前提。这是审核报告和路线图之间的一个缝隙。

3. App Server 只是"门面"

Stage 4 建了 FastAPI 框架 + 7 个基本路由，但完整的 28 路由需要 `RuntimeThreadManager` 状态机（Rust 4,413 LOC），这个完全没有实现。意味着 App Server 当前不能驱动真实的线程/Turn 生命周期。

4. 工具的"真正执行"链路未贯通

虽然 53 个工具注册了，但：

- SubAgent 的 executor 是 stub（sleep 50ms）
- Task 的 executor 是 stub（sleep 50ms）
- Engine 的 turn_loop 是骨架级
- capacity/compaction 未接入

所以从用户输入 → Engine → LLM → 工具调用 → 结果返回 → 下一轮这条完整的多轮工具链路，在长对话/复杂场景下是不可靠的。

### 五、按优先级排序的后续工作

如果目标是让系统真正"跑起来"（而非只是代码存在），建议优先级：

| 优先级      | 工作                                                       | 估计规模   |
| :---------- | :--------------------------------------------------------- | :--------- |
| P0-Critical | Stage 2 Integration Commit（接通 3 个孤岛到 Engine）       | ~300 LOC   |
| P0-Critical | Engine context/dispatch/tool_execution 补齐                | ~1,000 LOC |
| P0-Critical | RuntimeThreadManager + App Server 28 路由                  | ~3,000 LOC |
| P0          | session_manager + State 时间戳修正                         | ~1,500 LOC |
| P0          | SubAgent/Task 真实 Executor（替换 stub）                   | ~1,600 LOC |
| P1          | 15+ 缺失工具 (web_search, fetch_url, remember 等)          | ~5,000 LOC |
| P1          | cycle_manager + seam_manager + working_set 管理器          | ~3,000 LOC |
| P1          | 30 个 P1 slash 命令 + 11 个 P1 CLI 子命令                  | ~2,500 LOC |
| P1          | TUI 剩余 widget（Sidebar, Help, Pickers, Markdown 渲染等） | ~4,000 LOC |
| P2          | 网络策略/审计/workspace trust/error taxonomy               | ~1,500 LOC |
| P2          | i18n/theme/onboarding/eval harness                         | ~3,000 LOC |

### 六、总结

你的重构进度从 5% 提升到了约 30–35%，在 2 天内跨越了 6 个 Stage 并新增 730+ 个测试，这个速度是很快的。但距离"百分百行为复刻"，还有以下核心差距：

1. Engine 核心回路没有真正贯通（3 个孤岛 + 多个缺失子模块）
2. 中间层管理器大面积缺失（~30,000 LOC 的 sub-managers）
3. 20+ 工具仍未实现
4. App Server 无法驱动完整的 Thread/Turn 生命周期
5. TUI 约 80% 的 widget 功能仍为空白

就是完整的复盘。如果你准备继续推进，我建议先做 Stage 2 Integration Commit——它是投入最小（~300 行）、收益最大的一步，直接解决 Engine 运行时 3 个模块不工作的问题。



代码探索子任务已完成。结合实际数据，补充一个关键数字对照：

代码规模对比：

| 维度          | 审核时 (05-06) | 现在 (05-08) | Rust 原始       |
| :------------ | :------------- | :----------- | :-------------- |
| `src/` 行数   | 7,597          | 22,025       | ~161,000        |
| `tests/` 行数 | ~1,500         | 11,150       | (内嵌在 .rs 中) |
| Python 文件数 | ~60            | 147          | —               |
| 测试文件数    | ~15            | 53           | —               |
| LOC 占比      | ~5%            | ~14%         | 100%            |

代码量翻了将近 3 倍，从 5% 推进到了 14% 的 LOC 覆盖率（行为覆盖率约 30-35%，因为 Python 比 Rust 更紧凑）。

这些数据印证了我上面复盘中的结论——核心骨架已搭建，但中间层管理器 (~30,000 LOC) 和 TUI 深层 widget (~47,000 LOC) 是剩余工作量的主体。如果你想继续推进，我建议你告诉我下一步想做什么方向。
