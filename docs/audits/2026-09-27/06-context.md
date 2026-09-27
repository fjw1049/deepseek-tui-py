# 06 · 上下文预算、压缩与提示词审核（下篇，含修复）

**后续状态：下文第 4 节的建议已继续复核和局部实施，最新行为、修正与剩余边界见 [第二轮优化记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-context-followup.md)。下文原验证数据保留为第一轮记录。下一篇 [Goal 审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/07-goal.md) 已交付。**

基线：2026-09-27 当前工作区，接续 [Engine 上篇修复](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-implemented-fixes.md)。本篇按“估算 → 选择保留内容 → 生成摘要 → 替换历史 → 后续恢复”的调用链审核，覆盖 capacity、context、context_pressure、maintenance、prefix_probe、prompts、reminders，以及 cycle 的归档部分。不是对所有模型、所有提示词输出效果的全面认证。

**结论：保留分层压缩与显式来源标签；本次优先补齐历史替换前的完整性检查、消息配对、真实回合计数和工作集顺序。** 系统已有不少合理组件，问题主要出在组件接缝：字段改名后调用者没更新、文本到达被当成请求成功、固定消息时没有连带固定协议依赖。

本篇列出 8 项已落地的修复；另外明确列出尚未实施的策略建议。所有验证均为离线假客户端与临时目录，没有用真实模型判断摘要质量。

## 1. 应保留的设计与总体评价

- L0 裁剪工具输出、重写摘要、cycle 归档分别承担不同成本；压缩触发统一读取 ContextPressure，比各处写固定阈值好。
- 压缩桥进入消息历史，不把不断变化的摘要塞进 system prompt；原始用户请求单独保留，且有 MessageOrigin 区分机器提醒。
- cycle 归档原子替换文件，并把归档路径写入种子消息、仅对本会话开放只读访问；“摘要不等于证据”的提示应保留。
- prefix_probe 指纹不记录正文，且允许使用客户端实际序列化单元诊断前缀变化；适合作为诊断，不应反过来支配正确性。
- ReminderSpec 把 envelope、来源、放置位置和长度意图放在一起，减少注入点各自拼接文本的错误。

| 维度 | 判断 | 本次重点 |
|---|---|---|
| 通用性 | 主要契约能跨模型复用，但摘要预算仍有硬编码模型名和固定字符分档 | 使用配置中的窗口信息，尊重显式摘要模型 |
| 优雅性 | 纯函数较多，容易构造小型反例；maintenance 把生命周期编排集中起来是合理的 | 保持纯函数，不再增加平行的压缩状态来源 |
| 可扩展性 | 来源标签、结构化状态、工作集是有效扩展点 | 标签优先于文本猜测；消息保留规则必须考虑协议依赖 |
| 架构合理性 | 摘要生成与历史提交没有足够明确的成功边界 | 显式错误、截断、空结果不得被当成可提交历史 |
| 性能 | L0 年龄计算存在可复现的平方级重复扫描 | 一次逆序计数，再线性裁剪，验证输出一致 |

## 2. 已确认并修复的问题

### C01 · P1：cycle 的摘要生成实际从未被调用

位置：[maintenance._maybe_advance_cycle](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/maintenance.py)。

旧代码调用 `cycle_config.briefing_max_for(model)`，但 CycleConfig 只有 `briefing_max_tokens` 字段。AttributeError 被通用异常捕获，随后走无摘要分支，保留最近 16 条消息并递增 cycle 编号。

旧探针：30 条历史触发 cycle，produce_briefing 调用次数为 **0**，cycle 编号却变成 **1**。归档文件仍在，不能称原始数据完全消失；但模型活动上下文确实丢掉了前段历史，且没有模型摘要接替。

**已修复：** 使用真实字段；摘要失败或为空时保留原活动历史，不推进 cycle。归档可以保留为检查材料，但归档成功本身不再等价于可以替换上下文。

取舍：历史不缩小意味着压力可能仍高，后续普通 compaction/错误恢复仍需处理；比把一次编程错误伪装成成功的 cycle 更可诊断。没有新增未经产品定义的“强制丢弃旧消息”模式。

### C02 · P1：先收到文本、再收到错误，摘要仍被当作成功

位置：[capacity._create_summary](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/capacity.py)、[cycle.produce_briefing](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/cycle.py)。

旧代码只累加文本，不检查 StreamError 或 StreamDone.truncated。反例流先发送包含 Goal/Next step 的文本，再发送 connection lost；摘要函数仍返回看似合法的内容。纯标题验证无法证明传输完整。

**已修复：** 两条生成路径拒绝显式流错误和截断。普通 compaction 通过既有重试路径处理，最终失败返回原历史；cycle 遵循 C01 的保留原历史策略。

这没有证明摘要事实正确，也没有强制所有假客户端必须输出 StreamDone；只消除了已经明确报告失败却仍提交部分文本的问题。未来可把“传输成功、格式合格、容量有收益”建成一个集中验收步骤，不必立即引入复杂的摘要评审 Agent。

### C03 · P1：固定工具结果时，可能把对应工具调用压缩掉

位置：[capacity.plan_compaction](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/capacity.py)。

原先最近窗口会避开以 TOOL 行开头，但工作集传入的任意 pinned_indices 不受这条规则保护。单独固定一个较老的 ToolResult，就可能把其父 ToolUse 留在待摘要集合。

旧探针：结果索引 1 被保留，对应调用索引 0 未保留。更复杂时，一个 assistant 行包含多个工具调用，仅补父行仍会丢掉其他兄弟结果。

**已修复：** 根据 tool_use_id 建立消息间依赖，保留任一端时扩展到整个关联工具批次。测试分别固定调用行、第一结果和第二结果，三种情况均保留完整调用/结果组。

取舍：固定内容可能更多，这正是协议完整性的成本。后续预算紧张时应按完整交换组决定保留或摘要，不能恢复按行切断的逻辑。输入本来就缺失结果的历史，不由这个函数凭空补造。

### C04 · P2：运行时提醒被当作用户回合，且年龄计算反复扫描后缀

位置：[capacity 的回合年龄与 L0 裁剪](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/capacity.py)。

原年龄函数把所有 user 角色都算作用户回合；系统提醒、Goal 续跑、历史账本也使用这个角色。旧探针在一个新工具结果后追加 15 条 SYSTEM_REMINDER，它立即被清成“too old”。

此外，每个候选工具结果分别扫描后续全部消息；硬清除收益预估又做一次同类扫描，历史越长重复工作越多。

**已修复：** 复用已有来源判定，只计真实用户载体；一次逆序构建年龄数组，在两条裁剪路径中按索引查询。未引入跨请求缓存，因此不会被消息增删或来源变化弄脏。

下文基准用正常用户回合检验性能改动前后输出完全一致；来源修复则用独立的机器提醒反例检验，二者不混成“所有输出不变”的主张。

### C05 · P2：用户请求中的分隔标签会截断请求账本

位置：[context_pressure 的请求账本编码/解析](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context_pressure.py)。

请求直接放入 `<prior_user_requests>`，解析器用第一个关闭标签结束。旧反例：`Preserve </prior_user_requests> this exact constraint` 往返后只剩 `Preserve`。

**已修复：** 新账本对条目内容做 HTML 实体转义，并带明确编码版本标记；解析时只有该版本才解码。老账本仍按原格式读取，避免把旧用户原本输入的字面 `&amp;` 错改成 `&`。测试覆盖关闭标签、实体、多行编号和多次往返。

这是内容编码修复，不是提高这段文本的指令权限。账本仍有长度裁剪策略，不能据此宣称无限长用户要求已无损保存。

### C06 · P2：工作集既不保证最近顺序，工具参数入口又没有执行数量上限

位置：[context.WorkingSet](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context.py)。

recent_paths 原为 set，但 top_paths 取列表尾部并声称“最近”；这没有访问顺序保证。文本和 reference 入口做了数量裁剪，工具字典入口却只 add。旧探针通过 110 次工具参数观察得到 **110 个路径**，超过声明的 100；top_paths(0) 也返回全部 110 个。

**已修复：** 使用保留插入顺序的 dict，每次观察先移除再放到尾部；所有入口共用 `_remember_path`，统一保留最近 100 个，零/负 limit 返回空列表。无需外部 LRU 库。

### C07 · P2：显式摘要模型被默认模型盖掉，摘要输入分档靠模型名猜测

位置：[maintenance._run_compaction](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/maintenance.py)、[capacity._summary_input_limits_for_model](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/capacity.py)。

Engine 始终把 default_model 作为 model_override，导致 CompactionConfig.model 不起作用。输入分档又把名称含 reasoner 的模型直接当作大窗口，对自定义 Provider 不通用。

**已修复：** 显式 compaction model 优先，未指定才继承默认模型；输入分档读取注册的 context_window_for_model。测试覆盖名称包含 reasoner 但窗口只有 8K，以及名字陌生但窗口为 1M 的模型。

限制：现在仍是两档字符预算，不是按实际请求 token 严格装箱。小窗口、CJK、很长 previous_summary 组合仍需要进一步的完整请求预算验收。

### C08 · P2：明确标为真人输入的文本，仍可能被识别成压缩桥

位置：[context_pressure.is_compaction_bridge_message](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context_pressure.py)。

原判断在非 COMPACTION_BRIDGE 情况下仍检查正文前缀与标签。用户粘贴桥接格式作示例，即使 origin=REAL_USER，也会被识别为旧桥，进入删除旧桥的逻辑。

**已修复：** 只要有显式 origin，就以来源为准；文本猜测仅兼容没有来源信息的旧消息。真人示例和真实压缩桥使用相同文本，测试验证两者仍能正确区分。

## 3. 性能与方案横向比较

同一脚本、同样的真实 prune_old_tool_results 调用，修改前后分别运行 5 次。数据包含正常用户回合与 5,000 字符工具结果；消息生成和结果哈希不计入裁剪时间。

| 历史规模 | 修改前中位耗时 | 本次中位耗时 | 内容验证 |
|---|---:|---:|---|
| 400 条消息 | 2.785ms | 0.988ms | 195 条工具结果变化；前后 SHA-256 一致 |
| 1,600 条消息 | 34.621ms | 3.726ms | 795 条工具结果变化；前后 SHA-256 一致 |

这是本机合成历史的函数级测量，不是整个会话加速比例，也未覆盖磁盘、网络和模型耗时。

方案比较：

1. **一次逆序年龄数组，已采用。** 每次裁剪计算即可，逻辑局部、无需失效策略。
2. 跨轮保留消息年龄索引。可能少做一次线性扫描，但压缩、恢复、插入提醒都会改变索引，本次没有性能证据支持增加这层状态。
3. 把历史整体搬到数据库查询。针对当前瓶颈过重；只有真实持久化查询规模要求时再评估。

[基准脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/context_prune_compare.py) · [修改前](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/context-prune-before.json) · [修改后](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/context-prune-after.json)

## 4. 逐模块建议与尚未实施的部分

| 模块 | 已审职责、保留项与下一步建议 |
|---|---|
| capacity.py | 压缩计划、摘要生成、摘要输入分档、L0 裁剪。C02/C03/C04/C07 已修。下一步在提交摘要前比较完整请求预算及最小缩减收益；当前格式成功不代表上下文一定变小。对固定太多内容导致无法压缩，应给出明确诊断，而不是破坏工具配对 |
| context.py | token 估算、上下文分类、项目指令加载、工作集。C06 已修。项目文件读取有大小限制，但 prompt 构造会进行文件系统读取和缺省指令文件生成；建议后续将读取快照与显式初始化分开，按真实 I/O 测量决定是否缓存。不要只因文件长就拆出一批无语义 helper |
| context_pressure.py | 统一占用信号、来源、桥、用户请求账本。C05/C08 已修。real_input_tokens 没有匹配的 estimate 时仍直接使用旧测量，切换模型/序列化方式时应一起失效校准锚点；这条跨模型策略本轮没有改。请求条目仍限约 2K 字符、总条目约 20K，并可能裁剪中间要求，“verbatim”只能理解为保留下来的片段 |
| orchestrator/maintenance.py | 压缩/cycle 编排、摘要记录、检查点及会话保存接口。C01/C07 已修。继续保持“生成候选→验证→提交”的方向；全量持久化还是同步且 best effort，真实持久化保证会在状态篇复核，不能因本篇通过就视为完整耐久性审核 |
| cycle.py | 阈值、briefing、归档、seed 与结构化状态。C01/C02 和上篇事件交付已修。归档路径可重读、来源可持久化应保留。briefing cap 仍以约 4 字符/token 裁剪，中文和不同 tokenizer 下不是硬 token 上限；建议与实际预算估算统一 |
| prefix_probe.py | 指纹、权重、首次差异诊断。保留不记录正文的设计；provider 渲染单元优先于概念单元。没有找到本篇需要立即修复的正确性问题。单元序列化/估算可能重复，但未测得瓶颈，不新增缓存 |
| prompts.py | 稳定/动态层、环境信息、模板、工具 profile。分层方向合理。process_today 仍冻结首次调用日期，长期运行的服务器会把启动日期写作 today；可选“每日刷新环境日期”或“稳定启动日期 + 消息尾部当前日期”，后者更保前缀。此项尚未改，不把缓存稳定误称日期正确 |
| reminders.py | envelope、origin、placement、priority 与长度意图。保留显式来源和统一渲染。placement/priority 是声明，最终顺序仍靠注入点；如后续新增多种门，应统一调度排序并在集成测试验证。max_chars 后还会追加说明/封套，它不是完整消息硬上限 |

目前不建议进行全套架构重写。最有价值的后续工作是：完整请求容量验收、校准锚点生命周期、长期运行的当前日期，以及有明确保留策略的原始用户请求存档。这些需要各自独立的触发样本和产品契约，不能靠“更优雅”的抽象替代。

## 5. 验证与后续顺序

- [16 项新增上下文回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/engine/test_context_audit_fixes.py)，涵盖上述 8 项修复。
- [修复前反例脚本](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/context_probe.py)与[旧结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/context-probe-results.json)保留用于追溯；它们的断言描述旧缺陷，不应当作当前通过测试。
- [工作集旧结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/context-working-set-before.json)记录了超限与零 limit 行为。
- 最终相关测试合计 **458 passed、3 skipped、1 deselected**，包含上篇修复验证；没有重复累加成两个总数。具体命令和排除原因见 [验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-validation.json)与[上篇修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/06-implemented-fixes.md)。

Engine 上下篇至此交付。协议文本解析、插件规则、持久化与 UI 的专项边界继续保留在各自篇章，不把它们算作本次全部审核完成。下一体系：**Goal 模式、目标队列与完成判定**，结合仓库已有 Goal 审核材料复核当前实现。
