# 第九篇 · 模型客户端与流式协议审核

日期：2026-09-27，基于当前工作区，接续 [第八篇修复](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/08-implemented-fixes.md)。覆盖 client/ 的 12 个 Python 模块，沿“路由构建 → 媒体投影 → 消息编码 → HTTP/SSE → 事件解析 → 限流/计量”检查。Engine 重试和工具编码只作边界追踪；MCP 连接生命周期留到下一篇。

**建议保留现有工厂、协议适配器与装饰器结构，先补齐完成状态和编码往返契约。** 目前最紧迫的不是再增加一个统一 Client 框架，而是底层把“连接结束”转成“正常完成”、辅助模型忽略失败事件，以及动态限流失效。

本篇保留修复前审核基线。七项发现的实施与剩余边界见 [第九篇修复记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/09-implemented-fixes.md)。本篇原始基线中的图片缓存装饰器属于第八篇 S06 修复。全部取证离线完成，未使用真实凭据、未发送模型请求、未核验当前服务商价格或宣称真实 API 一定返回某个状态码。

## 1. 逐模块结论

| 模块 | 通用性、架构与值得保留的设计 | 问题和建议 |
|---|---|---|
| `__init__.py` | 仅公开稳定构建入口和兼容类型，职责轻 | 暂无独立缺陷，不需要扩成插件注册框架 |
| `factory.py` | 配置选择 OpenAI/Anthropic 协议，允许未知 provider；统一检查缺失密钥 | 能力仍有模型/URL 子串启发式；后续显式能力配置优先。endpoint 测试与正式请求 URL/鉴权构造重复，适合提取少量纯函数，不宜重构整个传输层 |
| `base.py` | HTTP 连接复用、统一 close、带 jitter 的退避；计量装饰器保留真实 usage | 重试层责任重叠，输出后重放契约见 L06。计量只记录取得的 usage，不等于服务商最终账单 |
| `deepseek.py` | URL 版本前缀处理、请求字段映射、首包前重试与首包后分开 | EOF 完成判定见 L01；状态码重试位于限流装饰器内部，当前限流主要计算逻辑调用而非每个 HTTP 尝试 |
| `anthropic.py` | 独立消息投影、相邻角色合并、工具图像结果、显式缓存断点 | EOF 见 L01，工具关系/名称见 L04/L07。与 Chat 的失败语义应一致，消息形状仍应保持各协议独立 |
| `chat_messages.py` | 投影不直接修改原消息；保留 reasoning 与工具图片位置；有顺序配对清理 | 与 normalize 的规则部分重复，造成协议差异；工具名回放漏编码见 L07 |
| `normalize.py` | 提供 provider 无关的孤立块清理，不改输入 | 全局 ID 集合不足以验证轮次关系，见 L04；应形成可测试的局部配对规则 |
| `streaming.py` | 两种 SSE 转换为共享 StreamEvent，聚合 usage，识别长度截断 | 完成状态与 JSON 修复混在一起，见 L01；repair 反向依赖 engine.dispatch，适合以后移到协议无关纯函数模块 |
| `media.py` | 保留原历史，只投影请求；辅助视觉有超时、来源标记和有限条目缓存 | 失败/截断缓存见 L03；预算是估计值，不是最后序列化 payload 的严格字节上限 |
| `rate_limit.py` | 按密钥指纹共享进程窗口，失败快速返回，避免输出原密钥 | 调高 limit 后失效见 L02；不同路由共用同一 key 的额度语义需明确，长期唯一 key 条目也需回收 |
| `pricing.py` | usage 的缓存命中/未命中分开计算，时间可注入，便于测试 | 以品牌子串猜模型价格见 L05。建议未知价格保持未知，而不是宽泛回退 |
| `sanitize.py` | 在发送边界保护核心消息和凭据头；日志只记录被拒字段名 | 保留此层。它不是所有请求参数的完整验证器；extra_body 的采样/预算覆盖策略以后应由配置契约说明 |

整体通用性较好：新增兼容端点不需要复制 Engine。可扩展性的主要短板是能力/结束/重试契约没有集中表达，导致每位调用者自行猜测。优雅性的改进应落在少数纯函数和明确状态上，避免新建一套复杂继承体系。

## 2. 已复现问题与方案比较

### L01 · P1：无终止标记的 EOF 仍生成成功和补全后的工具调用

位置：[OpenAI finalize](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/streaming.py:154)、[Anthropic finalize](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/streaming.py:257)、[Chat 流入口](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/deepseek.py:118)、[Anthropic 流入口](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/anthropic.py:63)。

两个 HTTP 适配器在 SSE 迭代自然结束后都调用 finalize。解析器没有要求已见 finish_reason/message_stop；尚未完成的工具参数进入 JSON repair，再被包装成 StreamToolCallComplete，随后生成 truncated=False 的 StreamDone。

**真实适配器 + httpx.MockTransport 复现：**只发送工具开始和参数片段 `{"path":"x"`，不发送工具结束或消息完成事件就结束响应。两种协议均输出 `{"path":"x"}` 工具参数、非截断 Done、0 个错误。没有执行文件写入；这证明缺失参数会被修复成“完整调用”，不等于已绕过工具权限。Engine 会收集这些 complete 事件，协议层没有给它区分未完成样本的信号。

另外，OpenAI finalize 连调两次产生两个 Done；Anthropic 已有幂等保护。现有计量包装会保留最后 usage，因此不能把这个问题描述为当前必然重复计费。

方案比较：

1. EOF 一律报错：简单，但会拒绝有合法完成原因、仅缺最终传输哨兵的兼容端点。
2. **推荐：记录协议完成状态。** 明确工具块完成、消息完成、长度截断、错误和异常 EOF；合法 finish reason 可作为完成依据，不能用连接关闭代替。finalize 幂等；不把异常 EOF 的参数片段送去补全执行。
3. 每个 provider 独立容错开关：适合确有非标准网关的情况，但默认应保守，需显式配置与专门测试，不能从“已经有文字”推断成功。

验收：正常结束、usage 尾帧、空流、异常 EOF、工具参数半截、长度截断、重复 finalize、错误后 EOF。只有合法完成样本可进入执行；账单保留已知 usage。

### L02 · P1：首次窗口容量固定，调高限流值后可持续放行

位置：[RateLimitRegistry.try_acquire](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/rate_limit.py:46)。

首次用 limit=1 创建 deque(maxlen=1)，后续同 fingerprint 用 limit=3，队列长度永远最多为 1，因此 `len(window) >= 3` 永远不成立。冻结时钟，按 1、3、3、3、3、3 顺序调用，六次全部放行；应最多允许该窗口累计三次。调配置或同 key 构建不同 limit 的客户端即可触发。

推荐改用不自动丢弃仍有效记录的 deque，只按时间过期和限额拒绝；通常最多保留实际允许的窗口调用数。动态缩容也要保留已有记录，不能为适配新容量丢失计数。另一选择是每个 fingerprint 固定不可变策略，配置变化重建，但“重建清空计数”会允许额外突发，不推荐默默这样做。

额度归属需要另行明确：按 key、按 provider+key，还是按上游账户。当前 key 全局共享是已有设计，不应为修复此 bug 随意改变。验收包括升降配、共享 key 的并行请求、60 秒边界；本探针验证了升配反例，未声称测过跨进程配额。

### L03 · P1：视觉助手输出部分文字后失败或截断，仍缓存为有效观察

位置：[prepare_media_request.collect](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/media.py:89)。

collect 只处理 StreamTextDelta，忽略 StreamError 和 StreamDone.truncated。只要此前有非空文字，就写入缓存并在本次主模型请求中把图片替换为辅助观察。替身依次输出“Partial observation”及错误/截断 Done，两种情况都得到 `cached=true`、`images_left=0`。

原历史仍保留图片，故不是永久删除媒体；问题是失败观察被当成成功依据复用。超时和抛异常路径已有 finally close，应该保留。

推荐要求辅助调用明确完成、没有错误且未截断，才提交观察缓存；否则保留原输入并向上报告失败。使用一个新的模型“判断观察是否足够”成本更高，仍不能替代传输完整性。验收必须覆盖文字后错误、文字后截断、无 Done、取消、超时和正常缓存命中，不仅测空输出。

### L04 · P2：全局 ID 集合相等掩盖工具结果顺序和重复配对问题

位置：[normalize.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/normalize.py:16)、[Chat 局部清理](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/chat_messages.py:178)、[Anthropic 投影](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/anthropic.py:181)。

把 tool_result 放在相同 ID 的 tool_use 前面，use_ids/result_ids 集合相等，normalize 直接返回原列表。Anthropic 投影保留为 user(result) → assistant(use)。Chat 还有一层按 pending 调用清理，两个投影的归一化强度不一致。

这是历史恢复、压缩或异常输入边界，不是普通健康工具循环必然产生的历史。探针验证非法顺序得以保留，没有请求真实 provider，也不断言所有兼容端点都会拒绝。

方案：严格验证并报错，或按每轮相邻关系有损修复。推荐先共享配对校验结果，再由调用场景明确选择拒绝/降级，并记录诊断；不要悄悄排序，否则会改变时间语义。重复 ID、多工具并行结果、缺一个结果、跨用户消息配对都需纳入用例。

### L05 · P2：未知 DeepSeek 品牌模型被赋予 Flash 价格

位置：[_pricing_for_model_at](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/pricing.py:135)。

函数注释承诺未知模型返回 None，但除特殊前缀外，只要包含 deepseek、又不匹配 Pro，就使用 Flash 价格。`custom-deepseek-future` 因此得到价格。model 字符串也不能充分代表服务商路由和计价合同。

推荐使用明确的 model/alias 表，并逐步将 provider 或计价来源作为输入；未知模型显示价格不可用。更完整的可配置价格目录便于第三方端点，但引入维护成本，可后续添加。不要为了覆盖更多模型而扩大子串匹配。

本项只审查代码匹配规则，不评价常量是否符合 2026-09-27 当日报价。验收：未知模型、第三方同名模型、显式别名、折扣时间边界和缓存 token 分项。

### L06 · P2：基础重试生成器会在已输出文字后拼接新样本，主 Engine 另行防护

位置：[LLMClient.stream_with_retry](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/base.py:142)、[Engine 消费入口](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/turn.py:370)。

首次输出 partial 后抛 ReadError，基类先 yield retryable StreamError，再重试原请求。消费方若继续迭代，会收到 complete，最终文字是 partialcomplete；没有 attempt 标识或 reset 事件。

**风险范围不能夸大：**当前 TurnLoop 遇中途错误会 break 并清空缓冲重新采样，不会直接把上述拼接保存为成功消息。因此这是底层可复用接口与多层重试的契约缺口，而非已证明的主流程重复回答故障。

推荐传输层只负责未产出内容前的有限重试；产出后以错误结束，把重新采样交给掌握 UI/消息状态的上层。另一方案是显式 attempt/reset 事件，能服务更复杂调用者，但要求所有消费者升级，改动明显更大。合并重试前还要保留 HTTP 429/5xx 与内容阶段区别，并明确限流/计量按尝试还是逻辑请求计算。

### L07 · P2：工具目录已编码，历史回放却发送内部原名

位置：[Chat ToolUse 投影](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/chat_messages.py:55)、[Anthropic ToolUse 投影](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/anthropic.py:222)、[目录编码](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/registry.py:605)。

目录通过 to_api_tool_name 编码，流式解析通过 from_api_tool_name 解码，两个历史投影却直接写 block.name。对 `mcp:读取`，目录名为 `mcp-x00003A--x008BFB--x0053D6-`，两个历史字段均为原始 `mcp:读取`。因此同一请求中的定义与历史名称不一致，扩展工具更容易触发兼容性问题。

推荐在所有内部名→wire 的边界统一调用现有编码器，包括检查 forced tool choice 的名字约定。不要在存储历史中永久改成 wire 名，会污染内部 registry 查找并增加双重编码风险。验收用 ASCII、连字符、冒号、中文名字跑“目录 → 响应解码 → 历史再编码”的完整往返。

## 3. 性能与分层建议

第八篇已把同一 payload 的图片预算/序列化重复编码从 2 次降为 1 次，本篇不重复登记已修缺陷。其余性能点目前以静态分析为主，不能声称已有吞吐提升：

- 媒体预算在丢弃旧图前先编码全部图，旧图多时仍有不必要工作和瞬时 base64 内存。优先测真实历史分布，再考虑先决定保留集；单用像素估算取代最终字节校验会损失准确性。
- 工具参数分片列表没有自身字节上限；Engine 有流量/时间保护，但独立解析器调用者不一定继承。可在 parser 边界增加明确容量，避免完整 JSON 绕过 repair 阶段才有的限制；容量策略应与工具大参数需求一起评估。
- 限流窗口只在相同 key 再次访问时淘汰时间戳，字典 key 不主动回收。正常少量凭据影响小，多租户长期运行需有界回收；没有理由为单用户场景立即引入 Redis。
- 三处重试不应仅为减少重复代码而合成庞大基类。先确定“哪层有权重放”和“已输出内容怎样撤销”，再提取状态码、URL 等纯逻辑。

## 4. 证据、验收顺序与覆盖边界

[可重复探针](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/client_probe.py) · [原始结果](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/client-probe-results.json)

运行：`PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/client_probe.py`。使用临时 DEEPSEEK_HOME、假密钥、合成图片、固定时钟、MockTransport 和异步客户端替身。探针是当前缺陷的特征记录，不是断言这些行为正确的测试；修复时应转为期望安全行为的回归测试。

建议修复顺序：L01 完成边界 → L03 辅助模型提交条件 → L02 限流 → L07 编码往返 → L04 配对 → L06 重试职责 → L05 价格来源。对 L01/L03 可以先做严格、局部修复，不必等待整体 transport 重构。

本篇逐一检查了 12 个 client 模块，不覆盖每种商业网关的真实兼容性，也没有完成 protocol、tools、Server 的独立审核。下一篇：**MCP 连接、工具发现与调用生命周期**。
