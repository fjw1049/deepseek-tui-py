# Goal 模式第二轮审计：与 Codex 的一致性和发布条件

> 这是升级前的历史审计。后续实现及仍存在的边界见 [当前 Goal 说明](goal-mode.md)。升级后探针结果见 `goal-production-probes-results-after.json`。Shell 另有直接源码写入保护，本文的能力分类缺口主要涉及允许的产物路径、间接执行和外部改动，不能理解为所有 Shell 源码写入都被允许。

日期：2026-09-27。对象：当前未提交工作区，包含上一轮 Goal 升级。此次新增审计报告和离线反例脚本，没有继续修改产品行为。本文结论取代“测试通过即可视为成熟”的判断。

**结论：尚未与 Codex 的公开行为契约完全一致，也不足以按成熟功能发布。** 持久状态、跨轮待办、完成记录、预算状态和恢复入口已有基础；核心问题“任务没做完却宣布完成”仍能从模型工具入口复现。第一轮增加的证据 ID 检查是机械门槛，不能等同于验收成立。

## 调研依据与对标边界

重新查阅了 [OpenAI 官方 Using Goals in Codex](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex) 的架构、续跑与完成检查说明。其公开设计强调线程持久目标、空闲且无待处理用户输入/工作时续跑、依据证据验收、用户或系统控制恢复和预算。没有工具调用的续跑会抑制下一轮。

本文没有取得并逐行审计 Codex 完整实现，也没有对两款产品做同任务实机实验。因此，下文“一致”仅指公开行为契约，不表示源码、工具 schema 或实际成功率相同。上一轮自定义的 `evidence: [tool_call_id]` 不是已证实的 Codex 原生 API；独立验收器也只是本项目的设计建议，不能宣传成 Codex 已公开采用的内部机制。

| 维度 | 当前实现 | 判断 |
|---|---|---|
| 线程内持久目标 | 有目标、状态、预算和恢复 | 基础接近；异常数据和崩溃恢复仍需补强 |
| 完成验收 | 非空理由 + 成功工具 ID + 无开放 checklist | 不足以判断目标达成；确定反例见下文 |
| 完成可追溯 | 保留完成记录，可 reopen | 已改善；尚无完整队列历史归档 |
| 控制权限 | 模型可调用 active 和 SetGoalBudget，授权主要靠提示词 | 缺少运行时授权边界 |
| 续跑调度 | 检查 active_turn 后异步启动 | 用户输入优先级与原子启动尚未验证 |
| 无工具续跑 | 自动转 paused | 能止住文本空转；比公开的“抑制下一轮”更强，应明确为产品选择 |
| 预算限制 | 独立 budget_limited | 状态语义改善；动态时间预算存在缺陷 |
| 真实完成率 | 无当前版本的模型轨迹评测 | 无法声称达到 Codex 效果 |

## 复现实验

运行方式：

```sh
PYTHONPATH=src .venv/bin/python docs/goal-production-probes.py
PYTHONPATH=src .venv/bin/pytest tests/goal -q
```

脚本：[goal-production-probes.py](/Users/fjw/Desktop/deepseek-tui-py-main/docs/goal-production-probes.py)。结果保存在同目录的 `goal-production-probes-results.json`。已有 Goal 测试结果：**89 passed**。

反例调用真实 GoalService、UpdateGoal/SetGoalBudget 工具及计时函数；工具结果是合成记录，计时用可控 sleep 模拟。没有调用模型 API，没有实际执行 pytest/pwd 命令作为任务工作，也没有重演用户历史会话。这些实验说明运行时允许错误行为，不能推算模型实际出错概率。脚本退出 0 表示取证完成，不表示产品验收通过。

| 实验 | 实测结果 | 含义 |
|---|---|---|
| 目标要求修复 checkout；记录测试失败，再引用 pwd 成功 | complete 被接受 | 无关成功可掩盖必需验证失败 |
| 删除 pending 验收待办，再引用 pwd | complete 被接受 | 无法防止模型漏项/缩减范围 |
| 将 pending 改为 cancelled，再引用 pwd | complete 被接受 | 取消与验收通过未严格区分 |
| 用户暂停后，模型调用 active，没有新授权记录 | 恢复 active | 调用接口未验证用户恢复意图 |
| 模型将 token 总额从 100 改为 1,000,000，没有新授权记录 | 修改成功 | 数字合法不等于获准调整 |
| 旧计时器等待期间，总时间改为 60,000ms | 仍 budget_limited，剩余 60,000ms，cancel 调用一次 | 旧期限误伤新预算 |
| 五轮自动续跑都记录相同 pwd | 五轮均允许继续 | “有工具”不能证明有进展；此为成熟度问题，不声称 Codex 一定做了更强检测 |
| 恢复 evidence=[{}] 后申请完成 | KeyError | 持久化数据缺少结构校验 |
| 恢复 checklist=null | TypeError | 不兼容异常/旧数据形状 |
| 直接调用 service.mark_complete，无证据 | complete | 底层服务可绕过门槛；不是额外暴露给模型的工具入口 |

## 必须优先处理的发现

### P1：完成门槛检查引用合法性，没有检查需求覆盖

位置：[validate_completion](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:243)、[save_checklist](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/service.py:187)。

代码只校验被引用的记录是否成功、结束、版本匹配。未引用的必要失败没有要求关联；checklist 可删可取消，completion_criterion 不参与结构化验收。任意非空 reason 都能通过，包括没有逐项审计的“Everything is done”。这是最直接对应用户症状的缺陷。

建议将“用户要求的验收项”和“模型临时执行步骤”分开。清晰需求可自动提取并展示，无需每次弹确认；需要缩减用户要求时，应有用户变更依据。每个必需验收项关联产物或检查结果，区分通过、失败、未验证、阻塞；不能将取消执行步骤视为需求通过。研究/文字任务允许产物及来源证据，不强行安排无意义 Shell 调用。

不要改成“发生过任意失败就不能完成”：调试时失败正常，也可能不相关。需要拒绝的是当前必需验收仍失败或未验证。语义关联无法完全由 schema 保证，仍需对照原始请求做最终审计，并通过真实模型评测测量漏项。

### P1：Shell 文件改动不会使既有验证失效

位置：[结果分类](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:386)、[Shell capabilities](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/shell.py:148)。这是静态代码确认，未进行完整 Shell 写入端到端实验。

分类只检查 WRITES_FILES，exec_shell 声明的是 EXECUTES_CODE/SANDBOXABLE。因此通过 Shell 改源码不增加 work_revision，甚至写入命令本身会被标成 verification。未知工具也可能落入非写入分类。第一轮文档已列出限制，但该限制直接影响完成正确性，不能作为成熟功能的常规免责声明略过。

建议建立可核查的产物版本/内容指纹，覆盖 Shell、子 Agent 和外部变动；在验证开始与结束记录相关版本，完成提交时再次核对。先覆盖代码任务的源码和指定产物，不做无限目录监控。不要简单把所有 Shell 都禁止作为证据，因为测试本身通常经 Shell 运行。

### P1：模型控制权限没有运行时约束

位置：[UpdateGoal active](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/tools.py:240)、[SetGoalBudget](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/tools.py:288)。

提示词要求用户明确授权，但工具执行不检查授权上下文。建议恢复、清除和预算修改从用户命令/UI 进入；如保留自然语言委托，绑定一次性的目标 ID、目标版本和授权参数。不能用模型自报 authorized=true 替代授权。模型完成申请应在单一服务入口原子执行校验和状态转换，避免 mark_complete 绕过门槛。

### P1：时间预算无法正确响应回合中的调整

位置：[deadline](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:518)、[创建 timer](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py:2099)。

已复现增加额度后旧 timer 仍取消。代码还显示：回合开始时没有时间预算就不建立 timer；回合中首次设置预算缺少即时监控。缩短预算也没有重新调度机制。这两个分支尚未做长工具端到端复现。

建议 timer 始终按当前预算计算剩余时长，预算修改和状态变更可唤醒它；到期再次校验目标身份、运行代次和实际剩余预算，再取消对应运行。测试至少覆盖首次设置、加长、缩短、暂停/恢复、替换目标及取消竞态。

### P1：切换会话时预算恢复操作存在错线程风险

位置：[预算提交](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GoalStrip.tsx:132)、[store 命令](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2888)。这是静态控制流发现，尚未实机复现。

UI 先 await budget，再调用 resume；每次 store 调用都读取当时 activeThreadId。若等待期间切换会话，第二次命令可能作用于另一个线程。前一次响应也无条件写 currentGoal，可能覆盖当前会话的目标栏。

建议调用固定 thread_id/goal_id/expected_revision，预算与恢复作为同一目标操作；异步响应只更新对应线程缓存，当前视图仅在身份匹配时刷新。测试必须在请求挂起时切换线程，不能只 mock 顺序成功。

### P2：调度、恢复和无进展检测需要故障注入测试

位置：[续跑调度](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3906)、[反序列化](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/goal/persist.py:37)。

调度在锁内检查 active_turn 并取出标志，锁外再 start_turn；期间可能有用户输入、目标替换或其他轮次启动。异常分支可能暂停当时仍 active 的目标。这里还没有确定性竞态复现，不能写成已发生事故。下一步用可控屏障验证：用户输入优先、不重复启动、不因旧续跑失败暂停新任务。

完成到队列推进之间的崩溃恢复、SSE 断线重连、后台进程结果未消费、并行工具结果乱序也未充分验证。持久化应版本化、验证字段、对无效证据作废并保留可恢复目标；不能静默把损坏状态视为完成。

相同工具反复调用应根据产物、检查结果及阻塞变化判断是否无进展，提醒换策略或诚实报告阻塞；不能固定 N 轮一律判失败，轮询长任务也可能合理。不能为了止循环擅自给用户增加预算限制。

## 建议的实施顺序与发布门槛

不建议继续增加面板或堆叠“必须认真完成”的提示词。建议按下面三个批次推进，每批通过对应反例后再进入下一批。

| 批次 | 实施内容 | 必须通过的验收 |
|---|---|---|
| 1：修复确定性缺陷 | 用户控制权限、动态 timer、线程身份绑定、反序列化、单一完成提交入口 | 未授权恢复/扩额拒绝；改预算按新期限；切线程不串写；损坏证据不崩溃/不完成 |
| 2：完成契约 | 需求验收项、证据关联、产物时效、需求变更依据、最终逐项审计 | 失败测试+pwd、删需求、旧证据、后台未结束等负例均不能完成；合法完成不被无关失败误拦 |
| 3：调度与实测 | 原子续跑仲裁、恢复故障注入、真实模型任务集 | 用户操作优先且只启动一次；重启不丢待办；实际完成率和误完成率达到预设标准 |

建议首轮建立至少 20 个固定任务，覆盖代码、研究、多要求交付、预算、中断和故障恢复，旧版/新版使用相同模型、工具权限与额度，各重复 3 次。由隐藏的验收检查或人工审阅评价结果，不能用 Goal 自己的 complete 状态作真值。若要声称与 Codex 效果相当，再增加 Codex 同任务对照，并披露模型与环境差异。

重点记录：错误完成率（声称完成但外部验收不通过）、真实完成率、错误阻塞率、无进展轮数、资源用量、恢复成功率。建议发布门槛是所有确定性关键反例为零失败、并发/崩溃矩阵通过、模型任务集无已知严重误完成，并报告样本数与波动。即使 60 次运行没有错误，也不能宣称错误率为零。

本轮只重跑 Goal 专项测试，没有重新执行全项目测试、桌面构建或真实模型对照。上一轮曾发现全项目 TypeScript typecheck 存在未改文件中的错误；这次未重新核实，不把旧构建结果当作本轮发布凭据。

**当前发布判定：继续内部验证，不建议宣称“已对齐 Codex”或“已解决过早完成”。** 现有基础值得保留；把上述反例变成会阻断发布的验收测试，才能从功能可用推进到可依赖。
