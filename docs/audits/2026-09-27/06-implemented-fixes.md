# 第六篇上篇修复记录 · Engine 与工具调度

实施日期：2026-09-27，基于包含用户已有改动的当前工作区。原问题与旧数据保留在 [第六篇审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-engine.md)。本轮没有提交、推送或覆盖其他功能的改动。

## E01—E08 的实施状态

| 问题 | 实际修复 | 验收证据 |
|---|---|---|
| E01 排队消息阻塞取消 | 忙碌期间将 SendMessageOp 放入待执行 deque，操作循环继续接收控制指令；空闲后按顺序启动消息 | send/send/send/cancel：第一回合被取消，后两条按顺序执行 |
| E02 遗留操作等待任务 | run 的 finally 统一取消并等待 op_wait 与 turn_task；启动事件发送也纳入清理作用域 | runner 退出无 engine-next-op 残留；下一条消息仍在队列；启动事件遇到满队列时取消也会关闭 coordinator |
| E03 下游丢事件 | coordinator 保留一批待交付邮箱事件，try_emit 成功后才移除；未交付前不继续 drain 下一批。活动快照只在发送成功后更新 last，并发送运行→空闲 | 4096 个事件填满队列后，释放容量，completed 只交付一次；活动数由 1 回到 0 |
| E04 错误结果复用 | 只允许连续区间内的 read_file/grep_files/file_search 成功结果复用；非缓存工具使缓存失效；失败结果不复用，有工具前后 Hook 时禁用复用 | 增量写执行两次；read/write/read 得到新内容；动态状态、失败读取、Hook 场景不使用旧缓存 |
| E05 跨回合串账 | reset 更换当前账本列表，不清空后台请求持有的列表；通过任务上下文继承回合账本，请求开始时捕获 scope，记录 turn_id。会话费用在每条 Usage 到达时累加，取消回合末重复累计 | 旧子任务跨 reset 连续完成两轮，6 个输出 token 留在旧 scope，新回合为 0；会话总费用恰好计入一次 |
| E06 资源未回滚/清理中断 | ToolRuntime 与 Engine 工厂使用 AsyncExitStack 登记已获得资源，成功后才转移所有权；shutdown 尝试所有释放步骤。另修复 Engine.create 自建 runtime 被误标为借用的问题 | 后续初始化失败和启动期间取消都调用 shutdown；一个子管理器关闭失败不阻止其余清理；自建 runtime 会关闭，借用 runtime/MCP 不误关 |
| E07 轮次耗尽仍成功 | 返回 FAILED、明确错误原因、实际工具轮数和已有部分回答 | 上限耗尽后 outcome=failed、tool_round_count=1，保留 partial 回答 |
| E08 并行结果晚发布 | 使用 as_completed 提前发布完成事件；所有调用结束后，仍按请求顺序提交上下文与共享状态。取消批次时回收所有并行 job | 快结果在慢工具结束前可见；每个结果事件一次；上下文仍按 slow/fast 原顺序写入 |

实现入口：[操作循环与装配](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py)、[工具调度](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py)、[结果缓存](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/tool_dedup.py)、[事件转发](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/cycle.py)、[用量账本](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/usage_ledger.py)、[工具运行时](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/runtime.py)。

## 取舍与仍然存在的边界

- 没有引入通用事件总线或新的调度框架。待交付队列最多积累一次 drain 的内容；这批未交付时，新事件仍由原有有界 Mailbox 管理。它解决运行中转发失败的丢失，不是断电后的逐事件可靠重放。Mailbox 自身极端饱和仍按第五篇的快照补偿规则处理。
- 去重修复遵循保守的内置工具白名单，不试图推断任意插件工具的幂等性。外部进程同时改文件的全局一致性不在同批缓存保证内；跨轮防循环策略保留。
- 用量 scope 随任务继承，晚到请求能够归属原回合，并更新会话累计。已经发出或落盘的旧 TurnComplete 账单不会自动回写；旧回合 UI 的事后补记仍需要 Server 的账单更新协议。当前修复防止新回合及其预算被旧请求污染，不能声称已经实现可追溯的持久化计费系统。
- AsyncExitStack 保证一个释放失败后仍尝试其他释放，异常通过链式上下文保留；它不提供“任意不合作执行器都能在固定时间内退出”的保证。shutdown 的会话结束事件采用尽力发送，避免没有消费者时阻塞客户端关闭。
- 并行优化只提前发布结果事件，没有把 Goal 记账、LSP 处理、spillover 和上下文提交全部并行化，避免扩大共享状态竞争。

## 最小横向对比

20 组交替试验，两条假只读调用分别等待 40ms 与 3ms；两侧都检查结果顺序。

| 方案 | 快结果可见中位时间 | 整批结束中位时间 |
|---|---:|---:|
| 旧 gather 屏障模型 | 41.138ms | 41.139ms |
| 本次真实并行调度方法 | 3.576ms | 41.201ms |

当前侧调用真实 `_execute_tools_parallel`，执行器与通知接收器是离线替身；对照侧重现旧 gather 后发布的屏障。这里只改善结果可见延迟，整批结束时间基本相同，不是模型吞吐提升。

[可重复脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/engine_compare_after.py) · [结果数据](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/engine-compare-after-results.json)

## 验证

新增 [14 项 Engine 定向回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/engine/test_audit_fixes.py)。后续上下文优化另有 16 项定向回归，详见 [第六篇下篇](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-context.md)。

本轮最终相关测试：**458 passed、3 skipped、1 deselected**。包含整个 tests/engine，以及子 Agent、Task 恢复、事件集成、用量、项目上下文、审批桥、手动压缩等相关合同测试；定向测试已包含其中，不重复相加。

- 3 项跳过均为需要显式启用和真实 API key 的 live 场景，没有请求真实模型。
- 1 项排除仍是此前的 Goal 隐藏续跑契约差异：无活跃 Goal 时是否应继续执行。本次没有改 Goal 行为迁就测试。
- 手动压缩合同测试原来只替换 Engine，却仍解析真实 API key；补齐 `_get_llm_client` 替身，保留全部接口断言。
- 编译检查与本轮主要修改文件的 Ruff F 类检查通过。context.py 原有未使用/重复 re 导入仍存在，未夹带清理，也未宣称仓库整体 lint 通过。

完整运行命令和统计见 [验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-validation.json)。历史 engine_probe.py 是修复前反例，保留它用于追溯；当前正确性由正向 pytest 回归验证。
