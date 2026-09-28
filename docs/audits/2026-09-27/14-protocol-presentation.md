# 第十四篇：协议、事件模型与展示归约

日期：2026-09-28。接续第十三篇修复，逐个读取 `protocol/`、`presentation/` 的 **8 个 Python 模块，共 953 行**，并追踪 Engine 事件、TUI 消费、图片 token 估算和 HTTP 旁白的相邻调用。相邻调用链不等于下一篇 TUI 已审核完成。本篇保留修复前审核证据；当时只审核取证。**2026-09-28 已完成本篇 P01–P07 修复**，具体实现、验证及保留边界见 [14-implemented-fixes.md](14-implemented-fixes.md)。

整体判断：内容块和流事件采用带 discriminator 的联合类型，领域事件与 UI 状态分开，方向正确。主要问题是模型接受的输入范围比消费者能处理的范围大；展示归约器的隐含前提是“单来源、串行 round、无重复”。这适用于当前主路径，但若希望共用于事件重放、恢复和多端展示，必须明确事件身份和状态转换。暂不建议把所有协议、引擎事件、HTTP 记录强行合并成一个万能 Event。

证据：A＝本地探针直接复现；B＝生产调用链/实现可确认；C＝设计建议或扩展条件。可执行探针为 [presentation_probe.py](presentation_probe.py)，输出为 [presentation-probe-results.json](presentation-probe-results.json)。探针记录当前行为，不是把缺陷行为固化为正确性的回归测试。

## P01 · P2：图片模型允许消费者无法估算的裁剪尺寸（A/B）

位置：[messages.py:53](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/messages.py:53)，以及 [media.py:163](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/media.py:163)。`ImageBlock` 的 width/height/byte_size 有正数约束，crop 却只是四个整数。`crop=(0,0,0,0)` 能构造成功，传给 `image_token_estimate` 产生 `ZeroDivisionError`。Engine 的 context/capacity 在发送图片前就调用该估算，后面的图片编码范围校验不能保护它。

建议先在模型校验非负坐标、正裁剪宽高，消费者仍保留对真实图片尺寸的最终校验。是否直接按声明 width/height 拒绝越界要结合 EXIF 旋转语义，不能只依据字段名称猜测。另一方案是只在估算器兜底，但会让非法模型继续流入持久化和其他消费者，不如边界校验清晰。

验收：零/负尺寸、负坐标、旋转图片、合法边缘裁剪、旧 session 读取；错误应成为输入验证错误，不能在预算阶段崩溃。

## P02 · P2：MCP 失败包装的内层 type 可以覆盖外层状态（A）

位置：[events.py:68](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/events.py:68)。`{"type": "failed", **payload}` 允许 payload 再提供 type。探针传入 `{"failed":{"error":"broken","type":"ready"}}`，得到的序列化结果是 `"ready"`，error 被丢弃。

目前没有证据表明正常 MCP 生命周期生产者会生成这种矛盾数据，不把它定性成可利用的远程攻击。问题在于兼容解码器接受了自相矛盾的状态。最小修复是显式取 error 并固定 failed 标签；若要严格拒绝额外键，应在兼容输入边界实施，避免对所有历史模型一刀切 `extra=forbid`。四个合法状态的 JSON 往返已经用探针验证，修复应保留。

## P03 · P2：重复 round 会重建批次，抹掉已经完成的工具状态（A/C）

位置：[reducer.py:35](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/reducer.py:35)。同一 round 包含 a/b，a 完成后重放 round，再收到 b 完成：新批次只记录 b，状态仍为 running，round_count 变成 2。工具结果重复已被处理，但 round 声明没有相同的幂等约定。

当前 TUI 直接消费 Engine 队列，没有在这里证明正常运行一定产生重复 round；这是复用于断线重放/恢复时的确定性缺口。建议先明确实例是否仅服务单 turn：若是，以 round_idx 和工具 ID 签名识别相同声明，重复返回同一视图，矛盾声明报错或显式重置。若跨 turn 使用，再增加 turn_id；不要先引入全局事件注册中心。

验收：结果前/后的重复声明、同 round 不同工具集合、跨 turn 相同 round_idx、重复完成后不重新折叠 UI。

## P04 · P2：取消只处理最新批次，终态语义不一致（A/C）

位置：[reducer.py:91](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/reducer.py:91)、[models.py:46](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/models.py:46)。若旧批次尚未完成就声明新批次，取消只 detach 新批次：旧批次仍 running，旧工具映射仍保留。另外取消后的 `status == "cancelled"`，`is_terminal` 却为 False，因为后者实际上表示“所有工具已收到结果”。

主 Engine 当前以轮次串行执行为主，因此重叠输入不是已证明的常见线上路径。仍应选定并编码一个契约：A）严格单活跃批次，拒绝重叠；B）支持多个批次，取消时遍历所有运行批次并清理。建议当前先选 A；若未来做多来源事件汇聚再选 B。把 `all_results_received` 与生命周期终态区分，比给 cancelled 伪造失败结果更清楚。

验收：cancel→迟到结果不得复活、取消幂等、无残留映射、已完成批次状态不被取消改写。

## P05 · P2：展示分类把“可能写入”当成“正在修改”（A/B）

位置：[semantics.py:85](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/semantics.py:85)。`exec_shell` 固定属于 MUTATE，因此 `cat README.md`、`pytest -q`、`touch output.txt` 都得到“实施修改并准备验证”，phase 都进入 CHANGE。将 shell 保守视为有写权限的做法适用于安全策略，却不适合用来断言用户正在看到的操作意图。

最小方案：无法确定用途的 shell 显示中性“执行命令”，不要靠字符串命中测试名称断言验证成功。后续若工具执行层已有稳定的意图/能力标签，可以传给展示层，工具名映射作为兜底。不要重新实现一套 shell 语法/安全分析器。MCP/插件工具默认 MIXED 是可接受的退化行为，不能把未知工具默认为只读。

另一个小问题在 [semantics.py:105](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/semantics.py:105)：`/Users/example/project/src` 的 batch_root 返回 `Users`，不对应项目目录。建议传入展示基准目录后显示相对路径，无法相对化时显示安全截断后的完整路径或末级目录；纯函数不应自行读取 cwd。

## P06 · P2：请求与用量模型缺少最低合法性约束（A/B）

位置：[messages.py:152](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/messages.py:152)、[responses.py:9](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/responses.py:9)。空 model、max_tokens=-1、temperature=NaN 可以构造；Usage 也接受负 token。探针只证明模型接受这些值，不声称每个正常 provider 都会返回它们，也不把所有下游成本计算都认定为负数漏洞。

建议只在共享层加入跨 provider 成立的约束：非空模型、正输出预算、有限浮点、非负计数。temperature/top_p 的具体取值范围、reasoning_effort 枚举、工具参数兼容性留在 provider adapter；不要为了统一模型误拒绝合法扩展。历史 Usage 输入的处理可选择明确报错或 adapter 归一化并标记异常，但不应静默靠正负抵消。

已有 `input_tokens_include_cache` 标记和别名支持值得保留：不同 provider 的 input_tokens 是否包含缓存确实不同。不要为了减少字段重新根据数值大小猜语义。

## P07 · P3：批次结果归约在大批量下重复分配集合（A/B）

位置：[models.py:67](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/models.py:67)。每次结果都做 tuple 成员查询、terminal_ids 的集合合并、expected_tool_ids 的集合重建，整批成本随数量趋于平方增长。

同进程、相同 ID、倒序完成，7 次中位数，计时不含对象构造；在扩展测试运行期间测量，仅作趋势证据：

| 工具数量 | 当前模型 ms | 集合增量原型 ms |
|---:|---:|---:|
| 16 | 0.0069 | 0.0012 |
| 256 | 0.9562 | 0.0164 |
| 2,048 | 73.6606 | 0.1247 |

原型仅覆盖成员判断、完成判定和错误状态，并横向验证了乱序、重复、未知 ID、denied 的结果；不包含 UI、审批、序列化和渲染，因此不能把倍率当作端到端提速。常见十几个工具的批次成本很低，优先级低于 P01–P06。若确实要支持大批次，缓存不可变 expected 集合、维护 terminal 集合即可；单纯增加缓存但允许外部修改所有 sets，会产生缓存失效问题，要一并收紧状态写入入口。

## 逐模块审核建议

| 模块 | 通用性与已有设计 | 主要限制与最终建议 |
|---|---|---|
| [protocol/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/__init__.py) | 明确公开入口，内容、流事件和 MCP 兼容类型可单独导入。 | ImageBlock、MessageOrigin 未出现在聚合导出，但子模块可导入，不能仅凭不对称认定功能 bug。明确“完整协议入口”还是“历史兼容入口”，需要公开时再补兼容测试，不做无依据的大搬家。 |
| [protocol/messages.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/messages.py) | ContentBlock discriminator 清晰；媒体仅存引用，origin 与传输序列化分离，扩展方式合理。 | 修 P01/P06。ToolUseBlock、ToolCall 的字段相似但分别承担持久化内容和调用结果，不必合并；在转换边界测试 ID/arguments 保真即可。角色与内容组合规则依 provider 不同，建议验证发送前的完整请求，而不是把所有限制塞进 Message 构造器。 |
| [protocol/responses.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/responses.py) | StreamEvent 有 discriminator，错误/终止独立，truncated 字段保留输出截断信息；Usage 缓存语义显式。 | 修 P06 的计数合法性；保留 provider 适配边界。协议模型只能描述单事件，done 恰好一次、delta 在 done 之后非法等流时序应由 parser/聚合器的契约测试负责，不在模型里制造全局状态。 |
| [protocol/events.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/protocol/events.py) | MCP 启动状态支持旧 wire 形式，frame 外层拒绝额外字段，兼容层小。 | 修 P02；明确外层包装与内层标签的优先级。McpStartupCompleteEvent 的 ready/failed/cancelled 可接受重复/重叠服务器名称，属于额外可考虑的一致性校验，尚未证明当前生产者违反它。 |
| [presentation/__init__.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/__init__.py) | 仅模块说明，无初始化副作用。 | 保留；当前没有为了“可拓展性”建立注册器或 facade 的需求。 |
| [presentation/models.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/models.py) | ToolActionView 冻结，批次聚合与结果幂等集中在模型，UI 不必重复推断完成条件。 | 修 P04 的命名/终态约定；P07 按规模需要优化。ActionBatchView 可变 sets 是外部能绕过状态方法的入口，先约定单写入者，再决定是否给 UI 只读快照。phase/batch_kind 当前是 str，若移入共享枚举需要避免 models↔semantics 循环依赖。 |
| [presentation/reducer.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/reducer.py) | 不依赖具体 widget，终态工具结果只触发一次完成回调，函数易测。 | 修 P03/P04。`AgentRoundCompleteEvent` 仅作注解却在运行时导入 engine.events；可先移到 TYPE_CHECKING，降低纯展示层的运行时耦合。将来真正多事件来源时再引入小型展示输入 DTO，暂不做通用事件总线。 |
| [presentation/semantics.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/presentation/semantics.py) | 分类、阶段、模板均是纯函数，本地化和降级路径易替换。 | 修 P05。保留规则兜底，让调用方传入可信展示意图；避免按工具名字或 shell 片段宣称修改/验证事实。`batch_intent_text(INSPECT, [])` 存在隐含非空前提，当前 reducer 先检查非空，外部公开使用时应明确契约。 |

## 架构方案与实施顺序

| 方案 | 范围与收益 | 成本与选择 |
|---|---|---|
| A：校验边界 + 单 turn/单活跃 batch 契约 | 修输入崩溃、矛盾状态、重复声明，保留当前 Engine→TUI 链路。 | 改动最小，建议先做；需要补恢复/取消序列测试。 |
| B：独立 PresentationEvent 输入 + 多批次 reducer | 支持 TUI、HTTP、日志重放共用同一展示状态机，单写入者输出只读视图。 | 需要定义 turn/round/tool 身份、来源与恢复协议，适合真正接通 HTTP 展示归约时实施。 |
| C：统一所有协议与事件并生成多端 schema | 能统一版本管理、兼容演进及端到端重放。 | 当前三个层级的职责不同，直接统一会耦合模型流、执行生命周期和 HTTP 持久化；目前不推荐。 |

建议顺序：先 P01/P02/P06 校验，再 P03/P04 生命周期，随后 P05 文案准确性，最后按真实规模决定 P07。第十三篇新增的 `stream.resync_required` 仍需要客户端收到后重新获取 thread/items 快照；这属于 HTTP 事件适配器的协议，不应直接塞进只消费 Engine 事件的 reducer。

## 验证与边界

针对 presentation、Usage 语义、流终止/截断的现有测试：50 passed，1 deselected。首次完整选择为 50 passed、1 failed：`test_context_breakdown_uses_full_prompt_instead_of_uncached_remainder` 期望 total=204，实际为 7821，涉及此前预算估算语义；本轮未修改协议/展示或 engine/context 源码，没有为了本篇改写该旧断言。此失败不计作本轮修复通过。详见 [14-validation.json](14-validation.json)。

没有调用真实模型/网络，没有测试 Windows UI，没有把大批次微基准当作用户可感知性能。下一篇：**TUI 生命周期、输入、会话切换与展示组件**；重点验证任务取消/退出、事件监听重启、消息与工具卡片归约以及会话恢复的一致性。
