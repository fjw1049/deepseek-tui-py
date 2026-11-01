# 浏览器工具：值得吸收的机制与实施顺序

日期：2026-10-11。依据：当前工作区、此前 Codex `26.1007.21159/build 20052` 审核证据、本轮接口探针与选定测试。本文是审查和设计建议，没有修改业务代码。原始审核见 [REPORT.md](../codex-browser-use/REPORT.md)。

**最后复核发现工作区已有后续修改：此前 G1、G2、部分 G5/G6/G8 已有实现，不能继续按未修复问题处理。** 原报告与 ZIP 保留当时证据；当前采纳状态以本文为准。

## 判断

当前工具已有正确的基础：chat 内共享持久浏览器、明确 tab/document/控制代际、失效 ref 拒绝、动作后观察、执行与效果收据、人工协助暂停恢复、开放 shadow/同源 frame、条件等待和视觉能力区分。

最需要吸收的是把这些机制贯穿整个模型执行循环。浏览器端知道正确目标、工具返回成功、模型收到足够证据、业务结果确实完成，是四个不同的条件。下一阶段应集中于记录与区域定位、按需观察、任务结果验证、可信观察边界和少量受控序列。

推荐保留现有 Octop/CDP 后端和主模型决策路径，从模型收到的观察、精确目标、派发和验证契约开始改善。没有证据要求现在替换整套后端或复制 Codex 私有 RPC/WASM。

## 1. 先确保模型收到可操作的观察

**已吸收，继续验证。** 最新 observe 不再重复完整 JSON；新增 `browser/context.py` 从 metadata 结构化投影，保留 observation 身份、receipt 和完整控件对象，避开 spillover 后文本损坏。另有 text/element offset、下一页位置与总控件数。本轮 **5 项上下文测试通过**，覆盖不同压力与 spillover；真实 Chrome 的长页面续读测试也通过。

此前 G1 证明旧投影损坏，没有证明真实模型任务失败。现有实现已经吸收关键方向。接下来应参考 Codex 多种观察表示、局部/增量读取的思路继续完善：

- 先按任务区域/记录读取正文与控件，保留身份、收据、遗漏和继续读取方式。
- 压缩后 name/options 等详情应可补读，避免名称后半段或第 11 个选项永久不可见。
- 续读产生新观察，要明确旧 ref 过期；动态列表的 offset 不是稳定记录身份，列表改变后重新选择范围。
- 后续需要差量时，必须带基准观察 ID；基准不匹配就返回完整局部观察。

验收必须覆盖实际送入模型的 transcript 和上下文压力，不能只检查服务端对象：长列表中间/尾项、压缩后同名前缀、超过 10 个选项、分页期间页面变化。模型必须收到目标及对应观察 ID，并能补读完整详情。

来源：[结构化投影](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/context.py)、[模型入境处理](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context.py:243)、[观察](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py)。旧探针见 [project-gap-probe-result.json](../codex-browser-use/evidence/project-gap-probe-result.json)。

## 2. 让模型识别对象，让执行器处理页面细节

**优先级 P2；部分已实现。** 当前 ref 能绑定真实节点并校验可见、disabled、遮挡及语义变化，应该保留。可吸收的是区域/行/记录/frame 范围中的语义定位与操作时重新解析。

例如“删除张三那一行”需要模型看见行与记录上下文，并把“张三所在行 → 删除按钮”表达为唯一目标。当前平铺的 role/name/ref 很难可靠区分一整页同名按钮。

建议先补附近上下文和 parent/region/row/frame 身份；统一 ref 读取与范围检查，之后再按需求开放语义定位。多匹配仍应拒绝，不能自动选择第一个或任意序号。

可保留每个观察内的短 ref。直接模仿 Codex 稳定 AX 索引没有充分依据：本次未解析其 WASM 索引算法。若后续引入长期目标句柄，也必须绑定 document/frame/control generation，与短期观察 ID 分开设计。

来源：[观察与目标](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py)；Codex [shipped-source-index.json](../codex-browser-use/evidence/shipped-source-index.json) 的选择器与输入准备范围。

## 3. 降低往返成本，同时保留失效引用保护

**优先级 P2；本轮确认的契约取舍。** 当前动作后 `observe(full=True)` 创建新观察 ID。模型一次预先生成两个 fill 调用并复用同一 ID，第一步执行后，第二步会被正确拒绝。真实服务 Python 逻辑＋mocked CDP 探针确认：一次派发，第二次 `stale_observation`。见 [interaction-probe-result.json](interaction-probe-result.json)。

这不是失效校验应被撤掉的理由。Codex 持久运行时可以在一次代码调用内串行操作并消费结果，这个减少模型往返的机制值得吸收。

最小推进方式：先保持浏览器动作串行，并让动作后返回足够的新状态。若真实任务的耗时主要在模型往返，再支持少量已授权、后续步骤无需模型重新决策的动作序列。每步更新状态、重新定位、检查所有权；遇歧义、页面变化、人工接管或未知结果，立即停下并返回已完成步骤。提交及其结果验证保持明确边界。

不要把多条带同一个旧 observation_id 的调用当作 batch 自动放行。稳定字段可轻量观察，导航、结构改变、交回控制后再进行完整观察。局部观察也必须提供下一步可操作目标，而不只返回“成功”。

来源：[动作后观察](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py)、[串行工具执行](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py)。提示已表达低成本验证，服务仍每动作 full 读取。先测真实耗时，再决定是否加入序列；无需立即引入完整 JS REPL。

## 4. 把成功标准放在业务效果上

**优先级 P2；已有收据与字段状态检查，继续关联业务目标。** 最新 fill/select/set_checked 后比较目标实际状态，返回 confirmed/not_confirmed，不回显实际值。本轮真实 Chrome 的选项拒绝、checkbox 拒收与键盘组合测试通过，但没有完整覆盖所有受控输入/格式化场景。Codex 真实遮挡实验出现过“点击返回成功、目标无变化”，也说明派发结果不能替代业务效果。

当前 check_text/wait 可做范围内文本检查，但“页面里有已保存”可能是旧提示或另一个记录的提示。建议增加目标 URL、计数、记录状态等明确条件，核对操作前后的预期变化。例如“订单 123 从待提交变为已提交”，比全文匹配成功词更可靠。即时字段比较之外，受控输入延迟格式化/拒收也需有限状态等待。

非秘密输入值可以只比较用户指定值并返回 matches，不回显网页里实际值。密码、OTP 和未授权草稿继续由用户处理。验证失败与执行失败分别记录；响应丢失后先核对页面，不重复提交。效果验证最终仍由任务目标决定，运行时只执行明确条件，不需要另造一个裁定任务成功的模型。

来源：[状态断言与收据](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py)。Codex 异常见 [codex-live-observations.json](../codex-browser-use/evidence/codex-live-observations.json)。

## 5. 优先修正真实输入与可信观察边界

**滚动已吸收并验证。** 最新项目层直接派发 CDP，使用验证后的 x/y，水平/垂直轴互斥，已替换此前 G2 的旧路径。本轮真实 Chrome 嵌套容器与横向滚动测试通过。应保留该适配，不必修改第三方依赖。

**观察隔离 P1，静态风险。** ref 表、name/visible 函数和 revision 仍存在网页 main-world 全局。页面能接触这些对象，所以不能让它们充当可信校验源。建议受控 isolated world，并在服务端绑定 document/frame/backend node。隔离 world 能保护自身 JS 状态，不能使共享 DOM 永远不变，动作前仍要校验。节点传递、同源 frame 与 marker 的全部消费者需一起迁移，不能只把 collect 换到另一个 world。本轮未做恶意网页实测，没有发现凭证泄露。

**frame P2，按需求扩展。** 当前支持同源 frame/开放 shadow；跨源 frame 要通过 CDP execution context/session 路由，并明确 frame-local/top-level 坐标。先统一目标和坐标契约，再扩展覆盖面。

来源：[目标与滚动派发](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py)、[main-world 状态及 evaluate](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py)。G2 的旧派发参数保留在原探针。

## 6. 明确接管、期限与授权的行为边界

接管已有 owner/generation/队列失效检查，不应重复建设。进一步值得吸收的是把所有权核验放在实际输入派发前，并区分已经派发的动作与仍处于预检查的动作。当前明确允许锁内 atomic action 完成；这是一项产品取舍，不能仅据缺少最后一次检查就声称严重越权。

本轮真实服务逻辑＋mocked CDP 探针在 target 与嵌套节点解析的两个 await 边界确认：接管请求先改变 owner/generation，但当前原子动作仍继续模拟 click；接管返回在动作之后。不是“接管完成后仍越权点击”。建议在实际输入处复验此前捕获的 generation；准备阶段还会滚动/聚焦，也需计入产品接管承诺。结果与独立审核见 [review.json](review.json)，可重复运行 [probe.py](probe.py)。

等待已有条件轮询；更严格的期限需要把剩余预算传到单次 CDP 调用及动作后观察，而不是只在每次调用完成后看 deadline。实际已派发的副作用未必能撤回，超时仍要保留 unknown 或已知执行状态。

两个期限探针中，请求 1ms，模拟单次 evaluate 或动作后观察耗时 80ms，总响应约 81–82ms。`timeout_ms` 是条件轮询的软期限，不能向调用者承诺总操作时长；外层 35 秒只包 `_action`，target 另有 5 秒，嵌套解析不在该 35 秒包裹内。可给解析、派发、条件等待和后观察分配明确有限预算。没有据此断言底层 CDP 完全没有超时。

授权范围应按已有 trust mode、任务目标、origin/account 和操作影响判断。最新 approval scope 已绑定目录/control generation，不随每次 revision 改变；具体参数仍影响指纹，不能据此声称所有重复提示已解决。先核验真实用户流程，再实现任务级授权范围。浏览、滚动、截图与发送、支付、发布等外部改变应有不同边界，用户授权需对应实际对象与操作。

能力输出应说明当前后端真能执行什么、当前模型是否收到图片、谁拥有控制权，以及 next action。当前 status/vision_available 已有部分基础。能力不足时走主模型驱动的现有 assistance 路径，避免新增关键词判定器或让第二模型覆盖主任务决策。

来源：[派发与接管](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py)、[工具能力与图像附件](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/browser.py)、[授权指纹](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:914)。

## 实施顺序与验收

| 阶段 | 工作 | 必要验收 |
| --- | --- | --- |
| A：守住当前修复 | 真实模型验证结构化观察/续读；观察隔离 | 关键记录进入模型上下文；压缩后详情可补读；网页同名全局不能破坏校验 |
| B：增强表达和验证 | parent/row/region 范围、安全字段/状态断言、低成本后观察 | 重复按钮定位正确记录；受控输入拒收能发现；旧成功通知不能造成错误确认 |
| C：改善执行体验 | 按需要加入受控动作序列；收紧预检查接管；分层剩余期限；任务级授权 | 序列部分成功后停在准确位置；不重复提交；尚未派发的接管动作拒绝；授权范围变化重新检查 |
| D：按真实任务扩展 | 跨源 frame/更多浏览器能力 | 两个 origin 的 frame 操作及父层遮挡/坐标验证，后端能力与工具描述一致 |

用真实主模型通过完整工具管线做以下任务验收，而不只运行演示：长列表指定记录、同名按钮、六字段表单、嵌套滚动、提交后响应丢失、操作中接管。再按需求加入跨源 frame。记录业务目标是否完成、错误成功声明、重复变更次数、拒绝/恢复原因、模型往返数、观察输出量与耗时；隐藏输入和秘密不写日志。

本轮 **5 项上下文测试、3 项真实 Chrome 测试通过**，另有 mock 边界探针。此前 18 项独立演示断言和 20 项项目测试各自保留范围，均不能当作真实自然语言任务成功率。本轮验证没有调用付费模型。建议以这些明确问题和验收条件逐项推进，不一次引入所有复杂机制。

快速跳转：[模型入境投影](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context.py:243)、[投影实现](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/context.py)、[动作执行](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py)、[观察与目标](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py)。
