# 第六篇下篇 · 第二轮优化记录

日期：2026-09-27。接续 [上下文审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-context.md) 中尚未实施的建议。本轮完成下面的局部行为修复，之后继续交付 [第七篇 Goal 审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-goal.md)。保留用户原有改动，没有重写整个上下文或持久化体系。

## 已实施

| 项目 | 新行为 | 验证与取舍 |
|---|---|---|
| 摘要请求容量 | 普通摘要和 cycle briefing 在调用 Provider 前检查完整消息、system、tools 与显式输出额度的估算总量，包含 previous_summary | 超窗不调用 Provider；不自动删掉 previous_summary 中的约束。确定性容量失败不重复请求三次 |
| 压缩候选验收 | 构建桥、请求片段、图片引用和保留消息后比较前后估算量；候选没有缩减则拒绝。自动压缩另使用主请求实际模型、system、工具目录和输出额度检查窗口 | 无收益/仍超窗都返回原 messages；有收益且满足容量的正例可提交。采用严格减少，而未发明任意百分比收益门槛 |
| 摘要与主请求模型 | 生成摘要时显式 compaction model 优先，其次本回合模型，再次默认模型；提交候选按主请求模型的窗口验收 | 避免自定义摘要模型的大窗口被错当成主请求窗口 |
| 失败诊断 | CompactionResult 增加 failure_reason；全部被固定、可摘要内容太少、候选无缩减、容量超限有具体说明 | HTTP 手动压缩和 TUI 会展示该原因；其他失败仍可查看日志 |
| 校准生命周期 | 切换 Provider/模型路由清空两个实测锚点；不同回合模型进入工具循环时失效旧测量 | 同名模型更换客户端也会清空；未提供配对估算时取旧实测与当前估算较大者，防止忽略新增消息；上下文面板同步采用该保守规则 |
| 当前日期 | process_today 每次读取本地日期，同一天输出稳定，跨午夜刷新 | 接受每日一次前缀变化，优先保证 today 真实；不会主动中断已经构建好的请求 |
| briefing 长度 | 改用统一 estimate_tokens 对完整文本和截断标记一起限额，覆盖 CJK；非正额度返回空 | 是本地估算上限，不宣称与每个 Provider tokenizer 精确一致 |
| 请求账本表述 | 将“所有请求完整原文”改为“按时间顺序保留的请求片段，可能缩短” | 原有长度策略保留，避免短账本冒充无损存档；未暗中增加另一套存储 |

实现入口：[capacity.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/capacity.py)、[maintenance.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/maintenance.py)、[core.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/core.py)、[context_pressure.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context_pressure.py)、[context.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context.py)、[cycle.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/cycle.py)、[prompts.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/prompts.py)。

## 复核修正与尚存边界

1. 原审核称 prompt 构造可能自动生成缺省指令文件，这个描述过宽。当前 build_system_prompt 与上下文面板均传 allow_auto_generate=False，已是只读加载；底层 loader 默认仍可生成占位文件。此次不重复修改调用者，也没有删除现有显式初始化能力。同步读文件仍存在，未测出瓶颈前不新增缓存失效体系。
2. 容量检查基于本地估算，无法保证任意 Provider 的真实计数完全一致。超大的摘要输入目前明确拒绝，而不是自适应重新分配摘要输入；这是保护约束的保守选择，可能降低小窗口压缩成功率。
3. 自动压缩路径获得完整主请求信息。手动和 TurnLoop 的旧应急 callback 只传消息，仍检查消息缩减和摘要请求容量，但没有额外重建所有调用时的自定义 system/工具/输出参数；真正发请求前仍由 TurnLoop 的完整请求预检兜底。要把所有入口统一成完全相同的候选验收，需要升级 callback 契约，不应宣称本轮已完成。
4. 没有新增原始用户请求的独立耐久存档；账本仍会截短、删除中间条目。要保证恢复后能重读原文，应在状态篇统一会话日志、压缩归档、读取权限和保留期限，避免多套历史源不一致。
5. ReminderSpec 的 priority/placement 仍由注入点落实；max_chars 仍不是封套后的硬上限。当前没有新增多种门的需求，不为声明字段建立新的调度框架。
6. 已有 Provider 测量配对时仍沿用加性校准。动态工具格式变化和未通过 set_model_route 的直接客户端赋值不属于本轮新增的失效保证；应通过统一路由入口更新配置。

## 验证

新增 [12 项定向回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/engine/test_context_followup.py)：跨日日期、中文/英文 briefing、无锚点增长、摘要静态提示与输出额度、超长旧摘要、无收益/仍超窗拒绝、有收益提交、模型路由失效、cycle 超窗、全部固定的诊断。

旧面板测试要验证“实测小于估算时缩放分类”，现在显式提供与实测匹配的估算锚点，保持这个断言；无锚点的行为由新增测试单独覆盖。没有删除旧检查以迁就实现。

最终相关测试 **425 passed**，包含 Engine、Goal 和上下文/压缩/子 Agent 溢出等合同测试；12 项已包含其中，不重复相加。编译、主要修改文件 Ruff F 和相关 diff 空白检查通过。context.py 原有 re 导入问题不在本次清理范围；未声称全仓 lint 通过。没有真实模型调用，没有重跑整个桌面构建。

完整命令与边界见 [验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-context-followup-validation.json)。
