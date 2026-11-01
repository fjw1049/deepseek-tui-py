**Browser harness 修复记录 · 2026-10-12**

本文件保留第一轮结果；后续输入保护和 open shadow 回放修复见 [第二轮记录](ROUND2.md)。

本轮按 [REPORT.md](REPORT.md) 的问题清单落实修复，保留开始工作前的未提交修改。原审核报告、源码散列和 probe-results.json 保留为历史基线；旧 probe.py 用于展示旧缺陷，不能替代当前回归测试。

修复重点是让模型收到可继续使用的观察，让工具、人工操作和回放遵守一致的执行契约，并准确区分操作结果与附属证据失败。没有更换浏览器依赖，也没有增加第二个评审模型。

**13 项问题的对应处理**

| 审核编号 | 当前处理 | 验证证据 |
|---|---|---|
| 1 观察被压缩破坏 | 观察只编码一次；浏览器工具结果使用 JSON 结构化投影。保留 observation_id、文档/标签/控制代次、回执和可操作 ref；缩减正文、目标、frame、options 时提供继续读取信息。人工交接恢复上下文也使用同一投影。 | 低/中/高压力、转存磁盘后的 metadata、真实 Engine 工具入上下文、大交接观察、长选项 value 完整性。128k 窗口且压力 0.6 的测试预算为 6,000 字符；其他窗口使用原有对应预算。 |
| 2 不适配控件仍被点击 | dispatch 前校验 fill/type 的编辑类型与 readonly，select 的原生控件与有效选项，set_checked 的原生 checkbox。工具、回放、内部/UI 字段操作都经过检查。 | fill Submit 与 readonly 返回 not_executed，真实按钮点击计数保持 0；焦点变化后无目标输入被拒绝。 |
| 3 回放绕过 harness | 回放通过 BrowserService.action 执行，使用新观察、控制代次、目标校验、正确 fill、状态后置条件和统一回执。候选 selector 要匹配录制的名称、tag/type/role；有目标的 press 匹配失败不会变成无目标 Enter。 | old → replacement；首候选消失后的匹配候选；错误控件与语义已变化的目标不执行；现有真实录制回放通过。 |
| 4 错误状态被报告成功 | fill/select/set_checked 在有限等待后读取目标最终状态。未达到要求返回 effect=not_confirmed，并保留 execution=executed。多行 contenteditable 按可见换行验证。 | 不存在/禁用选项拒绝；checkbox preventDefault 不声称确认；异步回滚字段报告未确认；多行编辑区正确确认。 |
| 5 长页面与断言截断 | 正文、元素、frame、select options 可继续读取，并带 scope_selector。文字断言在完整指定 scope 内判断。观察提供类型、可编辑状态、readonly、唯一 ID selector、href 与 option value，不输出输入值。 | 270 个按钮的后 20 个可读；16k 字符后的文字可读且断言成立；60 个选项可继续读取并选择末项；预算压缩不截短 option value。 |
| 6 滚动目标/轴错误 | 向已验证容器或页面中心发送 wheel；按方向独立设置 deltaX/deltaY。 | 指定容器 scrollTop 实际改变；right 的 deltaY 为 0。 |
| 7 快捷键与焦点 | 解析 Ctrl/Meta/Alt/Shift 和支持的键名，复用 CDP 输入路径。无目标 type/press 绑定观察时的焦点；指定 frame 目标按页面激活、父 frame、目标元素的顺序聚焦。 | Ctrl+A 真正选择 [0,3]；焦点改变拒绝输入；跨域/OOPIF 中首次快捷键、随后 fill 与点击通过。 |
| 8 死会话与恢复 | ensure 探测现有连接；status/view 失联后标记不可用、清观察并给出 recover 提示。agent 暴露 recover/close_session。恢复生成新的控制代次并重新打开之前的 HTTP(S) 页面，不重放历史动作；UI 恢复保持原任务暂停与协助请求。 | 关闭真实 CDP 后不会继续报告可用；恢复后已完成 click 仍只记一次；原任务与 assistance 保留，保持 user 控制。 |
| 9 删除线程泄漏 | 永久删除线程前关闭其浏览器、录制及 frame 通道，释放 run 与临时目录。保留原有证据/profile 保留策略。 | 在隔离测试线程上执行真正的 manager 删除，断言 session.close(kill=True)、run 移除、临时目录删除。 |
| 10 popup 发现滞后 | 动作前后同步标签快照，返回 tabs 与 tab_changes；tabs 读取统一更新 run.tabs。 | 真实 popup 返回两个标签及一个 opened ID，UI/service 状态一致。 |
| 11 frame 边界不明 | 返回真实 frame ID、父关系与能力说明；支持直接子 frame 的 scoped observe、CDP 输入与父页遮挡检查，包括 OOPIF 与内部 open shadow。frame 或其祖先有 CSS 变换时拒绝坐标执行；深层跨域 frame 与 closed shadow 仍有明确限制。 | 不同端口跨域与不同主机 OOPIF 的读取、首次快捷键、填充、点击、内部 open shadow 输入、父页遮挡及祖先变换拒绝；已有同源 frame/open shadow 测试保留。 |
| 12 附属失败覆盖操作 | action 与人工 input 的录制抓图/持久化错误返回 evidence_warning，保留已执行结果；回放截图、视频启动/收尾和步骤动画收尾错误单独记录，避免覆盖路径结果。 | 实际 click 只执行一次且仍返回 executed；人工文字输入只发一次；视频收尾失败仍保留回放结果并结束步骤录制。 |
| 13 审批粒度矛盾 | 导航、hover、scroll、screenshot 使用 AUTO；可能改数据的 click/fill/type/select/checked/press 继续遵守审批。审批 scope 绑定会话与控制代次，读取不使其失效。 | 策略参数化测试、observe 后 scope 不变、既有控制交接与审批回归。 |

**比较矩阵中的其他修正**

- open 仅复用完全相同的 URL 标签，避免意外重载草稿；reload 仍显式执行。不按同站点根 URL 进行宽泛复用。
- 工具结果带最近 10 项简要动作历史，不包含填写文本。
- 动作后提供最长 1.5 秒的 DOM 稳定等待；稳定窗口为 150ms。长异步任务仍通过与目标有关的 wait/验证判断，不能从 CDP dispatch 或短暂静止推断业务完成。
- screenshot 支持 full_page 与 crop，并检查页面边界和 16MP 上限。只有当前 viewport 截图绑定坐标点击；整页、裁剪与 frame 范围截图不会被误当作 viewport 坐标依据。
- UI 把状态新鲜与图像新鲜分开。busy/image=null、轮询失败时保留旧画面供查看，但禁用坐标输入；恢复新画面后再启用。
- UI /action 携带控制 generation，服务端拒绝缺失或过期代次，防止旧 HTTP 请求在交接后导航/修改页面。
- 回放验证支持 URL、文本、selector、标题、元素文本和 input value，导出统计 verify 与 check_text。没有验证规则时仍是 verification=not_checked，路径 passed 不代表业务验收。
- 生成 Skill 明确要求最新 observation_id、每轮一个状态相关动作、使用动作返回的新观察。
- 没有绑定 Workbench browser_service/runtime_thread_id 的运行入口不向模型广告 browser_use。
- 视觉辅助模型获得当前浏览器操作/目标/观察信息，排除填写文本和值；缓存包含该上下文，避免不同目标复用同一视觉描述。

**代码与回归入口**

- 综合后端回归：**235 通过，1 跳过**。跳过项为当前测试 PATH 未安装 FFmpeg 的视频编码测试。
- 前端 6 个定向测试文件：**31 通过**。
- TypeScript 全量 typecheck、浏览器相关修改及新增回归文件的定向 Ruff check、Python 编译检查、git diff --check 通过。

核心实现：[context.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/context.py)、[observation.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/observation.py)、[frames.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/frames.py)、[service.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/service.py)、[workflows.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/workflows.py)。

主要验收：[真实 Chrome 测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_browser_chromium.py)、[上下文与视觉辅助测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_browser_context.py)、[真实 Engine 入上下文测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/engine/test_browser_primary_loop.py)、[HTTP/生命周期测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/contract/test_browser.py)、[共享输入测试](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_browser_shared_input.py)、[UI 新鲜度测试](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/BrowserWorkspace.test.ts)。

综合后端回归命令（项目根目录）：

```sh
DEEPSEEK_BROWSER_E2E=1 .venv/bin/python -m pytest \
  tests/test_browser_chromium.py tests/test_browser_observation.py \
  tests/test_browser_assistance.py tests/test_browser_module.py \
  tests/test_browser_shared_input.py tests/test_browser_extensions.py \
  tests/engine/test_browser_primary_loop.py tests/contract/test_browser.py \
  tests/test_browser_context.py tests/engine/test_context_audit_fixes.py \
  tests/engine/test_context_pressure_live_signal.py tests/engine/test_per_engine_context.py \
  tests/engine/test_context_query_survival.py tests/test_registry_input_validation.py \
  tests/test_client_audit_fixes.py tests/contract/test_rewind_thread.py -q --tb=short
```

前端回归命令（packages/workbench）：

```sh
npm exec -- vitest run \
  src/renderer/src/components/BrowserWorkspace.test.ts \
  src/renderer/src/components/BrowserViewport.test.ts \
  src/renderer/src/components/BrowserSessionSettings.test.ts \
  src/renderer/src/components/BrowserAssistanceMonitor.test.ts \
  src/renderer/src/components/BrowserAssistance.test.ts \
  src/renderer/src/lib/browser-activity.test.ts
npm run typecheck
```

本轮使用临时隔离 Chrome、本地虚构页面和脚本化模型；不使用真实账号、外部网站或付费 LLM。实际模型的长任务成功率、复杂网站 hydration/service worker、完整 Electron 运行态、FFmpeg 编码及跨平台按键差异尚未验收。

能力边界：closed shadow、深层跨域/变换 frame、录制中的 framePath/shadowPath 自动回放、上传/下载管理及原生对话框没有完整实现。自动回放遇到尚未支持的框架路径会预检拒绝，避免在父页面操作相似 selector。线程隔离与可选持久化 profile 保留原设计。
