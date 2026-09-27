# 第九篇 · 模型客户端修复记录

日期：2026-09-27。基于现有未提交工作区继续修改，保留前八篇修复与其他开发改动。原始问题和方案见 [第九篇审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/09-client-streaming.md)。

## 实际实施

| 问题 | 修复行为 | 取舍及剩余边界 |
|---|---|---|
| L01 流结束被误判 | 两个解析器记录完成/失败状态，finalize 幂等；异常 EOF、错误或截断不再产生工具 complete。工具结果延迟到消息完成后提交；已知 usage 通过 truncated Done 先交付，随后发错误 | OpenAI 需要明确 finish reason；只有 `[DONE]` 或 EOF 的非标准输出不再算正常成功。Anthropic 工具块结束后还需 message_stop。正常完成样本的 JSON repair 保留，不把本轮扩大为参数修复策略重写 |
| L02 升配失去限流 | 时间窗口改为普通 deque，不因旧 maxlen 自动丢弃仍有效记录 | 保持按 key 的进程内共享语义；不新增跨进程限流，也未把内部 HTTP 重试改为逐尝试计数 |
| L03 视觉助手缓存失败样本 | 必须得到非截断 Done 且无错误才写入观察缓存；缺完成、失败、截断、取消均不提交投影 | 原消息和图片不改动，finally 仍关闭辅助客户端。成功结果才替换本次请求中的图片 |
| L04 错乱工具历史 | 用 assistant 之后连续 Role.TOOL 消息配对；结果必须唯一，重复 use ID 视为歧义；丢弃非法配对并记录数量 | 保留文字、消息顺序和同批合法配对；缺一个结果不会删掉其他完整配对。不猜测排序，也不修改原历史 |
| L05 未知模型误计价 | 精确识别四个已有模型名：deepseek-chat、deepseek-reasoner、deepseek-v4-flash、deepseek-v4-pro；未知名称返回 None | **局部修复**。费率常量与折扣边界保留，未核验当日报价。函数仍只有 model 输入，第三方路由使用完全相同模型名时，计价来源仍需未来显式建模 |
| L06 基类拼接重采样 | 未收到内容前保留有限透明重试；收到内容后出现网络异常，发错误并结束当前生成器 | Engine 已有清空缓冲后重新采样逻辑，继续负责重放。RetryConfig.max_error_retries 保留构造兼容，但不再控制基类的中途重放；没有增加 reset 事件协议 |
| L07 工具名称回放 | Chat/Anthropic 历史中的 ToolUseBlock.name 经过现有编码器；内部 `{type:tool,name:…}` 强制调用同样编码 | `{type:function,function:{name:…}}` 是已有 wire 形状，保持原值，避免重复编码。目录继续接收 registry 已编码的名称，存储历史仍用内部名称 |

实现：[streaming.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/streaming.py)、[rate_limit.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/rate_limit.py)、[media.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/media.py)、[normalize.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/normalize.py)、[pricing.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/pricing.py)、[base.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/base.py)、[chat_messages.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/chat_messages.py)、[anthropic.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/anthropic.py)、[deepseek.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/client/deepseek.py)。

## 对照证据

| 场景 | 修复前探针 | 修复后回归 |
|---|---|---|
| 未完成工具样本 EOF | 补全参数并发非截断 Done | 无工具 complete，truncated Done + 错误 |
| 相同时间窗口 limit 从 1 调至 3 | 连续六次全部获准 | 初次后并发十次只再获准两次，窗口累计三次；缩容不抹记录，60 秒过期可再调用 |
| 视觉文字后错误/截断 | 缓存 partial 并剥离本次图片 | 抛出失败，缓存为空，原图保留 |
| 工具结果在调用之前 | 原列表直接通过 | 去掉异常工具块，普通文字保留 |
| 基类网络异常后继续迭代 | partialcomplete | partial + StreamError，当前生成器终止 |
| 非 ASCII/连字符工具名 | schema 与历史名称不一致 | 目录、历史、内部强制调用编码一致，解析可还原 |
| 未知品牌模型 | 套用 Flash 费率 | 返回价格不可用 |

修复前数据仍保留在 [client-probe-results.json](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/client-probe-results.json)。旧 client_probe.py 的视觉失败路径现在会抛出预期异常，不再把它作为成功回归脚本执行。

## 验证与已知失败

新增 [38 项回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_client_audit_fixes.py) 全部通过，覆盖两种 HTTP 适配器、空流/EOF、正常结束、错误/截断、幂等、已知 usage、动态并发限流、视觉失败/取消/正常提交、工具配对、名称往返、价格别名及时间边界、重试分层。

扩大回归结果为 **491 passed，1 failed**。唯一失败是既有 [上下文预算测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_usage_token_semantics.py:133)，它要求低估的 real_input_tokens=204 把整个预算强行缩到 204，与此前上下文预算实现的回退行为不符。本轮没有修改此测试和预算实现。在临时源码副本中恢复本轮开始时的全部 client 文件后，该断言仍失败，确认不是本轮客户端修改引入；详细方法见验证记录。

另修正了一个正常 Anthropic SSE 测试夹具：最后 message_stop 帧补齐空行。原先该帧未被 httpx_sse 派发，靠不安全的 EOF finalize 才得到 complete；原有文本、工具、usage 与请求头断言全部保留。

MCP 既有相关测试另有 **77 passed**；它们用于下一篇审核基线，不代表已修复下一篇发现。相关 Ruff F、编译和 diff 空白检查通过。没有真实模型调用、没有更改或启动用户配置的 MCP 服务，未执行全仓或桌面端完整构建。

[验证记录](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/09-validation.json) · [第十篇：MCP 审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/10-mcp.md)
