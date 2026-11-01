# 优化后的 Browser Use：复核与下一步建议

日期：2026-10-12。范围：当前工作区的浏览器服务、观察/投影、frame、回放、工具/主模型入口、协助恢复和面板。只做审核，未改业务代码；保留已有未提交修改。前次 Codex 逆向证据仅作机制参考，没有重新运行 REA。

## 结论

本轮优化已落地跨源直接子 frame、选项续读、受控输入检查、页面 quiet period、popup 发现、断线恢复、回放目标校验、截图坐标范围和人工输入代际检查。方向成立。

下一步最值得做的是：**统一可信目标绑定、明确效果确认的对象/时间/条件、为压缩后的目标提供详情补读。** 在这些基础上补记录/区域语义、未决操作记录、按需观察和有限恢复预算。功能覆盖面已明显扩大，应先把契约补齐。

现有相关检查 **142 passed、8 skipped**，另有 **3 个审核探针**确认以下边界。探针通过表示该边界成功复现，不表示安全检查通过。没有调用付费模型或外部网站，未测真实自然语言任务完成率。

## 本轮核验

| 组 | 结果 | 能证明什么 |
| --- | --- | --- |
| 上下文、观察、主模型循环、协助 | 30 passed | 真实 Python 实现与合成/模拟输入的合同；主模型测试使用模拟客户端 |
| 模块、共享输入、路由合同、扩展 | 63 passed、8 skipped | 选定模块和合同；跳过项不计通过 |
| 当前 `test_browser_chromium.py` | 32 passed | 真 Chrome、临时 profile、localhost 页面；包括跨源 frame/OOPIF、回滚、恢复、选项续读和回放 |
| BrowserWorkspace 面板 | 17 passed | Vitest 模拟环境；并非完整 Electron 应用实测 |
| 本轮新探针 | 2 个真 Chrome、1 个合成投影 | 下面三个具体边界 |

可复现脚本：[probe_test.py](probe_test.py)。当前文件摘要和测试命令见 [verification.json](verification.json)。

## F1 / P1：顶层可信 ref 映射仍可被网页改写

**真 Chrome 已复现。** observe 返回 `#expected` 的 ref `e0`。随后用网页 main-world 脚本把 `window.__deepseekObservation.refs.get('e0').element` 改成另一个同名按钮。再次按原观察 ID/ref 点击：原按钮计数为 **0**，另一个按钮为 **1**，receipt 为 executed。

只改变 Map，未改变 DOM、代际或观察 ID；现有可见、名称、disabled 和命中检查都建立在被改写后的节点上，因此仍然通过。这是目标绑定可信边界问题，不能靠再加提示词修复。证据：[main-world-ref.json](main-world-ref.json)。

源码：[观察表写入](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:134)、[目标读取](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:289)。新的 [FrameContext](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/frames.py:57) 已为显式 frame 建 isolated world，但顶层仍走普通 Runtime.evaluate，不能据子 frame 隔离声称全链路已隔离。

**建议逻辑：** 顶层与 frame 都在受控 world 收集和校验；可信端绑定 observation/document/frame/generation 与节点身份。节点转交、marker、同源 shadow/frame、parent 坐标和效果读取都要遵守同一契约。网页可改变共享 DOM，隔离后仍要在输入前校验真实节点与布局。

**验收：** 网页改写同名全局、重绑 Map、替换 marker 后，只能操作原绑定节点或明确拒绝；不能派发到另一个节点。加入正常 DOM 更新、节点重建和 frame 导航用例，防止隔离修复破坏已有能力。

## F2 / P2：quiet period 支持即时确认，不能证明异步接受

**真 Chrome 已复现。** 输入事件安排 900ms 后回滚。fill 在 **172ms** 返回 effect=confirmed，字段当时为 replacement；之后字段变回 old。证据：[delayed-rollback.json](delayed-rollback.json)。

当前 [_settle](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:1263) 等待 150ms 的 DOM/readyState quiet period；直接修改 input.value 不一定触发 MutationObserver。[状态比较](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:1081) 正确描述了那个时刻，现有提示也明确区分业务完成，因此本发现不是“工具保证永久成功却违约”。问题是 confirmed 的结构信息还不足以表达验证范围，不能把 30ms 回滚测试扩展成所有异步表单均已接受。

**建议逻辑：** receipt 补 `assertion_kind`、目标身份、`verified_at`/观察 ID，把 field_value/checked 的即时确认与目标记录保存/提交确认分开表达。任务需要保存时，主模型提供明确、有限的业务条件：指定记录的新版本/新状态、与本次操作相关的结果区域等。执行器验证该条件，主模型判断任务是否完成。

不要统一加 900ms 或无限 network-idle。动画、轮询与应用延迟都可能让这种等待既慢又不准确。quiet period 保留为取得较稳定观察的机制；最终验证由任务条件决定。

**验收：** 延迟回滚、格式化、保存失败、旧成功通知、另一记录成功、提交已完成但后观察失败。分别记录派发、即时字段状态和业务效果，未知结果不自动重放。

## F3 / P2：最小控件回退丢失具体详情补读信息

**真实投影函数＋合成输入复现。** 一个 select 的选项 value 为 7000 字符，在 BrowserAction.text 的 8000 字符上限内。6000 字符投影预算触发 [最小回退](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/context.py:94)，只留下 ref/role/name，options、total_options 和 next_option_offset 消失；整体只标 context_truncated。证据：[oversized-detail.json](oversized-detail.json)。

正常短选项分页已经实现并通过测试。该探针证明的是单个详情太大时的退化信息不足，没有证明所有选项分页均失败。

**建议逻辑：** 无论省略到什么程度，都保留 `details_truncated` 和绑定当前观察的补读引用。支持按 ref 读取完整名称、选项和所属记录。超长 option.value 可以保留在可信后端，用短 option_ref 选择，避免迫使模型把大值完整传回。不要截断 selector/URL/value 后仍让它作为可执行值使用；当前删除过长 selector/href 的做法应保留。

**验收：** 单项太大、数百选项、名称区别在后半段、选项列表在续读时改变。要么安全补读/选择，要么明确返回能力限制；不能产生不存在的续读路径或静默缺失。

## 在优化基础上，值得再加的五项逻辑

### 1. 记录语义和范围定位

当前观察仍以平铺 role/name/ref 为主。添加 parent/row/region、业务记录键和 frame 路径，使“订单 123 所在行 → 编辑按钮”有明确表达。ref 负责精确节点，记录键负责重排/重建之后重新识别。不要把 DOM 序号、坐标或分页 offset 当长期记录身份；多匹配继续拒绝。

最小实施是补附近记录文本和容器身份，再支持范围内定位；无需立即引入完整页面知识图谱。验收用虚拟列表、重复按钮、排序和分页，确认正确记录。

### 2. 少量未决外部操作记录

现有 history/unknown/no-replay 是正确基础，但最近 10 条历史或压缩后的对话不能承担全部未决操作语义。建议为可能改变外部数据的操作保留少量 unresolved 记录：任务、目标记录、动作类别、原 action_id、最后已知阶段、核对依据。解决前不因 history 截断而消失，恢复会话/上下文压缩后先核对结果。

当前动作串行，通常只需一个待核对的提交记录和有限历史；无需分布式事务框架。只记录必要身份和证据引用，不存密码、OTP 或完整输入。自建网站支持幂等键时使用网站提供的键；第三方网站不能凭工具去重缓存获得 exactly-once 保证。

验收：提交已生效但响应丢失，恢复或压缩之后仍不重复提交；明确未执行的操作才允许重试。

### 3. 局部后观察，按数据决定受控序列

目前每动作会进行 tab 读取、settle、完整 observation，再刷新 tabs。应先记录阶段耗时、模型往返和输出量。稳定字段返回局部状态与下一步可操作目标；导航、popup、结构变化和控制交回做完整观察。减少不必要的整页读取，再根据真实瓶颈决定是否增加短序列。

如果加入序列，每步更新观察/所有权，未知结果或目标变化立即停止，返回逐步收据；保留旧 ref 拒绝。不要直接批量放行同一个旧 observation_id。

### 4. 有限恢复与无进展识别

依据 typed reason、目标记录和关键页面状态识别反复失败，不把每次新 observation_id 当作进展。只重试允许恢复的读取/定位；状态改变未知时走结果核对。有限次数后由主模型重新判断当前路线及用户依赖；真正缺少用户操作才调用已有 assistance，不用 CAPTCHA/login 关键词裁定。

同时给解析、frame attach、输入、效果等待、后观察分配预算，并传递剩余时间。接管允许当前原子动作完成是现有产品选择；如要阻止仍在准备中的动作，在实际输入处检查捕获的 generation。不要在鼠标按下后简单截断鼠标抬起等事件对。

### 5. 每份证据绑定产生它的操作

图像辅助模型已加入最近操作上下文，并排除输入值，这是进步。进一步将每张图片对应到 asset_id、action_id、observation_id、document/frame、截图范围和时间。一次请求可能带旧图与新图，“最近操作”不能替代每张图的来源关系。viewport/full-page/crop 坐标契约继续保留。

前端返回可增加单调 view/frame 序号，辅助丢弃同 generation 的过时响应。这是建议，本文没有复现 UI 乱序或真实视觉判断错误。

## 建议顺序

| 顺序 | 工作 | 完成标准 |
| --- | --- | --- |
| A | F1 可信目标绑定 | 网页无法把当前 ref 指向其他节点；正常 frame/shadow 能力保留 |
| B | F2 验证范围；F3 详情补读 | 字段确认与业务接受有明确区分；所有省略可补读或明确拒绝 |
| C | 记录/区域语义；未决操作记录 | 重复按钮选对记录；响应丢失、压缩和恢复不重复变更 |
| D | 局部观察、有限恢复和预算 | 测得更少输出/往返；未派发与已派发状态准确 |
| E | 受控序列、更多 frame、下载/上传等 | 只在真实任务需要且验收覆盖时扩展 |

用同一组真实主模型任务比较优化前后：指定记录编辑、虚拟列表/分页、异步保存、popup/frame、响应丢失后恢复、操作中接管。记录完成率、错误成功声明、重复变更、定位恢复、模型轮次、观察量和阶段耗时。当前这些测试通过数不能替代自然语言任务基准。
