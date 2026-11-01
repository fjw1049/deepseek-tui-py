**Octop 浏览器操作与本项目 browser use 的对比审核 · 2026-10-11**

主要结论：你的浏览器驱动已经能工作，当前最明显的 harness 缺陷出现在「把观察交给模型」「把模型动作落实为正确操作」「让所有执行入口遵守同一契约」这三个环节。新增更多提示词或换一个驱动，都不能直接修好这些问题。

本轮只审核，未修改业务代码。新增本报告、源码清单和本地复现材料。审核基于当前工作区，包含开始审核前已经存在的未提交修改。

**审核基线与证据范围**

| 对象 | 固定基线 | 本轮用途 |
|---|---|---|
| 本项目 | HEAD `2b0644671633722e955390eb48024d66a4b75349` 加当前未提交修改 | 审核实际运行代码，而非只看提交差异 |
| TencentCloud/Octop | `0c5a46ab5f82e5ad9d1a56fa09b00e542f042fda` | 浏览器接口、会话管理、接管、录制回放、用户隔离、启动恢复 |
| TencentCloud/octop-harness | `bf9c882b7f8236c184c160f772369f770619bd01` | agent 工具包装；已下载锁定 wheel 1.0.1，核对 browser_use.py 与该快照完全相同 |
| 本项目实际驱动 | 本地安装的 `octop-browser==1.0.0`，Python 3.12.13 | 追踪调用到 CDP 的真实行为及依赖继承的缺陷 |

Octop 的固定版本 [uv.lock](https://github.com/TencentCloud/Octop/blob/0c5a46ab5f82e5ad9d1a56fa09b00e542f042fda/uv.lock) 锁定 `octop-harness==1.0.1`、`octop-browser==1.0.0`。另下载了该锁定 harness wheel，先验证 wheel SHA-256 与 lock 一致，再核对其中 `browser_use.py` 与本轮 Git 快照逐字节相同。wheel 和源码散列均写入清单。

源码证据清单记录 37 个本地范围文件、25 个上游范围文件和 16 个驱动范围文件的 SHA-256：[source-manifest.json](source-manifest.json)。这是范围清单，不代表运行了上游整个项目。

本地链路覆盖浏览器模块、工具 schema、工具注册、审批、模型工具结果入上下文、通用去重、暂停恢复、线程删除与 rewind、HTTP 接口、共享画面和输入、人工协助、录制回放、Skill 生成、证据导出及相关测试。

上游实际链路分为三层：Octop 提供用户级 profile 隔离和 Dashboard 会话管理；octop-harness 提供 `browser_use` 包装、最近动作历史、截图图片块和打开标签复用；octop-browser 提供 session、DOM/ref、CDP 输入与录制回放。单看 Octop 的 `harness.py` 无法覆盖完整 agent harness。

本项目则是：Workbench 线程 → Engine 的普通工具循环 → `BrowserUseTool` → `BrowserService` → 直接调用 `BrowserSession` → CDP。你自行增加的 `observation.py` 和动作回执承担了不少上游包装层没有的职责。

**已验证结果**

- 开启 `DEEPSEEK_BROWSER_E2E=1` 后，浏览器相关后端测试：**90 通过，1 跳过**。跳过项为 FFmpeg 视频编码测试，当前测试进程的 PATH 中没有 FFmpeg。
- 前端 6 个定向测试文件：**29 通过**。包含 viewport 输入、共享面板、协助通知和会话设置。没有据此宣称本轮完整 Electron 界面已经验收。
- 新增本地复现使用真实 Chromium、虚构页面和虚构输入，无外部网站、真实账号或付费模型调用。[probe.py](probe.py) 和 [probe-results.json](probe-results.json) 可复查。
- 没有运行上游完整服务，也没有验证真实模型在复杂网站上的任务成功率。脚本化模型测试只能证明工具循环连通，不能替代真实模型验收。

**需要优先处理的缺陷**

P1 表示会破坏观察契约、触发错误操作或造成明显错误结果；P2 表示会降低常见任务的稳定性或恢复能力。没有证据把这些问题归为 P0。

**1. P1：观察在进入模型时被通用压缩破坏——这是最直接的 harness 问题。**

`observe` 先把观察序列化到 `content`，又把同一个观察放在响应的 `observation` 中；`BrowserUseTool` 再序列化整个响应。随后 Engine 对它使用通用首尾截断，而不是保持浏览器结构的投影。

复现：包含 100 个按钮的观察产生 **69,188 字符**；在配置为 128k 上下文、压力比例 0.6 的路径中，模型只得到 **556 字符**，其中 **0 个 ref**，`observation_id` 也未完整保留。服务端仍保存着 100 个可操作元素。这意味着服务端要求模型提交有效观察 ID 和目标，但模型已经拿不到它们。

该路径不是只影响某一家模型；不同窗口有不同阈值，但浏览器结果都走相同的字符串压缩。重复 `observe` 会再次制造大结果，不能根治。

证据：[service.py:881](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:881)、[tools/browser.py:156](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/browser.py:156)、[tooling.py:465](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:465)、[context.py:243](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/context.py:243)；复现键 `context_compaction`。

建议：观察只编码一次；对模型返回受预算约束、仍然完整有效的结构，固定保留观察身份、当前标签、回执、警告和可操作目标。正文按区域缩减，并提供继续读取入口。不能仅提高通用字符上限，否则长任务仍会遇到同样的问题。

**2. P1：目标校验没有校验「这个控件能否执行这个动作」。**

`target()` 检查当前性、可见性、唯一性、disabled 和遮挡，但没有要求 `fill/type` 的目标可编辑、`select` 的目标可选择等。`fill` 随后直接点击目标，再做全选、删除、插入。

复现：对新鲜观察中的 Submit 按钮调用 `fill(text="draft")`，工具返回成功，按钮的真实点击计数变成 **1**。这里错误动作在进入文本编辑之前已经发生；事后观察和 `effect=unchecked` 无法撤销提交。

证据：[observation.py:184](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:184)、[service.py:783](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:783)；复现键 `fill_non_editable`。

建议：在 dispatch 前按动作校验原生控件类型、可编辑状态和 readonly；不适配时返回 `not_executed`。不要把「目标当前且可点击」当成「目标适合填充」。

**3. P1：录制回放绕过普通工具的填充修正，实际填入错误值。**

普通 `browser_use.fill` 已增加 CDP `commands=["selectAll"]` 的修正；回放 `_step()` 仍调用 `session.fill()`，继承驱动 1.0.0 的旧实现。

复现：已有值 `old`，回放填写 `replacement` 后得到 **`oldreplacement`**，且回放步骤返回成功；同一页面走普通 `browser_use.fill` 得到正确的 **`replacement`**。

证据：[workflows.py:123](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/workflows.py:123)、[service.py:783](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:783)；复现键 `replay_fill`。

回放还直接调用底层 session，没有复用 observation-bound 的目标校验、统一回执和操作后观察，只选第一个录制 selector candidate。若该候选过期，即便其他候选仍有效，也直接失败。

建议：先共用一个内部动作执行路径，让回放复用已经修好的操作语义与校验。候选切换必须重新证明目标正确、唯一且适合动作，不能直接照搬宽松 fallback。

**4. P1：明确状态设置缺少操作后的状态验证。**

复现 A：对 select 指定不存在的 `missing`，工具返回成功，实际 `value=""`、`selectedIndex=-1`。驱动只执行赋值并发送事件，没有验证结果或检查 JS 的异常细节。

复现 B：checkbox 的 click handler 阻止默认切换，`set_checked(checked=True)` 仍返回成功，真实状态保持 **false**。

证据：[service.py:816](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:816)、[service.py:818](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:818)、[驱动 interact.py](/Users/fjw/Desktop/deepseek-tui-py-main/.venv/lib/python3.12/site-packages/octop_browser/actions/interact.py:226)；复现键 `invalid_select`、`set_checked_postcondition`。

你的回执明确标了 `effect=unchecked`，所以不能说代码已经伪造了业务完成。但 `select/set_checked/fill` 这类有明确目标状态的原语，本身应返回「实际状态是否达到请求」，而非仅报告输入已发送。业务结果仍由主模型结合任务验证。

**其他已复现或源码明确的稳定性问题**

**5. P2：长页面既读不全，也可能把存在的文字判成不存在。**

`COLLECT` 的正文固定截到 16,000 字符，交互目标固定取前 120/250 个；`level=full` 只提高元素数量，不提高正文容量。`VISIBLE_TEXT` 同样截到 16,000，`check_text` 和文本 `wait` 用的正是这个截断结果。

复现：页面真实包含 `LATE_SENTINEL`，但它在第 16,000 字符之后，`check_text` 返回 false。270 个按钮只返回前 250 个。观察没有 offset、cursor 或按 ref 读取区域的接口；即使滚动，普通静态 DOM 的前 250 个通常仍是同一批。

`selector` 局部读取能缓解部分场景，但观察没有提供稳定 selector/id/区域层级，模型不一定能合法确定该 scope。输入值、链接 href、select 的 option value 列表也没有暴露，进一步限制精确操作与验证。

证据：[observation.py:77](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:77)、[observation.py:110](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:110)、[observation.py:132](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:132)；复现键 `text_limit`、`element_limit`。

建议：断言在完整、明确的 scope 内判断布尔结果，不必先把全文截断再判断；观察提供受限的区域读取/继续读取。普通非敏感字段可以提供经过策略约束的值验证能力；不能因此把密码等敏感输入全部放进观察。

**6. P2：滚动目标被忽略，水平滚动还混入垂直方向。**

虽然 `scroll` 会进入目标校验，但执行时只调用 `session.scroll(direction, amount)`，没有使用已经解析的目标或坐标。驱动固定向 **(400,300)** 发送 wheel。

复现：指定 `#box` 滚动，返回成功，目标 `scrollTop` 仍是 **0**；`direction="right", amount=300` 实际发送 **deltaX=300、deltaY=-300**。后者是驱动 1.0.0 的继承缺陷，前者是你的包装层丢弃了目标。

证据：[service.py:845](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:845)、[驱动 interact.py:113](/Users/fjw/Desktop/deepseek-tui-py-main/.venv/lib/python3.12/site-packages/octop_browser/actions/interact.py:113)；复现键 `targeted_scroll`、`horizontal_scroll`。

建议：向经过验证的目标所在位置发 wheel，区分页面与容器；水平操作的垂直 delta 应为 0，并观察实际滚动变化。

**7. P2：schema 承诺的键盘组合没有实现。**

schema 将 `key` 描述为 key/chord；底层 `press()` 却把整个字符串直接作为 CDP key/code，不解析 modifiers。

复现：`press("Ctrl+A")` 返回成功，长度为 3 的输入框选择范围仍是 **[3,3]**，没有全选。人工输入路径已支持 modifiers 与编辑 commands，agent 路径没有共用它。

证据：[tools/browser.py:74](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/browser.py:74)、[service.py:843](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:843)、[input.py:74](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/input.py:74)；复现键 `keyboard_chord`。

建议：实现明确的键名/组合解析和平台编辑语义，或者收紧契约，只暴露实际支持的单键。另一个边界是无目标的 `type/press` 没有绑定观察时的 focused element；焦点发生变化时，旧观察 ID 仍可能通过验证。这一焦点竞态本轮只做了源码分析，未单独复现。

**8. P2：直接调用 session 丢失了上游包装的断线恢复。**

`ensure()` 只检查 `session is None`。session 对象存在但 CDP 已断线时，不做健康检查；`state()` 仍报告 active。`status` 路径还在动作回执保护之外，驱动 `CDPSessionError` 不属于工具捕获的异常集合。

复现：关闭 CDP 连接后，工具 `status` 抛出 **CDPSessionError**；`ensure()` 返回同一个死会话；UI state 仍标 **active=true**。恢复只能依赖 UI 的 `/recover`，agent schema 没有 recover/close_session。

证据：[service.py:242](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:242)、[service.py:618](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:618)、[tools/browser.py:162](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/browser.py:162)；复现键 `dead_session`。

Octop 的 [harness.py](https://github.com/TencentCloud/Octop/blob/0c5a46ab5f82e5ad9d1a56fa09b00e542f042fda/src/octop/api/routers/browser/harness.py#L42) 有缓存会话健康检查与剔除；驱动 `browser_tool()` 也有重建和重试，但本项目直接调用 session，因此没有走到这层。

建议：恢复会话/重新观察与重发操作应分开。可以自动恢复明确的只读观察；已发出的 submit/click outcome unknown 时，先查结果，不能自动重发。上游重连后直接重试原动作的策略也不能整体照搬。

**9. P2：删除线程没有关闭该线程的浏览器，存在资源泄漏。**

线程删除淘汰 Engine 并删除线程树；Engine shutdown 没有关闭浏览器，BrowserService 只在 manager 整体 close 或显式 UI stop 时关闭 session。`runs` 最多 8 个，没有自动淘汰。

因此删除一个已经开浏览器的线程，浏览器 run 仍可能留在字典及进程中；线程已不存在后，正常浏览器路由又先拒绝该 thread ID，用户难以再关闭它。累计后会影响新的会话创建。

证据：[manager.py:2537](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:2537)、[manager.py:3007](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/threads/manager.py:3007)、[service.py:244](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:244)。这是源码链路确认，未对用户的真实线程执行删除。

建议：在线程永久删除流程中关闭对应浏览器及录制任务；证据/profile 的删除规则另按产品保留策略处理。正常任务结束可以保留结果页面，不应等同于永久删除线程。

**10. P2：popup 需要额外发现，模型收到的动作后观察仍是旧标签。**

复现：点击打开 popup 的按钮，操作返回的观察仍是原标签，不包含 tabs；再显式调用 `tabs` 才发现两个页面。即使这个 `tabs` 调用成功，`state().tabs` 仍为 **0**，因为 agent 的 tabs 路径只更新响应，没有更新 run.tabs；UI `/view` 才更新它。

这不是「完全没有多标签支持」，而是缺少动作与标签变化的关联。OAuth、支付、新窗口搜索容易让模型继续在原页上判断无进展。

证据：[service.py:721](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:721)、[service.py:956](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:956)、[service.py:408](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:408)；复现键 `popup_discovery`。

建议：动作回执提供新建/关闭/变化标签的结果，统一更新 run.tabs；自动切换必须有确定的动作关联，不能任意抢占现有标签。

**11. P2：可观察页面的边界较窄，需要明确能力和恢复路径。**

当前 JS 观察支持主文档、open shadow root、同源 iframe；跨域 iframe 只返回 `Unreadable frame`，没有 frame ID/路径或切换读取入口。复现确认跨域 iframe 的正文不可读。closed shadow root 同样不在 JS 遍历能力内。

上游 DOM builder 有结构化 selectorCandidates、framePath/shadowPath，但它们是元信息，不能据此断言上游已经完整支持所有跨域 OOPIF 或 closed shadow 操作。

证据：[observation.py:94](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py:94)、[驱动 builder.py:230](/Users/fjw/Desktop/deepseek-tui-py-main/.venv/lib/python3.12/site-packages/octop_browser/dom/builder.py:230)；复现键 `cross_origin_frame`。

建议：先增加明确的页面/框架身份和能力提示；需要操作这些控件时，再接入 frame-aware 的 CDP 读取与执行。没有视觉输入的纯文本模型无法仅靠保存截图处理该缺口。

**12. P2：附属录制失败仍可能覆盖已经成功的动作。**

你已经保护了操作后 observe 失败和图片附加失败。但录制中的 `_capture()` 失败没有同等隔离。

复现：按钮实际点击 **1 次**后，故意让步骤录制抓图失败；返回 **success=false、execution=unknown**，已知点击执行成功的信息被丢失。模型仍被提示先观察，因此比盲目重试安全，但回执精度和录制故障的可诊断性不足。

证据：[service.py:914](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:914)、[service.py:680](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:680)；复现键 `recording_failure_after_click`。

建议：dispatch 结果、观察结果、录制/持久化结果分别记录。已确定完成的动作不能被辅助证据失败改成 outcome unknown。

**13. P2：普通动作的审批粒度与提示词不一致。**

`open/click/hover/scroll/screenshot` 等一律 REQUIRED，只有少数只读/协助动作 AUTO；`on-request/suggest/untrusted` 都会进入审批。AUTO/YOLO 路径不受这一问题影响。

审批指纹还包含 `run.revision`，而 `_action()` 的 observe 等读取也会递增 revision，因此一次观察就使之前的指纹失效。提示词同时说普通导航无需确认、不要冗余确认。结果是不同层的规则相互矛盾。

证据：[tools/browser.py:89](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/tools/browser.py:89)、[service.py:707](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py:707)、[tooling.py:914](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/engine/orchestrator/tooling.py:914)。本轮调用审批策略函数确认了这些分支。

建议：明确任务授权范围、控制权代次和真正需要确认的动作影响；只读状态刷新不应被当作授权边界变化。点击可能提交数据，不能粗暴把所有 click 改成 AUTO。

**需要区分的设计差异与进一步风险**

| 环节 | 上游源码/驱动能力 | 本项目现状 | 判断 |
|---|---|---|---|
| 登录与隔离 | Octop middleware 强制 `user-<id>`，用户多会话共用 profile | 每个 thread 独立 profile，默认临时，可选持久化 | 更强线程隔离是设计选择；跨任务重复登录是该选择的代价，不是遗漏的单行 bug |
| 状态读取 | 上游 DOM 提供 minimal/interactive/full/structured | interactive/full，但文字长度相同，每次动作后 full | 需要按任务分配观察预算；现状与提示词「稳定填表不必每字段 full」冲突 |
| 新鲜目标 | 上游 RefCache，跨文档导航失效 | observation ID、document ID、generation、名字/role、遮挡检查 | 本项目明显更严格，应该保留 |
| 动作批次 | 上游 ref 可跨多个操作使用，但存在 stale 风险 | 每次动作后新观察，旧 observation ID 拒绝 | 复现同一观察下两个点击，第二个 stale；安全行为正确，但应明确一次状态相关动作一轮，否则浪费批次 |
| 打开网站 | harness 包装尝试复用匹配 URL/站点标签 | open 总导航，new_tab force_new；UI 的 preview 有部分复用 | 模型重试可能重载草稿或复制标签；不能盲目使用上游「同站根 URL 即匹配」的宽松规则 |
| 最近操作历史 | 每次工具结果带最近 20 个动作 | run.log 存在 UI/磁盘，agent 返回通常不含历史 | 长任务压缩后模型更难识别重复操作；通用参数去重仍存在，但新 observation_id 会改变参数指纹 |
| 等待与导航 | 驱动 navigate 等 load 最多 5 秒；back/forward/reload 立即返回 | 条件 wait 改进，但动作后立即观察，没有统一 settle 策略 | 不应将 load/CDP 成功当成 SPA 已稳定；本轮未验证复杂 hydration、service worker、慢导航竞态 |
| 焦点与输入 | session.type/press 对当前焦点发送输入 | 无目标 type/press 只校验文档与观察 ID | 需要焦点身份；DOM 版本/文档相同不代表焦点相同 |
| 图像 | 驱动有 viewport/full-page/crop；harness 返回图片块 | viewport JPEG、能力检测、视觉辅助及附加失败保护 | 图像链路已有实现；full-page/crop 是缺口。辅助模型看到用户任务概要，未必获得当前操作目标，复杂视觉定位需另验 |
| 用户输入 | Octop stream 转发输入；控制 owner 在已读代码中主要为提示 | 本项目 owner/generation/lock/pause 均有强制执行 | 本项目接管做得更完整，无需退回简单 owner 标记 |
| UI 新鲜度 | 上游通过 WS 状态/截图循环 | HTTP `/view` 轮询，busy 时可能 image=null；UI 仍 setFresh(true)，失败也不清 fresh | 可能继续对旧截图输入；本轮仅源码发现，需补 busy/null/error UI 测试。generation 只能防控制权变化，不能证明图像新鲜 |
| UI 动作代次 | 本项目 `/input` 明确 generation | `/action` 的 BrowserAction 无 generation，人工路径可不带 observation ID | 已到服务器的排队动作有代次保护；延迟到达的旧 HTTP 导航在多次交接后是否执行，仍需边界测试 |
| 回放验证 | 驱动支持 URL、text、selector、title、element text、input value 等规则 | 预检只接受 url_contains，完成所有步骤后 demo_status=passed | 文本/input 规则缺口明确；passed 表示回放路径通过，不能代表业务验收。导出 not_checked 已正确区分部分情况 |
| Skill 执行 | 上游录制可生成 Skill 草稿 | 预览 digest、同名不覆盖、自包含录制数据 | 已有实用保护；生成文字没有明确要求每次交互带 observation_id，依赖全局工具描述，宜同步契约 |
| 上传/下载/弹窗 | 已读基础 toolkit 并未提供完整文件与原生对话框任务链 | tool schema 同样未暴露 | 属于能力缺口，不能归因于你漏抄某个 Octop harness 函数；本项目提示词已有声明 |
| 任务恢复 | 上游健康检查；驱动有断线重建 | 磁盘日志保留，live refs 不跨进程保留 | 重启后重新观察是正确的；记录 uncertain 动作与验证进度比恢复旧 ref 更重要 |
| 其他运行入口 | 上游按 Octop user 绑定工具 | 浏览器服务 metadata 由 Workbench ThreadManager 注入 | 当前 CLI/TUI 的工具可能仍被注册但执行报「requires Workbench runtime thread」；不能假定所有子任务/入口都已有浏览器上下文 |

上游对应证据：[BrowserProfileMiddleware](https://github.com/TencentCloud/Octop/blob/0c5a46ab5f82e5ad9d1a56fa09b00e542f042fda/src/octop/infra/agents/middleware/browser_profile.py)、[agent browser_use 包装](https://github.com/TencentCloud/octop-harness/blob/bf9c882b7f8236c184c160f772369f770619bd01/src/octop_harness/builtin/tools/browser_use.py)、[Dashboard stream](https://github.com/TencentCloud/Octop/blob/0c5a46ab5f82e5ad9d1a56fa09b00e542f042fda/src/octop/api/routers/browser/stream.py)、[录制回放 API](https://github.com/TencentCloud/Octop/blob/0c5a46ab5f82e5ad9d1a56fa09b00e542f042fda/src/octop/api/routers/browser/record_replay.py)。

还有两个上游自身的限制，不能把「跟上游相同」当作验收标准：驱动 `browser_tool()` 断线后会重试原动作，可能重发已经生效的外部提交；已读 harness 包装参数没有 `key/value/timeout_ms/url_contains`，而底层部分动作需要这些参数。上游动作历史也只记 action/success，没有证明业务效果。

**已经做对、应当保留的部分**

- 线程内工具与人工画面使用同一受控 session，隔离 profile 与本地 CDP 端口；状态查询不会为了观察而偷偷启动浏览器。
- 新观察替换旧观察；文档身份、控制代次、唯一/可见/遮挡检查都参与目标解析。同源 frame 与 open shadow target 已有真实测试。
- 动作串行，交接等待当前原子动作；暂停代次阻止旧模型回答/后续工具批次继续执行。人工返回后重新读取页面并恢复原任务，而不是启动不相关的新任务。
- 协助使用结构化请求、暂停和通知，不只靠模型说一句「请登录」。通知监控位于浏览器可见性之外，收起侧栏仍能通知。
- outcome unknown、操作后观察失败与图片附加失败已有部分明确处理；提示词也要求先检查结果再重试提交。
- 输入值不进动作日志，录制 mask-all，接管前结束 agent 录制；导出无断言时标 not_checked。截图、URL、picker HTML 仍可能含页面数据，因此这些保护不是全链路脱敏的证明。
- rewind 会清 observation 与 assistance；进程重启不会复用失效的 live ref。

**建议修复顺序与可执行验收标准**

| 顺序 | 工作 | 验收标准 |
|---|---|---|
| 1 | 浏览器结果的结构化入上下文，去掉重复编码 | 同一 100 控件页面经过真实 Engine result 投影，在低/中/高压力下仍有有效 observation_id 与可操作目标；正文不足可继续读 |
| 2 | 动作类型校验与明确状态后置条件 | fill 按钮/readonly 被拒绝且没有 click；无效选项失败；checkbox 被阻止切换时不声称达到目标状态 |
| 3 | 回放共用动作执行契约 | `old → replacement` 在普通工具与回放均正确；两条路径都覆盖唯一性、遮挡、过期目标和回执 |
| 4 | 滚动、键盘、长页面读取与断言 | 指定容器实际滚动；right 无垂直 delta；Ctrl/Meta 组合符合契约；16k 之后的目标可以读取和验证 |
| 5 | 恢复、popup、线程删除与附属失败 | 死 session 不再报告 healthy；只读恢复可重试、未知提交不重发；popup 与动作关联；删除线程清 run；抓图失败保留已完成动作 |
| 6 | 长任务与真实模型验收 | 使用获授权的真实模型跑多步 SPA、popup、人工接管、上下文压力与未知提交场景，记录任务完成率、误操作、重复提交、模型 token 与耗时 |

这里不需要先增加第二个评审模型。首先把主模型所依赖的观察、动作和证据契约修好，再评估更复杂的规划/评估机制。回执可以强制区分「没有执行」「已执行」「结果未知」，并验证操作原语的确定状态；业务任务完成仍需要与用户目标相关的证据。

**复查命令与本轮边界**

在项目根目录执行：

```sh
PYTHONPATH=src .venv/bin/python docs/audits/2026-10-11/octop-browser-comparison/probe.py

DEEPSEEK_BROWSER_E2E=1 .venv/bin/python -m pytest \
  tests/test_browser_chromium.py tests/test_browser_observation.py \
  tests/test_browser_assistance.py tests/test_browser_module.py \
  tests/test_browser_shared_input.py tests/test_browser_extensions.py \
  tests/engine/test_browser_primary_loop.py tests/contract/test_browser.py -q
```

复现脚本会覆盖同目录的 probe-results.json。它刻意展示当前缺陷，不是修复后的回归测试集；修复时应把每项已确认问题转成对应的失败→通过测试。

本轮未实测真实网站账号、CAPTCHA、人机检测、完整 Electron 新鲜画面竞态、真实模型长任务、FFmpeg 编码、所有平台按键差异、跨进程浏览器恢复，以及完整上游服务。报告对这些分别标出源码判断或待验收，没有将测试通过扩大为「所有 browser use 场景已经可靠」。
