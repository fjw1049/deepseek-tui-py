# 当前浏览器观察与模型上下文审查（2026-10-12）

只读源码审查；未修改项目代码。证据来自当前工作树、定向 pytest、独立自建 localhost 页面。没有调用外部模型 API、登录已有账号或读取凭据。

## 已验证的实际链路

`BrowserUseTool.execute` → `BrowserService.action`（会话锁、control generation、最新 observation）→ `observe/target`（CDP DOM/JS）→ `_action`（Octop 或 FrameContext 输入）→ `receipt + fresh observation` → `ToolResult.metadata.browser`（完整结构）→ `_finish_tool_result`（spillover 后按 metadata 做结构投影）→ `Message.tool_result` → 模型请求。图片另从截图 artifact → import_image → ToolResult.images → transcript；已知文本模型通过 `prepare_media_request` 配置辅助视觉模型，只在请求中加入带来源标签的视觉观察，原始消息保持不变。

没有 CONTEXT.md / UBIQUITOUS_LANGUAGE.md / ADR 文件可供本分区使用，保留现有 domain 名称：BrowserRun、observation、receipt、control generation、frame scope。

## 已做对，不能当作缺陷重复要求

- 旧 G1 的主入口问题已经修复：engine/context.py:253–257 取 metadata.browser，而不是被 spillover 截断的文本；browser/context.py 在预算内保留 ID/ref/完整 JSON，并输出 text/element/options/frame continuation。
- 最新 observation_id + document identity + control_generation；不确定动作异常返回 execution=unknown，后续观察失败不自动重放动作；见 observation.py:263–279、service.py:825–859/1159–1165。
- 已支持 aria-labelledby、label、fieldset inherited :disabled、readonly、contenteditable 标记；本地真实探针确认前三项与 contenteditable。
- scoped direct child cross-origin/OOPIF 已支持 isolated world，不能继续把旧“跨源 iframe 完全不可读”归入当前缺陷；frames.py:48–83、observation.py:244–255。复杂变换主动拒绝而不是猜坐标。
- 原始图片内容地址、请求预算、视觉 helper 缓存只在完整成功后提交、失败不会悄悄丢图、截图输入值不复制到视觉 prompt，已有针对性测试。
- browser tool 按 runtime availability 注册、串行操作、局部重读/分页设计，比另建全功能浏览器框架更应保留。

## 必须纠正的目标身份问题

### O1 / P1 / Strong：顶层引用注册表仍是页面可改状态

当前 `observe` 的顶层 `Runtime.evaluate` 不带 contextId，COLLECT 把 refs/name/visible/revision 放在 main world 的 `window.__deepseekObservation`。`target` 又信任该对象。恶意或冲突的页面脚本可以直接把公开的 e0 对应到另一元素，满足代码自检，点击被重定向。

精确位置：observation.py:39–44/140–145/179–186/298–353；service.py:792–802/1123–1125 也依赖同一 main world target/state。FrameContext 已有 isolated world（frames.py:55–82），保护方式不一致。

真实复现：自建 localhost Chosen 与 Other 两个按钮；先 observe 得到 Chosen=e0，再在页面上下文把 refs[e0] 指到 Other 并更新 entry name/role。按原 observation_id/e0 点击，receipt execution=executed，页面实际显示 OTHER。证据 `mainworld-result.json`、可运行探针 `probe_mainworld.py`。

优化：把顶层、同源子 frame、OOPIF 的 observation/target/control readiness 收入一个有 depth 的 Observation Module，使用当前 document 的 isolated execution context 或服务端 backendNodeId 注册表。让页面数据只提供证据，不能定义 refs、验证函数或 observation identity。Seam 应集中在文档上下文和受控 CDP Adapter；不要让 service 继续用不同 JS 世界读 target。增强 locality 的收益是 mutation、导航、frame 失效的规则只在一个 Implementation 维护。

验收：页面读取不到代理 registry；尝试修改同名 window 变量不会重定向原 ref；观察文档变化、frame 导航、frame detach、上下文销毁均拒绝旧 ref；保留 shadow/same-origin/OOPIF/fill/checkbox/coordinate 测试。

### O2 / P1 / Strong：DOM node 仍在，但属于另一个业务记录

ref 的验证仅看 node 是否可见与 name/role，未绑定记录上下文；DOM revision 只对截图坐标路径检查（331–339），对 refs 路径没有检查。正常 SPA 虚拟化列表复用行/按钮节点时，“Details”按钮本身 name/role 不变，但所属记录已从 A 变成 B，旧观察仍能操作 B。

精确位置：observation.py:101–102（entry 只存 element/name/role/box），351–353（语义检查）；context.py:56–75 保留给模型的元素同样没有 row/ancestor/landmark 关系。

真实复现：自建卡片 Record A + Details；observe 后保留按钮同一 node，把父记录换为 B；旧 observation/ref click 实际记录 B。证据 `mainworld-result.json.recycled_row`。不是节点替换或恶意 registry 篡改。

优化：Observation Module 给元素保留可见语义 scope（行/卡片/对话框/区域、关联标题/标签）与目标相关 revision/fingerprint；模型看到足够的记录上下文，执行前比对同一语义记录。用可操作 scope 的 Interface 收敛策略；不要一刀切要求全局 DOM revision 完全不变，否则动画、广告、轮询页面的可用性会倒退。

验收：复用 node 的 Record A→B 返回 target_context_changed 且不点击；同一记录里的非相关计时器变化仍可操作；重复同名按钮可以通过明确 scope 定位；模型输出与 registry 使用同一 scope。

## 泛化与资源优化

### O3 / P2 / Strong：无 observation 分支与 scope 元数据未受预算约束

旧的“裁成坏 JSON / 丢当前 ref”已修，但预算函数 `project_result` 在 observation 非 dict 时直接 encode（14–16），最终只有 text 的 while shrink（112–117）。大 status/log 或合法深 shadow_path 可超过 hard limit；它们仍走 browser 特殊分支而绕过通用文本裁剪。

合成当前实现探针（不是实际 LLM 超限事故）：6000 chars budget 时，80 条 status 样例 log 输出 23991；schema 允许的 16×1000 shadow selectors 输出 16295，JSON 都有效，第二项 observation_id 保持。证据 `projection-result.json`、`probe_projection.py`。

优化：把状态、错误、观察统一纳入同一个 Projection Module 的完整预算 Implementation；保障 identity、receipt 和 continuation 可以表达后，再分配 targets/text/status/history。对于不可截短的 scope，不改字符串含义，改为受控 scope handle 或明确预算不可表示错误。保持目前 special-case browser projection；暂不引入所有工具共享的 plugin abstraction（目前只有一个 Adapter，通用 Seam 尚未成立）。

验收：所有 browser action 成功/失败/无观察分支在 6000/12000/36000 chars 预算下有明确上限；JSON 有效；不截短 ref/selector/value；保留观察元数据后可从 continuation 重新取得完整目标。增加随机化/边界 case，而不只镜像常见 payload。

### O4 / P2 / Worth exploring：手写 name/role 算法覆盖尚未到通用可访问语义

当前 role 用 explicit role 或 tag，name 以 aria-label / aria-labelledby / labels / text / alt / placeholder 组合。已经有多种实用支持，但 `<input type=submit value=Continue>` 在真实 fixture 返回 role=input、name=""，无法通过可见按钮语义识别；这不是密码输入值，应作为按钮 label 读取。引用隐藏 `<span hidden id=hidden-label>Hidden referenced</span>` 的按钮也返回空 name，因为 readText 过滤隐藏节点。相同页面的原生 CDP Accessibility.getFullAXTree 证实两个按钮分别是 role=button/name=Continue、role=button/name=Hidden referenced。角色、状态、行/列/landmark 关联缺少原生可访问树的结构。

精确位置：observation.py:25–27/57–63/93–105；Mainworld probe 的 accessible_elements/native_ax_comparison 可复核。可见 aria-labelledby、fieldset-disabled、contenteditable 已正确工作，不要为它们重复造修复。

优化：先修原生 button types 的 label/role 精确规则，再选择 CDP Accessibility 的 Adapter 或成熟标准算法作为语义 Implementation，保留 DOM locator/geometry 与 AX 语义之间的精确 node 对应关系。不要把未经业务结果核查的 AX flatten 当作“完整 DOM 替代”。和 O2 同一 Module 的 scope 设计可共享 locality。

验收：input button/submit/reset/image、隐藏 aria-labelledby、label 链、多语言 icon button、nested button text、disabled fieldset legend、contenteditable、虚拟化重复行均有明确预期；不给 password/textarea 用户内容增加暴露。

### O5 / P2 / Worth exploring：scope 分页是实时重扫，不是稳定快照；全量成本尚无测量门槛

COLLECT 虽然 limit 返回 120/250，仍遍历全部元素、文本与样式；每次 continuation 新 observation/new ref map，并从新 DOM 的整数 offset 继续。动态列表在两次页码间插入/删除可以漏项/重复；超大 DOM 的收集成本不会因输出 limit 自动降低。

精确位置：observation.py:84–90/98–99/138–150/219–225；service.py:1160 每次动作 full=True；context.py 多次 encode 同一逐渐扩大的 data。

优化：先测 observation elapsed、context projection elapsed、payload/tokens、可见目标数、分页重复率；建立 browse task budget。分页 token 绑定 document+scope+revision，变化后返回重新读取提示；优先局部 scope、必要元素/文本，再逐步扩展。只有测量证明压力后才做 incremental diff、AX revision 或更大索引缓存。

验收：分页中间插入行不会静默漏项；大/深 DOM 实验能显示 p50/p95 收集时间与可解释退化路径；目标被移出 scope 的旧 ref 必须拒绝；持续动画不会使任务不可执行。

### O6 / P2 / Worth exploring：视觉证据和 observation scope 的关联应可机器检查

当前 helper 已带 asset_id、crop、最新 browser operation，主 transcript 原始图片保留；但 prompt 没有当前 browser observation / document / viewport→wire-image 坐标映射，全部历史图可能一次分析，返回为自由文本。文本模型得到的是辅助模型观察，不一定能安全把缩放图像坐标转为 CSS viewport x/y。

精确位置：client/media.py:131–155/239–250；media.py:129（wire thumbnail）；BrowserUseTool:164–199（是否挂图）；screenshot 的 current capture 绑定见 service.py:1119–1133。

静态泛化风险，不是已复现错误点击。优化：给视觉 helper 用按当前问题选择的图像 manifest（asset_id、observation/document/frame/screenshot scope、原始/传输尺寸与 CSS viewport）；输出可核查 facts/uncertainty/区域，严格区分图像证据和用户授权。只在需要定位时给 coordinate transform；延续 DOM ref 优先。

验收：辅助视觉结果明确所属图像/观察；旧截图不能用于最新坐标；超预算去图有明确 fallback；resize/crop/full_page/2048 thumbnail 有一致坐标契约；未知能力不谎称原生看图。

## 验证结果与当前阻断

第一组命令：`.venv/bin/python -m pytest tests/test_browser_context.py tests/test_browser_observation.py tests/engine/test_browser_primary_loop.py tests/test_browser_assistance.py tests/test_image_capabilities.py -q` → 42 passed，0 skipped，0 failed。

第二组命令：`.venv/bin/python -m pytest tests/test_multimodal_pipeline.py tests/test_client_audit_fixes.py::test_vision_commits_only_successful_observations -q` → 27 passed，0 skipped，3 failed。没有外部 API/浏览器依赖，不能标为环境失败或宣称全部验证通过。

| nodeid | 当前失败 | 解释证据 | 合入前要求 |
| --- | --- | --- | --- |
| tests/test_multimodal_pipeline.py::test_conversation_bundle_restores_original_images | ThreadRecord 缺 id/created_at/updated_at/model/workspace | fixture:439–448 把裸 Message 写到 threads/record.json；data_bundle.py:554–561 当前按 ThreadRecord 校验 | 明确合法 bundle schema，迁移 fixture 或纠正 importer；实际当前 ThreadRecord + images round-trip 通过 |
| tests/test_multimodal_pipeline.py::test_switch_route_updates_new_subagent_runtime_only | `metadata.task_config is cfg` 失败 | fixture:496 要求同一对象；core.py:640 deep copy 再 647 写 metadata | 确认 snapshot isolation 是契约；改测值一致/后续修改隔离，或纠正实现；测试须通过 |
| tests/test_multimodal_pipeline.py::test_subagent_qualified_route_preserves_identity_and_closes_owned_client | SimpleNamespace 无 provider | fixture:543 使用仅 model/loop_runtime/conversation，dispatch.py:1093 现在要求 agent.provider | 用真实 SubAgent/补完整当前契约验证路由与 owned client close；若兼容旧对象仍要求支持则实现修复；测试须通过 |

这三个失败是当前验证阻断，尚未修复，不能直接推断浏览器实际操作失效。先判断实现契约与 fixture 哪方应改变，再通过验证。

真实探针命令：`PYTHONPATH=src .venv/bin/python /private/tmp/browser-optimization-20261012/observe/probe_mainworld.py`，使用 isolated profile + 临时 localhost HTTP server，finally 关闭全部会话和服务器。P1×2 与 submit 语义缺口为当前运行实证。

合成预算探针命令：`PYTHONPATH=src .venv/bin/python /private/tmp/browser-optimization-20261012/observe/probe_projection.py`，不启动浏览器、不调用模型。O3 是当前函数合同违反实证，未做实际 provider request 超限实验。

建议顺序：O1 → O2 → 修复验证阻断 → O3/O4 → 依据任务基准再投入 O5/O6；先保证目标身份与上下文可信，再追求速度和扩展框架。不要重写已经有效的 execution/effect、control generation 与分页架构。
