# Browser harness 最终审核与优化方案

核查日期：2026-10-12 至 2026-10-13。依据：用户提供的 Claude 方案、当前工作区源码、前三轮修复记录，以及本轮重新运行的本机 Chrome、接口故障注入、前端表征和定向测试。

本轮交付审核和实施方案，没有修改业务代码。第三轮清单中的 11 个源码散列与本轮开始时完全一致；Claude 最终快照中有 7 个文件后来被第三轮更新，所以涉及录制的旧失败不能直接沿用。新证据保存在 [final-review-evidence](final-review-evidence)，没有覆盖 Claude 原始实验。

## 1. 最终判断

Claude 的核心判断合理：保留主模型决策、BrowserService 执行、Workbench 展示与交接、录制与 Skill 复用的结构。当前最影响可靠性的缺口是目标身份、操作结果和跨入口约定。扩大动作数量可以后做。

前三轮已经补齐结构化模型上下文、目标输入校验、字段即时确认、直接子 frame/OOPIF、open shadow、分页、原生键鼠、代际控制、恢复清理，以及真实录制回放。它们是应该保留的基础，但现有测试通过不能证明所有动态页面都可靠，更不能代替真实模型任务完成率。

最终实施主线是：**可信目标与整体预检 → 操作结果与人工输入一致 → 录制收尾和条件验证 → 有界上下文与准确语义 → 能力、授权与基准 → 按任务扩展功能。** 每组独立验收，不同时重写执行器、模型循环和前端。

## 2. Claude 发现的当前状态

| 项目 | 本轮最终审核 | 证据和代码 |
|---|---|---|
| F1：页面可改写 ref registry | **确认仍存在，P1。** 本轮 Chrome 实验中，请求 Chosen 的原 ref，实际点击 Other。观察 ID 和控制 generation 没变。 | [本轮身份实验](final-review-evidence/identity.json)；[registry 写入](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:140)、[目标读取](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:301)。 |
| F2：虚拟列表复用相同按钮节点 | **确认仍存在，P1。** 同一个 Details 节点所属记录由 A 变 B，旧 ref 仍点击 B。只验证节点、名称和 role 不够。 | 同一身份实验；[当前校验](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:351)。 |
| F3：默认 button 类型导致 Shadow 回放失败 | **第三轮已修，不列为当前缺陷。** 保留观察、录制和回放共享规范的建议。 | [第三轮记录](ROUND3.md)、[第三轮源码与验证清单](round3-manifest.json)。 |
| F4：回放后置参数错误导致部分变更 | **确认仍存在，P1。** 第二步替换成 9000 字输入后才被拒绝，第一步 Save 已执行一次。 | [本轮回放实验](final-review-evidence/replay.json)；[不完整预检](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/workflows.py:118)、[运行时构造动作](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/workflows.py:251)。 |
| F5：动作结果在 HTTP/UI 中丢失 | **确认仍存在，P1。** 故障注入下 HTTP 409 只保留字符串，工具保留 unknown receipt；UI 动作成功后 view 失败仍返回 false。没有复现 UI 自动重试，风险是误导调用者或用户重复操作。 | [HTTP 实验](final-review-evidence/route-receipt.json)、[前端表征](final-review-evidence/ui-characterization.test.ts)；[route](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/browser_routes.py:70)、[perform](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/BrowserWorkspace.tsx:147)。 |
| F6：异步字段/标题断言只读一次 | **确认仍存在，P2。** 字段 350ms 后达到条件，初次核验约 0ms 即失败，之后再次核验通过。 | 本轮回放实验；[verify](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/workflows.py:282)。 |
| F7：结构投影超出预算 | **确认仍存在，P2。** 6000 字符预算，无 observation 输出 23991 字符；合法长 shadow scope 输出 16295 字符。属于合成输入复现，不是实测模型溢出。 | [本轮预算实验](final-review-evidence/projection.json)；[无观察分支](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/context.py:14)。 |
| F8：submit/隐藏引用名称遗漏 | **窄范围缺陷确认，P2。** 当前观察没有 Continue、Hidden referenced 名称，本轮原生 AX 对照能读到。直接补明确语义缺口；全量 AX 融合仍需要独立评估。 | 本轮身份实验的 native_ax_comparison；[name 算法](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:57)。 |
| F9：输入队列仅绑定 generation | **表征确认，P2。** 同 generation 的 disable→enable 后旧文字仍被发送；真实跨页误输入尚未复现。后端也没有 tab/document 场景校验。 | 本轮前端表征；[队列](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/BrowserViewport.tsx:18)、[服务端检查](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:522)。 |

本轮补充三项必须纳入方案的边界：

1. **录制停止失败没有进入完整性判定，P1。** 本机 Chrome 原生输入后立即停止，注入 dispose 的 Runtime exceptionDetails；finish 正常返回，manifest 为 stopped，input 事件 0 条、capture_warning 0 条，完整性 gate 接受。原因是 `_dispose` 不检查 Runtime exceptionDetails，并吞掉调用异常。这是故障注入复现，不代表普通停止仍失败。见 [实验](final-review-evidence/stop-integrity.json)、[代码](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/recording.py:223)。
2. **confirmed 缺少验证范围，P2。** 本轮填入值后 184ms 返回 confirmed，900ms 后页面回滚。工具正确反映当时字段状态；缺的是字段状态与任务业务结果的结构化区分，不应靠加长 sleep 修复。见 [实验](final-review-evidence/delayed-rollback.json)。
3. **极大单个详情没有清楚的补读契约，P2。** 7000 字符的 option.value 在动作上限内，但 6000 字符投影退化后只留 ref/role/name，丢失 options 和详情续读标识。常规选项分页已经有效，不能把本问题说成所有分页都坏。见 [实验](final-review-evidence/oversized-detail.json)、[代码](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/context.py:94)。

## 3. 对 Claude 方案的修正与收敛

- **isolated world 必须修到整个执行链。** 只把 COLLECT 搬进去不够。`__deepseekTarget`、共享 DOM marker、节点交给 Octop、效果读取和截图校验都要同步改。否则动作可能仍通过页面可修改的 marker 再定位。隔离保护注册表和 JS 状态；共享 DOM 仍会变化，输入前还要核验真实目标。
- **业务 scope 采用最小实现。** 先支持最近 row/card/dialog 的明确记录键、标签和必要上下文；不建全页知识图谱，也不对整页文本做哈希。无关时钟变化不应使所有 ref 失效。无法证明重建后的目标仍属于原记录时拒绝，不用相似度猜选。
- **统一 receipt 的含义，保留兼容。** 可以继续用现有 not_executed 等字段名，不必先改所有枚举。执行、即时效果、观察可用性、证据可用性各自表达；success 保留给旧调用者，但不能独自决定是否重试。
- **静态预检不是运行时批量授权。** 一次检查完整流程的数据合法性；每一步仍用新观察和目标身份，不能共用一个旧 ref 批量执行。
- **条件的导航语义要分开。** 目标字段条件在 document/frame 替换后应失效；预期导航的 URL 条件可以跟随同一 tab 的新文档。不能要求所有条件永远固定旧 document，也不能导航后默认继续检查另一个对象。
- **语义改进先补明确漏项。** 不急于完全换成 AX。观察、录制、回放共享名称和类型规范；原生 AX 必须能映射实际节点并遵守输入值不泄露的规则。
- **预算硬约束先实现明确退化。** 巨大 scope 无法表达时先返回有界、不可执行的解释或要求缩小范围；有真实需要后增加短 scope/option handle。避免先做一套通用分页数据库。
- **TaskGrant 属于后续产品约定。** 现有精确参数审批较频繁是事实，但不能简单删除 observation_id/ref 的哈希，也不能把同域名全部点击自动授权。先定义任务、对象、允许影响、期限和撤销，再验证授权矩阵。
- **性能结论必须来自测量。** view 持锁读取 tabs 和截图是成本来源，但尚无 p95 输入延迟基线。先测，再做缓存、合并或局部观察。
- **不承诺任意网站绝对不会变化。** 输入前检查与输入之间仍存在页面异步变化窗口。验收覆盖已定义的行为不变量；可疑变化和未知结果要诚实返回，不能把局部测试的 100% 通过扩展成所有网站的保证。

## 4. 保留的总体职责

| 模块 | 最终职责 | 集中维护的知识 |
|---|---|---|
| Engine / 主模型 | 理解任务和授权，决定下一步、验证目标、需要用户提供什么 | 任务意图、成功标准、有限恢复选择；不处理 CDP session 细节 |
| BrowserService | 唯一动作编排入口，控制所有权、代际、派发和结果 | 操作 ID、阶段、deadline、已知执行事实、未知操作 |
| observation + frames | 收集可信观察，绑定精确节点，读取局部范围，执行前验证 | 文档上下文、tab/frame 身份、scope、目标语义、布局 |
| recording + workflows + skills | 采集、脱敏、编译预检、逐步回放、业务核验和任务参考 | 同一目标描述与 scope；不绕过执行入口，不扩大授权 |
| browser_routes + Workbench | 传递同一结果，显示同一会话，人工输入和接管 | receipt、场景 token、画面顺序、输入事件对 |
| context + media | 按预算呈现有效事实，绑定图像来源和补读入口 | 截断契约、模型实际输入、图像尺寸/变换和 observation 关系 |

保留普通开发预览与 Agent 浏览器的不同用途。前者是 Electron webview，后者是 BrowserService 的独立 Chrome profile；传 URL 不传登录状态或草稿。当前 [browser 提示词](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/prompts/browser.md:15) 把开发预览和自动化标签概括为同会话，需要与真实界面及能力说明对齐。

暂时仅有一个主要自动化后端。集中必要的 Octop 私有调用并固定兼容测试即可，不建设假想的多后端框架。一份短架构决策记录固定职责、支持范围和关键不变量。

## 5. 最终实施顺序与验收

### 第 0 组：固定可比较基线

保存当前来源、复现实验、第三轮正向测试和不支持能力列表；缺陷表征转成修复回归。三项媒体失败单独处理，不挡住可独立推进的目标修复，也不忽略发布验证缺口。

- 图片 bundle 测试改用合法 ThreadRecord/关联记录和图片往返，不降低 importer 的 schema 校验。
- 配置切换测试验证值一致和深拷贝后互不影响，替换旧对象 identity 断言。
- 子代理测试遵循真实 provider 契约，仍验证限定路由、原对象隔离、owned client 关闭。

**验收：**三项失败各有契约依据及修复；相关媒体回归没有未解释失败。本轮只核实失败及来源，尚未实施这些修正。

### 第 1 组：先阻止误操作和静态错误造成的部分执行

**1A 可信目标。** 顶层与已支持 frame 使用受控执行上下文。服务端保存 observation/document/generation 与节点绑定，不从页面可替换的全局或 selector marker 获取最终可信身份。节点句柄明确释放，导航、detach、恢复清空。录制可以仍需在页面主环境拦截事件，但不能因此让执行注册表回到页面可改写状态。

**1B 记录上下文。** 目标携带少量可见业务 scope；执行前检查目标仍属于该记录。同节点 A→B、相同 Details 重复行、排序重建分别覆盖。允许无关变化；scope 不可靠时返回明确原因，要求新观察，不偷偷替换对象。

**1C 完整回放预检。** 在 owner/generation 改变、后台 task 启动和任何页面变更之前，替换全部参数并验证动作、selector 候选的类型/长度、scope、长度、URL、键、checked、expect 和 verification。预检复用 BrowserAction 约束，运行时节点身份另行绑定。纯参数预检先于 ensure；依赖浏览器才能完成的只读检查仍在接管和页面变更之前完成。编译结果仅保存在内存，不将真实输入写回步骤/Skill。第一步不能先执行，再发现第二步可提前检测的错误。

**1D 录制停止完整性。** 先修已复现的小缺口：检查 dispose/flush 的 Runtime exceptionDetails 和连接异常；关键输入提交失败标记不完整，停止仍保存已有证据，回放和 Skill 拒绝使用。完整的跨上下文 drain、导航收尾和压力验收继续在第 3 组完成。

**验收：**全局/Map/marker 重绑定零误点；A→B 拒绝；同记录时钟变化仍可操作；父页、shadow、frame/OOPIF 不退化；第 2 步非法输入、selector 类型/长度或断言结构导致第 1 步 Save 计数为 0，控制所有权也不改变；本轮 flush 故障不再被 gate 接受。

### 第 2 组：统一操作结果和人工控制场景

**2A 操作收据。** action_id 在实际派发前分配一次；预检、派发、即时验证、后观察、证据失败均沿用它。HTTP 错误、ToolResult、回放和 UI 保存同一结构。UI 保存执行事实后再刷新 view；view 失败只标画面不可读，恢复只读画面/观察。

**2B 未决操作。** 对已派发但结果 unknown 的变更，保留少量独立记录：action_id、对象/任务、最后阶段、核对依据和证据引用。现有 recover 已保留当前 run 的历史，应继续保留；独立记录解决 history 截断、回放清日志、上下文压缩和重启后不能丢失的未决状态。存储异常不能再次吞掉已有 unknown receipt。只做本地对账，不承诺第三方业务恰好提交一次。

**2C 输入场景。** generation 负责控制所有权；另用 tab/document、viewport epoch 和队列 epoch 描述实际画面。切页、导航、隐藏、失去可用性和恢复淘汰旧积压输入。前后端都校验，旧 view 响应由单调顺序拒绝。场景 token 不应每次轮询/每次普通输入都更新，否则正常输入队列会被误丢。

鼠标/按键 release 与普通输入区别处理：废弃旧文字时仍清理已按下状态；不能把旧 release 当作新页面点击，也不能留下按键卡住。保留现有中文 IME、粘贴、clipboard 成功后再 cut 的行为。接管时在尚未派发的阶段重新检查 generation，已派发的事件对安全收尾并保留事实。

**验收：**动作 executed + view 503 仍显示已派发，Save/新 tab 不增加；unknown 经 HTTP/Tool/UI 不丢；压缩/恢复后先对账；同 generation 导航后的旧文字和旧 view 被拒绝；真实 Chrome 联调验证跨页输入，IME 一次、press/release 成对。

### 第 3 组：录制完整性与有期限的验证

**3A 停止录制。** 明确 flush → 确认各上下文提交 → drain binding → 脱敏/编译/保存 → 清理的顺序。检查 Runtime exceptionDetails、连接异常和文档消失；关键 flush/drain 失败保存已有证据并标 failed，回放/Skill 拒绝。清理时的次要失败独立报告，不能把它等同于用户输入一定没采到，也不能把关键 flush 失败当普通清理忽略。

动态 frame/shadow 的发现窗口增加压力验收：刚挂载立即输入、导航时 pending 输入、frame detach、重复停止。页面派生的 synthetic click 仍不录入；input/change 目前兼容合成事件，需要用明确的受支持输入路径测试，避免把应用派生值误当成人工操作。该项是后续采集语义核验，不把所有合成输入一律过滤。

**3B 共享条件检查。** URL、局部文本、存在性、标题、字段值、checked/selected 使用同一有限等待语义，覆盖 tab/frame/shadow，传递剩余 deadline。每个 await 受剩余期限约束，不在内部步骤重新领取完整超时。条件无关的固定 200ms 步间等待不能替代检查。

**3C 验证范围。** receipt 明确这次确认的是字段值/勾选/页面条件，以及目标、观察和确认时间。业务完成由任务指定的记录结果、状态或本次操作产生的证据确认。无业务断言的回放仅表示路径执行完成；已有成功提示、另一条记录成功不算本次完成。

**验收：**普通立即停止保留末次输入；注入 flush/存储/限流错误明确失败；mask-all 原始事件、步骤、Skill 无测试私密文本；350ms 异步更新期限内通过，永不满足按期限失败；接管和目标文档变化终止旧目标检查；900ms 回滚不会被解释为业务保存成功。

### 第 4 组：有界上下文、语义与视觉证据

**4A 所有结果受预算约束。** status、无 observation、拒绝、unknown、长 scope、history 等同样预算。先保留身份、收据、简洁原因和真实补读入口，再分配正文与控件。JSON 有效和预算成立同时验证。字符限制与模型 token 计量分别报告。

**4B 省略可解释。** 大名称、选项和 scope 标明哪些详情被省略。可以补读时提供绑定当前文档/scope 的入口；无法表达时明确限制，不能虚构续读能力。ref/selector/value 不能截成另一含义。必要时用短 option/scope 引用，绑定文档与快照，旧引用拒绝。

**4C 分页变化。** 固定页面保留当前 offset；动态插入/删除时检测快照变化，明确要求重读或按稳定业务键继续。不要拼接不同观察的 refs，也不要无提示地当作同一数据集完整续读。

**4D 统一目标语义。** 共享 role/name/type/disabled/editable 规范；补 input submit 的按钮文案、隐藏 aria-labelledby 名称和 ARIA 状态。按钮文案读取与用户填写值读取分开，保持隐私约束。中文、emoji、长名称的截断与比对按一致的字符规则，防止 JS/Python 边界不同。

**4E 图像来源。** 保留当前 crop/full_page 限制；每张图绑定 asset_id、action/observation、tab/document/frame、截图范围、时间、原始尺寸和传输变换。helper facts 标明来源与不确定性。缩略图或旧画面不直接生成可执行坐标。

**验收：**6000/12000/36000 字符的所有分支不越界；CJK/emoji 有 token 计量；超大单项能补读或明确拒绝；动态分页不静默漏项；语义在真实录制回放一致；resize、crop/full_page、压缩后的坐标不能误用。

### 第 5 组：能力、授权、性能与真实模型基准

**5A 能力声明。** status/environment 明确观察、录制、回放各自的 frame 深度和 shadow 范围，说明 OOPIF、坐标变换、视频/FFmpeg、上传下载、弹窗、多标签。后端 ready 不等于所有动作可用。能力说明和主模型提示词、UI 使用同一事实；支持范围在流程开始前检查。

**5B 任务授权。** 在现有审批上增加明确的任务范围与撤销规则，分开 fresh target 验证和用户授权。允许任务内等价定位、局部读取、正常等待；新对象、资源、账号、接收方或影响扩大仍按用户约定确认。网页文本不能发放 TaskGrant，人工 takeover/stop 淘汰待执行动作。授权矩阵通过前保留当前默认审批。

**5C 测量后优化。** 分别记录输入排队、派发、效果等待、capture、observe、projection、模型耗时、payload/token。再优化 tabs 缓存、画面复用、可见性降频和局部后观察。离散 click/key、IME 和 release 不丢；顺带补 wheel page 单位按 viewport 宽高换算。没有实测前不承诺 p95 或任务成功率。

**5D 有限恢复。** 按目标记录、typed reason 和任务条件判断是否进展，不把新 observation_id 视为进展。只重试可安全恢复的读/定位；unknown 变更先核对。有限次数后由主模型调整路线或使用现有 assistance；不加另一个网页分类/规划模型。

**5E 双层基准。** localhost 确定性行为集测执行合同；隔离环境的真实模型自然语言任务集测规划和完成。覆盖同意图的页面模板、语言与动态变体，保留独立测试模板。记录完成率、误操作、错误成功声明、重复变更、协助次数、模型轮次和成本，不把两层合成模糊成功率。

**验收：**能力声明符合实际；授权不扩大；相同任务集新旧版本可比较；故障和接管不变量全部通过；性能目标由基线制定。

### 第 6 组：按真实任务需要扩展支持范围

在前五组稳定后，分别交付：上传/下载、原生弹窗、多标签回放、嵌套 frame、shadow 内 iframe owner。每项都带能力声明、派发结果和真实端到端测试；不默认所有功能同时进入一次改造。

嵌套 frame 需要完整祖先文档/loader 身份、跨 renderer 连接、坐标与遮挡链、焦点和 detach 验收；不能只删除 direct-child 限制。closed shadow 和复杂 CSS 变换继续明确受限，证明实际能力后再开放，必要时使用人工协助。

视频需要独立 FFmpeg 编码验收。它可以按能力缺失跳过，但发布说明应明确视频未验证，不能算视频功能通过。

## 6. 验证与发布完成定义

| 本轮检查 | 结果 | 含义 |
|---|---|---|
| 观察/上下文/主模型循环/协助/图片能力/录制单元检查 | 55 passed | 当前定向正向回归；不代表完整模型任务 |
| 原有前端三文件 | 26 passed | 模拟环境中的既有输入、面板、预览行为 |
| UI 缺陷表征 | 2 passed | 通过表示当前缺陷成功复现，不是修复成功 |
| 即时回滚、同名 ref 篡改、超大详情探针 | 3 passed | 通过表示边界成功复现；2 个 Chrome、1 个合成 |
| 当前本机身份/回放/停止故障实验 | 完成 | F1/F2/F4/F6/F8 与停止完整性缺口均有当前证据 |
| 媒体管线及视觉提交 | 27 passed，3 failed | 三个测试契约失败仍未修；本轮没有把失败忽略 |
| 第三轮综合后端 | 历史记录 288 passed，1 skipped | 该轮源码清单保持一致；本轮没有重新跑全组，不能把本轮数与历史数相加 |

本轮所有真实浏览器实验仅使用自建 localhost、临时 profile 和测试数据，结束后关闭会话。未调用外部模型、真实账号或生产网站；未运行完整 Electron GUI、性能基准或 FFmpeg 编码。

发布门槛：

1. 已确认的误点、重复变更、旧输入和不完整录制接受问题都有修复回归；所声明的不变量全部通过。
2. 第三轮真实父页/shadow/frame/OOPIF 录制闭环继续通过，不能用手工 StepsDocument 替代采集验收。
3. 相关后端、前端、媒体验证没有未解释失败，源码/产物来源可核对。可选能力的跳过有明确声明。
4. 同一自然语言任务集没有明显退化；业务成功、即时字段状态、派发成功与未知结果分别报告。

## 7. 官方参照与本地依据

[Playwright actionability](https://playwright.dev/docs/actionability) 提供唯一性、稳定性、可交互状态和有限等待的行为参照；[Locators](https://playwright.dev/docs/locators) 提供语义定位与范围组合参照。本项目直接使用 CDP，必须通过自己的验收实现这些保证。

执行上下文参照 [Chrome DevTools Protocol Page.createIsolatedWorld](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-createIsolatedWorld)，实现仍需核验当前 Chrome、Octop 版本和既有 frame 连接方式。

本地依据：[原始比较](REPORT.md)、[第一轮](FIXES.md)、[第二轮](ROUND2.md)、[第三轮](ROUND3.md)、[Claude 方案](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-10-12/browser-optimization/PLAN.md)、[后续审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-10-12/browser-followup/REVIEW.md)、[本轮验证清单](final-review-evidence/validation.json)。
