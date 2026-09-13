# Workbench 提示、告警、报错与交互审核

> 本报告保留修改前的审核结论；本轮优化已落地，最新结果见 [修复落实记录](./FIXES.md)。

审核日期：2026-09-13。基线：当前工作区，HEAD `d534f227`；开始审核时工作区干净。

## 结论

**当前实现有分层的雏形，但还不能认为合理、可靠。首要问题是失败时的界面和状态不可信，而不只是文案或配色不统一。**

本次整理出 **12 项具体问题：3 项 P1、9 项 P2**，另有一组体验规范建议。P1 指页面崩溃或未保存内容丢失风险；P2 指误操作、恢复受阻、误报成功、异常信息缺失等。建议先修 P1 与审批恢复、导入取消语义，再统一提示样式。

审核通过全目录检索建立了 **82 个源文件、699 个匹配行**的入口索引，并追踪关键组件、store、IPC、HTTP/SSE 与对应后端接口。索引也包含静默 catch 和状态定义，不是 699 条告警，更不是 699 个问题。

这是源码审核及定向组件/store 验证；没有连接真实第三方服务发送消息，没有执行真实清库、导入、覆盖文件，也没有完成 Electron 真机逐屏验收。不能据此声称所有可见文案和布局都已逐项实测。

## 范围与现状

| 范围 | 现有反馈入口 | 判断 |
| --- | --- | --- |
| 启动、连接、认证 | ConnectionStatusBar、全局 error 横幅、RuntimeDiagnosticsDialog、首次配置弹窗 | 有重试和诊断入口，但提示归属与清除规则不够准确 |
| 会话、模型、SSE、工具执行 | chat-store.error、system 消息、工具卡、输入框 Notice | 错误严重程度在链路中丢失，普通状态与真正失败混用 |
| 审批、提权、用户问题 | 输入框上方待办卡、工具 gate、历史记录 | 普通审批有防重入；失败后恢复存在确定缺口 |
| 回退、发布冲突、Git | 发布冲突条、回退确认、分支提示、提交局部错误 | 冲突处理已有较完整的确认和恢复模型，可以作为参考 |
| 设置、供应商、用量 | 自动保存状态、字段校验、面板错误 | 保存失败退出路径不可靠，错误原因藏在 title 中 |
| 数据管理 | 页面 Notice、原生 confirm、运行状态 | 导入取消语义错误；破坏性操作依赖多次通用确认 |
| 编辑器、文件树、预览 | tab.error、局部错误、保存闪现、ConfirmDialog | 存在错误的已保存状态、异常漏提示及危险默认焦点 |
| 插件、技能、MCP | NoticeView、导入安装弹窗、运行状态 | 批量部分失败没有完整结果；落盘与运行时生效反馈不够分明 |
| 飞书、邮件、企业微信 | 本地 notice、保存/测试状态、二维码阶段 | 三处错误响应解析与后端格式不匹配 |
| 自动化、渠道、看板 | 页面提示条、运行详情、短时状态提示 | 自动化运行列表部分失败被隐藏，可能误报刷新成功 |
| 终端、内置浏览器、复制、附件 | 创建错误、退出状态、浏览器失败、截图/复制短提示 | 多套局部反馈机制，时长与语义不一致；未做真实设备验证 |
| 系统通知与启动失败 | Electron Notification、showErrorBox | 有通知开关；点击完成通知只唤起窗口，没有定位对应任务 |

## 具体问题

### F01 · P1 · 渠道测试失败时，错误提示本身会触发 React 渲染崩溃

**证据：组件复现 + 前后端调用链核对。**

后端 `api_error` 返回 `{"detail": {"message": "...", "error": "..."}}`。飞书、邮件、企业微信页面却把 `detail` 断言成字符串，直接赋给 `notice.message` 并渲染。类型断言没有运行时转换作用。发送失败或配置缺失时，React 会报 “Objects are not valid as a React child”。当前 renderer 检索未找到 ErrorBoundary，因此可能导致整个前端视图被卸载。

位置：[FeishuChannelSetup.tsx:89](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:89)、[EmailChannelSetup.tsx:168](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:168)、[WecomChannelSetup.tsx:99](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:99)；后端 [routes.py:25](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/routes.py:25)、[routes.py:387](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/server/routes.py:387)。IPC 返回原始响应体，未替这些页面规范化错误。

**建议：**共用错误解码器，支持 detail 对象/字符串/数组、顶层 message/error 和非 JSON；UI 最终只接收字符串。错误边界用于兜底，不能替代修复解析。

**验收：**分别注入三渠道 400/502、422 校验错误、非 JSON 错误页，页面保持可操作，测试按钮恢复，展示可读原因。

### F02 · P1 · 保存期间继续编辑，会把未写入磁盘的内容标记为已保存

**证据：store 复现。**

`saveTab` 发送的是保存开始时的 `tab.content`，收到成功后却把当前 `entry.content` 写入 `savedContent`。若保存期间继续输入，磁盘还是旧快照，界面已经清除未保存标记并显示保存成功；随后关闭标签不会触发未保存保护。

位置：[workspace-editor-store.ts:429](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:429)，尤其 [workspace-editor-store.ts:457](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:457)。

**建议：**保存完成时以实际提交的内容快照更新 savedContent，并处理重叠保存的版本顺序；新输入仍应保持 dirty。

**验收：**延迟保存 A，在返回前输入 B；返回后磁盘=A、编辑器=B、dirty=true，关闭时仍提醒。

### F03 · P1 · 设置保存失败后，返回操作仍离开页面，未保存配置丢失

**证据：明确控制流，未执行真实设置写入。**

`persistSettings` 捕获错误后只设置局部 error，不返回失败结果；`goBack` 等待它结束后仍无条件切换到 chat。端口校验不通过时 `flushPendingSave` 也直接返回，随后仍退出。用户看不到可靠的“未保存”阻断，重新进入时会读到旧设置。

位置：[SettingsView.tsx:417](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:417)、[SettingsView.tsx:467](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:467)、[SettingsView.tsx:488](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:488)。保存失败原因只放在状态标签的 title：[SettingsView.tsx:610](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:610)。

**建议：**保存返回成功/失败结果；失败时保留草稿，展示原因和“重试保存 / 放弃修改并返回”；校验失败同样明确处理。

**验收：**mock setSettings 拒绝或输入非法端口，点击返回不应静默丢弃草稿；用户明确放弃后才离开。

### F04 · P2 · 编辑器保存请求抛异常时，页面没有对应失败提示

**证据：store 复现。**

保存只处理 `result.ok === false`，不捕获 Promise rejection。上层 `runSaveWithFeedback` 同样没有 catch；Ctrl/Cmd+S 以 void 调用时，错误只会成为未处理拒绝，tab.error 仍为空。缺少 bridge 的分支也只是返回 false。

位置：[workspace-editor-store.ts:437](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:437)、[WorkspaceEditorPanel.tsx:651](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:651)。

**建议：**在保存操作边界统一处理异常，保留 dirty 状态，显示带文件名的失败原因与重试。

**验收：**模拟 IPC 断开/写入拒绝，不能显示已保存，错误应出现在文件对应区域，键盘重试可用。

### F05 · P2 · 数据导入的“取消”实际会执行合并导入

**证据：明确控制流与中文文案。**

选择文件后，`window.confirm(...) ? 'replace' : 'merge'` 把取消解释为另一种写入操作。虽然正文解释“取消=合并”，但取消/关闭/Escape 的常见退出意图在这里无法表达。

位置：[DataSettingsPanel.tsx:387](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:387)；文案 `settings:dataImportModeConfirm`。

**建议：**显式提供“合并导入 / 替换现有对话 / 取消”三个动作；替换前展示影响范围。取消不得发送导入请求。

**验收：**取消、关闭弹窗、Escape 均产生零次 import 请求；两种导入方式有独立按钮与准确结果反馈。

### F06 · P2 · 审批/问题提交失败后，后端仍待处理，前端却无法恢复入口

**证据：控制流 + 两项合并函数复现。**

提交网络失败会把 block.status 改成 error，输入框只保留 pending 卡片，因此待办入口消失。轮询 pending 时，合并函数按所有已有请求 ID 去重，连 error 状态也跳过；后端再次报告同一个 pending 请求也不能修复 UI。问题卡只显示失败结果，普通审批在时间线直接返回 null，无法原地重试。

位置：[chat-store.ts:3395](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3395)、[chat-store.ts:3569](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3569)、[FloatingComposer.tsx:419](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:419)、[chat-store-runtime-helpers.ts:42](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-runtime-helpers.ts:42)、[chat-store-runtime-helpers.ts:89](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-runtime-helpers.ts:89)、[UserInputBubble.tsx:388](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:388)。

**建议：**区分提交失败与业务终态；超时先向服务端核实是否已接受，仍 pending 才恢复按钮。保留问题答案草稿；不要直接无条件重发可能已成功的决策。

**验收：**提交发生瞬断，后端仍 pending；轮询后原卡恢复可操作且答案不丢失。后端已完成时不得重复提交。

### F07 · P2 · 提权和演进确认缺少一致的防重复提交保护

**证据：组件和 store 控制流。**

普通审批已有 `approvalSubmitInFlight`。但 resolveElevation/resolveEvolution 在 await 前没有写入进行中状态或请求锁，卡片按钮也没有提交中禁用。快速双击或连续点允许/拒绝会发送多个甚至相反决策。这里确认的是前端会重复请求，未假定后端一定重复执行操作。

位置：[chat-store.ts:3413](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3413)、[chat-store.ts:3452](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3452)、[ElevationBubble.tsx:26](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:26)、[EvolutionBubble.tsx:63](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:63)。

**建议：**按决策 ID 加同步防重入与统一 submitting 状态，状态结束后再允许下一步。

**验收：**延迟响应后快速连点，只产生一次请求；各确认入口均反映同一进行中状态。

### F08 · P2 · 自动化运行记录获取失败，仍可能提示“列表已刷新”

**证据：明确控制流。**

`fetchAllRuns` 对每个任务的请求失败直接忽略，最后不论成功比例都能设置 success notice。全部失败表现为空列表，部分失败表现为不完整列表，用户无法知道数据缺失。

位置：[AutomationCenter.tsx:242](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:242)，特别是 262 与 271 行。

**建议：**统计成功/失败数量，保留旧数据或显示部分结果标识；全部失败展示错误和重试，不显示正常空状态。

**验收：**0/3、1/3、3/3 成功分别表现为加载失败、部分完成、完整成功；错误任务可重试。

### F09 · P2 · MCP 批量导入把写入失败当作跳过，部分成功即关闭弹窗

**证据：明确控制流。**

重复项与 onSubmit 异常都计入 skipped；只要 added>0 就关闭弹窗，不提供完整汇总。失败原因丢失，用户难以知道哪几个连接器尚未导入。

位置：[ImportMcpJsonDialog.tsx:60](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:60)。

**建议：**分别记录新增、已存在、失败；有失败则显示条目和原因，允许只重试失败项。运行时重载另行显示结果，避免落盘成功被理解为立即可用。

**验收：**导入包含一个成功、一个重复、一个失败的配置，明确显示 1/1/1，失败项可重试。

### F10 · P2 · 全局错误被无关成功清除，也缺少就地恢复动作

**证据：store 与渲染规则。**

同一个 `error: string|null` 承载连接、文件、置顶、回退、权限等不同来源。`probeRuntime` 成功无条件清空 error，即使是后台探测；置顶成功等操作也会清空。这些成功不代表之前的问题已解决。在线时横幅没有重试、关闭等按钮；切换到非 chat 路由后又没有同一展示出口。

位置：[chat-store-types.ts:102](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-types.ts:102)、[chat-store.ts:1652](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1652)、[chat-store.ts:3117](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3117)、[Workbench.tsx:1544](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:1544)。

**建议：**给消息最少增加 code、scope、关联任务/文件和恢复动作；只由同一操作成功清除对应错误。连接状态独立维护，业务错误放回发生处。

**验收：**文件打开失败后后台连接探测成功，文件错误仍保留；重试打开成功只清理此项。任务切换不串入其他任务的迟到错误。

### F11 · P2 · 回合失败被降级成普通系统小字，结束通知无法区分失败

**证据：SSE → store → UI 调用链。**

`turn.completed` 带有 turn.error 时，先通过 onSystemStatus 写入普通 system block，随后仍调用 onTurnComplete。store 清空全局 error 并触发统一完成通知，system block 则以 12px text-ds-faint 显示。失败内容虽未完全丢失，但不易与一般状态提示区分，缺少对应的恢复动作。

位置：[deepseek-runtime.ts:1944](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:1944)、[chat-store.ts:1404](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1404)、[MessageTimeline.tsx:2315](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2315)。

**建议：**传递终态 success/failed/cancelled 与错误信息；失败作为回合内持久错误显示，提供适当的重试/检查配置入口，通知区分失败与正常结束。

**验收：**注入带 error 的 turn.completed，界面明确显示本轮失败，历史仍能定位，系统通知不使用无差别完成文案。

### F12 · P2 · 丢弃编辑确认默认聚焦执行按钮，键盘保护不足

**证据：弹窗及调用者代码。**

ConfirmDialog 打开即聚焦确认按钮，非按钮目标的 Enter 也触发 onConfirm；未实现焦点圈定/返回。关闭 dirty tab 实际丢弃编辑，却没有设置 destructive，按钮文案仍为通用“确定”。确认是否误触的实际频率需真机验证，但危险默认焦点和焦点逃逸路径明确存在。

位置：[ConfirmDialog.tsx:31](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ConfirmDialog.tsx:31)、[WorkspaceEditorPanel.tsx:1086](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:1086)。

**建议：**危险操作默认聚焦取消；使用“放弃修改并关闭”等动作文案，最好提供保存并关闭；实现焦点圈定、关闭后焦点恢复，补充 aria-describedby。

**验收：**打开弹窗后直接 Enter 不应丢弃内容；Tab 不进入背景编辑区；Escape 安全退出并恢复焦点。

## 建议统一的提示规则

不需要先搭建庞大的通知中心。先建立一份共享消息类型、一套错误解码器、少量展示组件和明确生命周期即可。

| 类型 | 合适的展示位置 | 生命周期 | 用户动作 |
| --- | --- | --- | --- |
| 普通说明 | 对应控件附近，必要时 tooltip | 条件存在时展示 | 通常无需操作 |
| 输入校验 | 对应字段下方，关联 aria-describedby | 修正后消失 | 聚焦问题字段 |
| 正在执行/自动恢复 | 当前操作或连接状态区，role=status | 根据真实状态结束 | 慢操作按能力提供取消 |
| 可忽略成功 | 原操作附近短提示 | 可短时消失，时长统一 | 通常无需操作 |
| 可恢复操作失败 | 原操作附近持久错误，必要时 role=alert | 同一操作恢复成功或用户关闭 | 重试/修改配置/查看详情 |
| 全局阻断 | 固定全局状态条 | 根因解决后结束 | 连接、诊断、设置 |
| 必须决策 | 明确影响范围的卡片或对话框 | 后端决策状态确认后结束 | 具名确认/取消，防重复提交 |
| 运行结果/部分失败 | 任务历史或批量结果区 | 持久可查 | 重试失败项/复制详情 |

需要统一的具体细节：

- **严重程度：**ComposerNoticeToast 把 error 渲染为琥珀色，市场 NoticeView 用红色；模型回合失败又是灰字。建议状态、警告、失败分型，颜色以外还用图标与明确文案。
- **显示时长：**市场错误固定 5 秒、成功/信息 2 秒；自动化统一 10 秒；数据操作提示持久；截图等另有时长。阻断性错误不应仅因计时器结束而消失，短提示不承担唯一恢复入口。
- **文案结构：**“发生了什么 + 影响了什么 + 下一步怎么做”。例如“保存失败，修改仍保留在编辑器中。重试保存”。技术错误、路径、错误码放到可复制详情，不直接把 JSON/IPC 错误作为标题。
- **国际化：**主链路已有 formatRuntimeError，但渠道、部分扩展、预览和 provider 不支持提示仍使用原始/硬编码英文，应统一接入；不要把翻译后的文案相等比较当作状态标识。
- **可访问性：**全局横幅和 NoticeView 缺少统一的动态播报语义；输入框错误统一 role=status 也不足以区分阻断错误。焦点、Escape、关闭行为应一致。
- **通知导航：**[index.ts:287](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:287) 点击完成通知只 revealMainWindow；建议跳转 payload.threadId 对应任务，并保留失败/成功语义。
- **别把所有提示升级成弹窗：**复制成功、自动重连和一般说明应轻量；权限决策和丢弃编辑需要明确确认；同一失败不要同时制造多个抢眼通知。

## 已有合理设计，建议保留

- 稳定 ready 状态不持续占用连接提示空间；断线时提供诊断和重试。
- formatRuntimeError 已对认证、缺 API Key、端口冲突等常见错误进行本地化映射。
- 普通审批 store 的同步防重入，适合推广到其他决策入口。
- 发布冲突处理区分工作区缺失、冲突、恢复选择，并对任务切换和过期恢复选择做检查；已有组件测试覆盖，可以复用其处理原则。
- 截断文件禁止写回，外部变更不覆盖 dirty 编辑器内容。这些保护应保留，并补上保存过程中的版本保护。

## 验证与排除项

运行了六个测试文件，**60 项通过**：既有 54 项测试 + 本次 6 项临时诊断测试。既有覆盖为 runtime 错误格式化、发布冲突 UI、编辑器 store、pending 合并辅助逻辑、runtime adapter。

诊断测试是“断言当前错误行为存在”的复现测试，通过表示复现成立，**不代表缺陷已修复**：

1. 企业微信错误 detail 对象导致 React 崩溃——复现 F01。
2. 保存中继续输入被误标已保存——复现 F02。
3. 保存 Promise rejection 不设置 tab.error——复现 F04。
4. 服务端 pending 审批无法替换本地 error——复现 F06。
5. 服务端 pending 问题无法替换本地 error——复现 F06。
6. ApprovalBubble 独立组件在成功 props 下残留 submitting——仅组件级现象，**不计入缺陷清单**：当前父组件只渲染 pending，实际成功后会卸载卡片，不能据此声称整页持续转圈。

源码控制流已确认但未做 UI 故障注入的项目：F03、F05、F07–F12。上线前应按各自验收场景补齐真实交互验证。

原始测试源已归档为 [reproduction.test.ts](./reproduction.test.ts)，没有保留在应用 src 下。它为一次性诊断代码，含简化 mock，导入路径以原临时位置为基准。复跑时把它复制到 `packages/workbench/src/renderer/src/notice-audit.tmp.test.ts`，在 packages/workbench 下运行：

```sh
./node_modules/.bin/vitest run src/renderer/src/notice-audit.tmp.test.ts src/renderer/src/lib/format-runtime-error.test.ts src/renderer/src/components/chat/PublishConflictBanner.ui.test.ts src/renderer/src/store/workspace-editor-store.test.ts src/renderer/src/store/chat-store-runtime-helpers.test.ts src/renderer/src/agent/deepseek-runtime.test.ts
```

复跑后删除这份临时副本。修复实现时应将关键场景改写成断言正确行为的正式回归测试。

## 整改顺序

1. **第一批：**渠道错误解析、保存快照、设置失败保留草稿（F01–F03）。验收目标：失败不白屏，未保存数据不被误认为成功。
2. **第二批：**保存失败反馈、导入取消、审批恢复与防重入（F04–F07）。验收目标：取消不执行，失败可恢复，决策不重复。
3. **第三批：**自动化/MCP 部分失败、错误归属、回合终态、危险确认（F08–F12）。验收目标：结果完整准确、提示不误清除、危险动作明确。
4. **最后：**统一样式、时长、文案、可访问性和通知导航；在真实 Electron 上走一次中英文、深浅色、键盘与断网故障场景。

完整定位索引见 [inventory.md](./inventory.md)。本轮只新增审核资料，未修改应用实现。
