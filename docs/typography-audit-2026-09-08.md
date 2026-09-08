# 主界面与 IDE 模式字体审核报告

> 此报告保留优化前的审核快照。后续字体优化已完成，见[优化结果](./typography-optimization-2026-09-08.md)。

审核日期：2026-09-08。审核对象：当前工作区中的 Electron Workbench；包含未提交的界面改动。你所说的“idle”已确认为点击编辑器后，左侧文件／代码、右侧大模型问答的 **IDE 模式**。

**结论：你觉得不协调有明确的实现依据。最主要的问题是整体缩放与局部小字号叠加、同一内容在不同状态下变字号，以及字体规则互相覆盖。并非把所有文字统一调大就能解决。**

本次只审核，未修改应用代码。

## 1. 审核方法与边界

- 扫描 renderer 中 304 个非测试源码文件；113 个文件命中字体、字号、字重、行高或字距声明，共 1,587 行，另核对共享设置、Tailwind 配置、Streamdown 的实际组件输出规则和 Monaco 配置。
- 追踪主界面、空首页、会话、输入与编辑、过程记录、工具、审批、子任务、右侧面板、IDE 编辑器、弹出层与 Shadow DOM。
- 使用项目安装的 Electron／Chromium、实际 Tailwind 配置和当前 `index.css`，按组件中的关键 DOM 结构构建隔离样本，测量 **chat／IDE × 阅读字号 12／16／20px** 的计算样式。样本包含 Streamdown 自带的表格与 H5／H6 类名，避免把声明值当成生效值。
- 这是**全量源码扫描＋重点路径级联验证**，不是把运行中的所有交互状态逐个截图验收。没有读取你的个人外观设置，也没有验证每个字形最终使用哪一个本机字体文件；当前设置、操作系统字体回退、显示器缩放及外部页面仍可能进一步影响观感。
- 外部 HTML／网页预览、图片中的文字、Mermaid 生成图、数学公式与原生系统菜单有自己的排版来源，不能诚实地列成一组固定字号。下文单列其边界。

附录提供[完整源码索引](./typography-audit-2026-09-08/source-inventory.md)与[计算样式测量数据](./typography-audit-2026-09-08/computed-styles.json)。索引是声明清单，含条件分支和被覆盖的旧规则，不表示所有声明同时生效。

## 2. 首先看“字号”到底有多大

**新安装默认使用“中”，对应整体缩放 0.88；“大”才是 1.00。** 源码中的 16px 不一定按 16px 的屏幕布局尺寸显示。

| 设置 | 实际整体缩放 | 说明 |
|---|---:|---|
| 小 | 82% | 所有 body 内界面一起缩小 |
| 中（默认） | 88% | 不是通常预期的 100% 基准 |
| 大 | 100% | 代码声明值的原始大小 |

| CSS 声明字号 | “中”下等效显示尺寸 | 常见位置 |
|---:|---:|---|
| 8px | 7.04px | 首页推荐卡小徽标 |
| 9px | 7.92px | IDE 活动计数、部分状态徽标 |
| 10px | 8.80px | 代码语言标签、计数与状态 |
| 11px | 9.68px | 路径、时间、IDE 元信息 |
| 12px | 10.56px | 文件树、IDE 过程、Monaco 编辑器 |
| 13px | 11.44px | IDE 标题、普通工具标签、默认终端 |
| 14px | 12.32px | 普通表格单元格等 |
| 15px | 13.20px | 侧栏、普通输入框 |
| 16px | 14.08px | 默认问答正文 |

这里是 `字号 × CSS zoom` 的等效布局尺寸，不是设备物理像素；`getComputedStyle().fontSize` 仍可返回缩放前的值。

证据：[apply-theme.ts:39](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-theme.ts:39)；[index.css:848](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:848)；[settings-store.ts:241](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/main/settings-store.ts:241)。

**判断：这是“小、密、细”的首要原因。** IDE 先把导航与过程降至 11／12px，再整体缩小 12%，小字同时采用浅色和细字重，阅读负担会明显增加。这是实际规则，不是对你的显示器做推测。

## 3. 所有字体来源

| 字体用途 | 当前来源 | 设置是否统一控制 |
|---|---|---|
| 普通控件、输入框、弹窗、标题 | `--font-ui`，标题 `--font-display` 指向它 | 跟随 UI 字体与主题字体 |
| 默认 UI 字体 | 新安装选择 system-native：Apple 系统字体 → PingFang SC 等回退 | 默认并不是 Inter |
| 可选 Inter UI 字体 | Inter → PingFang SC → Noto Sans SC → 系统回退 | 选择 Inter 或相应主题时启用 |
| 左侧项目／会话导航 | 局部 `--font-sidebar`，独立系统字体栈 | 不跟随 `--font-ui` 的自定义变化 |
| 用户气泡、最终回答 | `--font-chat`，system-ui 优先 | 阅读字号可调，字体不跟随 `--font-ui` |
| 模型／推理强度选择器 | Shadow DOM 内硬编码 Apple／SF Pro Text／Segoe UI | 不跟随 `--font-ui` |
| 普通技术文字、Diff、结构树 | `--font-mono` | 可被主题的 codeFont 替换 |
| 对话行内代码 | 本应使用代码字体，但被更强的 Streamdown 继承规则覆盖 | 当前可落到聊天字体，见问题 4 |
| 对话围栏代码 | `pre` 与子级 `code` 各有规则；子级默认落到 UI 字体 | 主题 codeFont 可介入，但默认不是可靠的等宽体系 |
| 终端 | `--font-terminal`，默认设置 JetBrains Mono，缺失时回退 | 独立终端字体与字号设置 |
| Monaco 编辑器 | 未显式设置 fontFamily，由 Monaco 自身默认决定；字号固定 12 | 不跟随聊天阅读字号或终端字体 |
| Markdown 文档预览 | `--font-ui`，文档排版规则 | 正文固定 16，独立于聊天字号 |
| Mermaid／公式／HTML／网页 | 图形渲染器、公式库或文档自身样式 | 不能靠普通 UI 字体设置完全覆盖 |

证据：[index.css:16](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:16)；[index.css:303](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:303)；[index.css:2970](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2970)；[index.css:6427](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6427)；[reasoning-effort-selector.js:95](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:95)；[apply-appearance.ts:68](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:68)；[WorkspaceEditorSurface.tsx:265](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorSurface.tsx:265)。

**重要校正：默认 system-native 下，多个栈在 macOS 上可能落到相同系统字体，不能直接断言“默认同时看见几种完全不同字体”。真正确定的是字体来源彼此独立；切到 Inter 或自定义主题后，这种分裂更容易显现。**

内置字体文件只显式加载 Inter／Noto Sans SC 的正常体 400／500／600。全局又关闭字体合成，因此 650／700、斜体等声明在未提供相应字面时可能回退或匹配到现有字重。系统字体模式的表现则依赖本机字体，不能把这一点一概判为缺字或错误。

## 4. 确认的问题与优先级

### A. 优先处理：整体缩小叠加 IDE 微字号

“中”=88%，IDE 主操作、文件树与代码编辑正文大量为 12px，元信息为 11px。编辑器不是偶尔扫一眼的角标，却与辅助文字接近大小。右侧回答 16、左侧编辑器 12，在默认缩放后成为约 14.08 对 10.56，左右视觉分量失衡。

建议：先明确 100% 基准，再决定 IDE 的导航／代码／过程最小字号。不要只把右侧回答调大，否则左右差距更明显。证据见第 2 节、[WorkspaceEditorSurface.tsx:265](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorSurface.tsx:265)、[index.css:11255](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11255)。

### B. 优先处理：输入 → 发送 → 编辑，同一段话会改变排版

普通模式输入框与编辑框固定 **15px／行高 22.5px／UI 字体**；已发送内容跟随阅读设置，默认 **16px／25.28px／聊天字体**。阅读设置调到 20 后，编辑时会从 20 缩回 15。

IDE 已把输入、编辑、发送统一到阅读字号与聊天字体。结果是同一输入框在普通模式和 IDE 间还会变化。

建议：普通模式与 IDE 使用同一套“可编辑会话正文”字体与阅读字号；控件标签独立保留紧凑尺寸。证据：[index.css:2150](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2150)、[index.css:2195](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2195)、[index.css:6751](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6751)、[index.css:11182](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11182)、[index.css:11614](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11614)；已用计算样式验证。

### C. 优先处理：代码阅读字号和全屏行为不一致

| 状态，阅读设置 16px | 普通模式 | IDE |
|---|---:|---:|
| 回答正文 | 16 | 16 |
| 行内代码 | 14.4 | 14.4 |
| 围栏代码 | 12 | 14.4 |
| 代码全屏正文 | 15 | 12 |
| 结构树代码 | 12.5 | 12.5 |

普通模式代码点全屏会从 12 变 15；IDE 中却从 14.4 **变小到 12**。当阅读设置为 20 时，IDE 内代码为 18，全屏仍 12，差距更大。

根因：正常代码的样式依赖 `.ds-markdown` 祖先；全屏由 Portal 挂到 body，实际没有该祖先，也没有回答字号规则。IDE 对弹窗只补了通用 12px。

建议：代码组件自身持有代码字体与字号，全屏保留调用内容的阅读尺寸，不应因 DOM 挂载位置而变小。证据：[index.css:5940](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5940)、[index.css:11367](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11367)、[index.css:11807](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11807)；[SharedCodeBlock.tsx:445](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SharedCodeBlock.tsx:445)、[SharedCodeBlock.tsx:496](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SharedCodeBlock.tsx:496)；[ResizableFullscreenDialog.tsx:203](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ResizableFullscreenDialog.tsx:203)。已核验实际全屏组件结构并测量。

### D. 优先处理：代码并未可靠使用等宽字体

1. `.ds-markdown [data-streamdown]:not(...):not(...)` 强制 `font-family: inherit`，优先级高于回答行内代码规则。真实行内代码带 `data-streamdown="inline-code"`，实测继承聊天字体。
2. 围栏代码内部 `code` 的显式 `font-family: var(--ds-chat-code-font, var(--font-ui))` 覆盖来自父 `pre` 的等宽字体继承。默认未配置 codeFont 时，代码实际采用 UI 字体。
3. 全屏代码失去 `.ds-markdown` 祖先，回到全局 `code, pre { font-family: var(--font-ui) }`。

这会让同一代码在 Monaco、Diff、回答与全屏中呈现不同字形和字符宽度，缩进与列对齐的观感也不一致。

建议：缩小 Streamdown 的字体继承选择器范围，显式排除代码；统一代码容器和内部 code 的字体来源。证据：[index.css:889](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:889)、[index.css:4890](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4890)、[index.css:4990](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4990)、[index.css:5016](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5016)、[index.css:6654](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6654)；[StreamdownCode.tsx:142](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StreamdownCode.tsx:142)。已测量正常模式与 IDE 中真实类名对应的结果。

### E. 中优先级：普通模式的表格绕过阅读字号设置

真实 Streamdown 表头带 `text-sm`，又被 `.ds-markdown th` 固定为 **13px**；单元格仍由 `text-sm` 固定为 **14px**。外层 table 虽写了 `0.94em`，并不能改变子元素自己的显式字号。

阅读设置从 12 调至 20，普通表格仍为 13／14。IDE 后续专门的规则已把回答表格恢复到阅读字号，因此相同表格在两种模式显示不同。

建议：回答里的 th／td 直接使用一致的阅读比例，不能仅设置 table。证据：[index.css:6011](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6011)、[index.css:6699](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6699)、[index.css:11859](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11859)；已包含 Streamdown 实际类名进行验证。

### F. 中优先级：过程文字的声明值与生效值不符

组件给推理正文和过程 Markdown 声明 `text-[13.5px] leading-6`，但 `.ds-markdown` 位于 Tailwind utilities 之后，同优先级覆盖为 **15px／22.5px**。普通旁白不带 `.ds-markdown`，仍是 **13.5px／24px**。

于是：纯文本旁白较小却行距更松，切到格式化过程后文字变大、行距反而更紧。IDE 则统一覆盖成 12px／18.6px。

建议：让过程正文由一个明确的语义样式决定，删除彼此冲突的字号声明；无需重构整个 CSS 文件。证据：[index.css:1](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1)、[index.css:4882](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4882)、[MessageTimeline.tsx:2294](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2294)、[MessageTimeline.tsx:2395](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2395)、[index.css:11428](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11428)；已验证。

### G. 中优先级：H5／H6 未纳入阅读字号体系

H1–H4 使用正文的 em 倍率；H5／H6 则保留 Streamdown 的固定 **16／14px**。当阅读设置为 12 时，IDE H4 只有 **12.24px**，H5 却为 **16px**，层级倒挂。阅读为 20 时，H5／H6 又比正文小很多。

建议：把 H1–H6 放入同一个明确的阅读层级，允许较低层级靠字重区分，但不要混合固定 rem 与正文倍率而产生反向大小。证据：[index.css:6521](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6521)、[index.css:11342](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11342)；本地 Streamdown `heading-5／heading-6` 实现；已验证 12／16／20 三档。

### H. 设计一致性：字体设置覆盖范围不清楚

UI 字体、侧栏字体、聊天字体、Shadow DOM 模型选择器字体彼此独立。主题选择 Inter／其他字体时，页面的一部分改变、一部分保持系统字体。默认系统字体模式下差异可能较轻，属于设置一致性与主题体验问题，不能说每个用户都必然看见强烈差异。

建议：如果希望统一，侧栏与选择器继承 UI 字体；若聊天确需独立阅读字体，应在设置与设计规则中明确表达。证据见第 3 节。

### I. 设计一致性：小字号、分数字号、字重层级过细

主工作流分散使用 10、10.5、11、11.5、12、12.5、13、13.5、14、14.5、15、16 等尺寸；首页还有 8、输入附件或徽标有 9。分数字号本身不是错误，但在 88% 缩放后，12 与 12.5 只差 0.44 等效像素，难以形成稳定的信息层级。

同时存在 400／450／500／550／560／600／620／650／700 等字重请求；是否真正有这些字面由字体决定。其分散程度大于当前界面所需的语义层级。

建议：先保留正文、控件、辅助、标题、代码这几类，再收敛档位；不建议为了“整齐”强行让首页标题、终端和所有徽标同大。

## 5. 主界面文字覆盖清单

下表均为**缩放前 CSS px**。`R` 是聊天阅读字号，默认 16，可设 12–20；字体 UI／Chat／Mono 对应第 3 节。动态分支的原始声明见逐文件索引。

| 区域／所有相关状态类别 | 字体与字号 | 审核判断 |
|---|---|---|
| 左侧导航、项目名、会话名 | Sidebar，主要 15；次级／搜索 14；分组／时间 13；品牌 18 | 基本有三级体系，但独立于 UI 字体设置 |
| 侧栏未读、当前选中、拖拽 | 以 400／500 和背景区分；局部强调还有 700 | 选中不靠整体字号改变，合理 |
| 项目／任务右键菜单、重命名、悬浮卡 | 菜单多 13；悬浮信息 13／13.5；侧栏命中语义类的项由其样式覆盖 | 必须同时看局部菜单 CSS，不能只看 Tailwind |
| 会话页眉、标题编辑、工作区说明、动作菜单 | SessionHeader 声明 20／21／22 标题档，12／12.5／13／13.5 元信息与动作 | 不同标题呈现路径单独定义，见附录 |
| 简洁空首页 | UI 标题 clamp 21.6–26.4；输入 15 | 标题随视口变大，是有意的响应式处理 |
| 丰富首页问候、日期、统计 | 问候 22／24；日期 12.5；数值 20；统计标签 11 | 标题层级清楚，元信息受缩放影响 |
| 推荐列表、趋势卡、加载／失败 | 标题 14.5；简介 12；元信息 10／10.5；徽标 8；分区标题 16；失败 13／12 | 8–10px 最值得收敛 |
| 离线／重连首页 | 主提示 20；说明 14；按钮 12.5 | 状态文字与常规首页有独立尺寸 |
| 输入正文与 placeholder | UI 15／行高 22.5 | 不跟随 R；与发送后内容不同 |
| 输入编辑历史消息 | UI 15／22.5 | R 改变后差异更明显 |
| 用户消息、前缀标签 | Chat R，字重 400；前缀 500，字号继承 | 显示态跟随设置 |
| 最终回答、段落、列表、普通链接 | Chat R／1.7 行高；强调 500；斜体按字体可用字面 | 正文读起来比过程更松 |
| H1／H2／H3／H4 | 1.4R／1.35R／1.25R／1.1R，600 | 默认 22.4／21.6／20／17.6 |
| H5／H6 | 固定 16／14，600 | 不跟随 R，存在倒挂 |
| 行内代码 | 0.9R；当前会继承聊天字体 | 不可靠的等宽显示 |
| 文件引用、文件名与行号 chip | 正文场景继承文字；弹出候选列表另有 12／13／14 | 实际 FileChip 已替代旧 file-reference DOM，不能误报旧选择器的 11px |
| 围栏代码／语言标签／结构树 | 12／10／12.5；结构树 Mono | 回答代码固定字号，全屏另有变化 |
| 表格表头／单元格 | 13／14 | 阅读设置未覆盖真实单元格 |
| 详情折叠 summary | 0.9R | 跟随正文 |
| 数学上标／下标、公式 | HTML 相对排版或数学渲染样式 | 不应拿其小字当普通正文档位 |
| 推理展开、过程 Markdown、过程旁白 | UI；前两者实测 15；旁白 13.5；推理折叠按钮 14 | 级联造成正文不一致 |
| 工作元信息、耗时、完成／中断等状态 | 主摘要常见 15；时间 11／11.5／12 | IDE 另有紧凑覆盖 |
| 工具批次、工具名、输入、路径、输出、展开全文 | 标签统一 token 13；输出常见 11／12；代码样式需按渲染器核对 | 不等于所有工具文字都统一 13 |
| 工具门禁、审批、权限提升、用户补充输入、演进通知 | 11／12／12.5／13／14 混用；原始命令与输出有 pre／Mono 分支 | 关键操作不宜长期小于辅助文字 |
| 待办计划、步骤流、子任务摘要／报告 | 标题 14、常见正文 13／13.5／14；步骤元信息 9–12；报告阅读正文 R | 容器级覆盖未必改变内部固定字号 |
| 修改总结、文件列表、发布冲突 | 总结标题 15；路径／主要动作 14；说明 13；冲突细节 11.5 等 | 与相邻紧凑工具行的分量不同 |
| 模型与推理强度选择器 | 独立系统栈；触发标签 14，菜单 13，辅助 11／12，空态 12.5 | Shadow DOM 单独维护 |
| 输入区权限、模式、上下文、目标条、工作区操作 | 多 12／13；目标条还有 10.88／11.84／13.12 | 有 rem 分数换算；缺统一标尺 |
| 附件、@选择、技能／连接器列表、排队输入、语音、提示 | 主要 12／13；描述 11；徽标 9／10；页脚 11.5 | 数量多，详见 FloatingComposer 与对应组件索引 |
| 会话搜索、历史查询、快捷键、快速打开 | 搜索输入 17；结果分主次约 13–15；快捷键／日期约 10–12 | 全屏/Portal 不会自动获得 IDE 内部样式 |
| Git 分支、提交、日志、冲突弹窗 | 多 12／12.5／13；弹窗标题 18；角标 10／11 | 保留独立操作界面体系 |
| 右侧变更检查、Diff | 文件名 12.5；代码 12.5 Mono；行号 11；差异计数 12 | 与聊天代码、Monaco 并非同一尺寸 |
| 编辑器标签、文件树、错误与空状态 | 标签／树主要 12；提示 11／12／13 | 独立于阅读字号 |
| 终端内容与终端页签 | 内容默认 13，可设 10–22；页签 12／12.5 等 | 内容字号有独立设置，合理；仍受整体 zoom |
| 右侧运行过程／结果面板 | 过程 12／结果 13；容器宽≥700 时变 14／15；元信息 10–11.5 | 明确独立于聊天字号，面板变宽还会换档 |
| Markdown 文件预览 | UI 正文固定 16／1.72；文档标题另有倍率与 rem | 不跟随 R，不等于聊天 Markdown |
| 网页／HTML 预览、图片预览 | 工具栏常见 11／12／12.5／14；内容字体由文件本身决定 | 外部页面与图片内文字无法穷举固定字号 |
| 初始设置、连接异常、运行诊断 | 提示多 11–15；诊断标题 18 | 已扫描条件状态；无须把设置页所有表单视为聊天正文 |
| 图标按钮的原生 title 提示、系统菜单 | 浏览器／系统管理 | 不能用页面 CSS 当作最终字体依据 |

## 6. IDE 模式文字覆盖清单

**IDE 并不是“所有文字统一变 12”。其规则只在聊天轨道、特定弹窗与组件上生效。** 文件编辑器、项目导航、运行面板有各自体系。

| 区域／状态 | IDE 字号／字体 | 是否跟随 R |
|---|---|---|
| 顶部项目名／路径／菜单分组 | UI 13／11／10.5；菜单项目 12.5、路径 11 | 否 |
| 顶部文字动作、聊天页签 | UI 12；页签状态徽标 10 | 否 |
| 活动栏计数 | 9 | 否 |
| 文件树、目录行、文件行、工作区根标题 | UI 12；部分改动点标 10 | 否 |
| 文件搜索输入／结果／父路径／空态／错误 | 12／12.5／11／12／12 | 否 |
| 快速打开 | 搜索输入 17；结果按全局搜索 CSS | 否；它是独立弹窗 |
| Monaco 代码、行号、编辑器内辅助 UI | 代码配置 12／行高 20；内建控件由 Monaco 各自规则决定 | 否；未接聊天／终端字号 |
| 编辑器页签、保存状态、无文件与读取错误 | 主要 11／12／13 | 否 |
| Diff 内容／行号／文件名 | Mono 12.5／11；文件名 12.5 | 否 |
| Markdown 预览正文 | UI 16／27.52 | 否 |
| 用户消息、输入正文、placeholder、历史编辑 | Chat R／1.7 | 是；这部分比普通模式更统一 |
| 最终回答 | Chat R／1.7 | 是 |
| 回答 H1–H4 | 1.35R／1.25R／1.15R／1.02R，600；行高 1.25 | 是；比普通模式更紧 |
| 回答 H5／H6 | 16／14，600 | 否 |
| 回答表格 | 表头、单元格均 R／1.7；表头 600 | 是；末尾规则已修复紧凑覆盖 |
| 行内代码／围栏代码 | 0.9R；字体覆盖问题仍存在 | 是 |
| 结构树 | Mono 12.5 | 否 |
| 推理、旁白、格式化过程 | UI 12／18.6 | 否 |
| 工作元信息／工具行 | 13／12 | 否 |
| 工具原始输出／命令详情 | 常见 11／12，视具体 renderer | 否，不应只读父容器 token |
| 待办、步骤流、子任务摘要 | 正文被匹配的档位降为 12，标题 13，时间／角标 9–11 等仍有独立声明 | 否 |
| 修改总结 | 标题保留 15，路径保留 14，部分按钮匹配 12，其他 14 保留 | 否；比相邻 12px 工具行更醒目 |
| 审批、提升权限、补充问题、演进通知 | 容器 12；命令 pre 常见 11；子级显式 11／12／13 可继续保留 | 否；容器字号不是子级全部字号 |
| 回答时间与操作元信息 | 11 | 否 |
| 模型触发标签、权限／模式等紧凑操作 | 12；模型菜单仍 11／12／12.5／13 | 否 |
| 输入附件／命令／提示列表 | 继承共享组件的 9–13，局部标题 13 | 否；IDE 未全量重映射 |
| 会话历史查询行 | Chat R／1.7，独立 Portal 类修正 | 是 |
| 聊天页签历史菜单 | 标题 12.5、时间 11、空态 12 | 否；与上一行是不同历史入口 |
| 子任务弹窗：框架／报告 | 框架 12、标题 13；报告 R／1.7；报告代码 0.9R | 部分是 |
| 代码全屏 | UI 12／18.6；语言名 11 | 否；比轨道内代码小 |
| 回退确认弹窗 | 标题 13；匹配的说明 12；内部固定小标签仍独立 | 否 |
| Git／设置／搜索等通用弹窗 | 继续使用共享样式 | 否；未被错误地一概降为 12 |
| 终端 | 独立终端字体，默认 13／1.2 行高 | 否；有专门终端设置 |

## 7. 经过核验，不能误报的情况

- **IDE 回答正文不是 12px。** 前面的规则确实写了 12，但后面的更具体规则恢复到 R。
- **IDE 回答表格不是 11／12px。** 当前文件末尾已恢复到 R；普通模式的表格才仍有固定字号问题。
- **IDE 用户消息／编辑框／输入框已跟随阅读字号。** 当前剩余的不一致主要在普通模式。
- **实际文件引用用 FileChip。** 旧 `.ds-file-reference-link` 的 11px 规则不能直接当作当前文件链接缺陷；按真实组件测量，正文 FileChip 跟随 R。
- **流式回答与最终回答共用回答容器。** 没有发现“只因结束流式状态，最终答案就整体换字号”的证据；过程消息转入最终回答属于不同语义块。
- **Diff、终端、首页标题采用独立字号本身合理。** 问题在于是否可读、是否被隐性缩小、同一内容切换是否稳定。
- **当前样式文件已有未提交改动。** 本报告以眼前工作区为准，不把历史提交或旧注释当成现状。

## 8. 建议的修正顺序与验收标准

建议按以下顺序处理，避免一口气全局替换 px：

1. **先统一尺寸基准。** 明确默认整体缩放是否回到 100%。验收：IDE 的文件树与代码达到预期可读尺寸，普通主界面无意外拥挤。
2. **修复确定的级联与状态问题。** 代码字体、代码全屏、普通模式输入／编辑、表格 th／td、H5／H6、过程 Markdown。验收：阅读设置 12／16／20 三档，同一内容在普通／IDE、内嵌／全屏、显示／编辑之间不出现未设计的变小或字体切换。
3. **再收敛字体与档位。** 默认推荐以系统 UI 栈为基础；代码明确等宽；正文先保留 16，控件集中到 13／14，辅助信息以 12 为常用下限，少量徽标另议。IDE 编辑器可优先试 13–14，而不是固定 12 再整体缩小。以上是设计建议，需结合实际窗口试读，并非外部标准的强制值。
4. **最后做真实页面目视回归。** 中文＋英文＋数字、长路径、Markdown 表格、H1–H6、代码、错误／审批／子任务，覆盖浅色／深色、Inter／系统字体、窄轨道／宽轨道以及三档阅读字号。

应保留的检查重点：相同代码等宽且全屏不变小；相同一句话编辑前后字号稳定；表格响应阅读设置；小阅读档位不发生标题倒挂；IDE 文件树、代码、对话三者形成清晰但不过分悬殊的比例。

**最值得先改的四项：88% 默认缩放、代码等宽字体、代码全屏尺寸、普通模式输入与显示尺寸。** 它们比继续追加局部 0.5px 调整，更接近你当前不协调感的根源。
