# 中英文字体审核

本次统一默认中英文字体的继承与回退，不恢复已撤回的字号、行高、字距和密度调整。保留小／中／大 86%／92%／100%。

## 本机 Codex 依据

读取 `/Applications/ChatGPT.app/Contents/Resources/app.asar`（bundle identifier: `com.openai.codex`）中的 `webview/assets/app-initial-5b0a474bff5e.css`：

- 桌面默认：`--font-sans-default: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`。
- 正文：`--font-content: var(--codex-content-font-family, var(--font-sans))`。
- 代码：`--font-mono-default: ui-monospace, "SFMono-Regular", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace`。
- 浏览器窗口有独立覆盖，本次对齐桌面默认。

这证明的是已安装版本的默认配置，不是运行中 Codex 所有页面或用户自定义设置的逐像素参数。

## 修正

| Before | After | Why |
| --- | --- | --- |
| 苹方位于 UI 字体第一位 | 系统西文字体优先，显式保留苹方中文回退 | 避免英文也使用苹方的西文字形 |
| 聊天和侧栏各自定义字体栈 | 都继承统一 UI 字体 | 中英文在导航、正文、菜单之间保持同一搭配 |
| 模型选择器 Shadow DOM 写死另一套字体 | 继承 UI 字体变量 | 避免组件内部脱离外部配置 |
| 全局 code/pre/kbd 使用比例字体，Streamdown 又覆盖代码字体 | 代码使用统一等宽字体，正文继承规则排除 code/pre | 与 Codex 的正文／代码区分一致 |
| 模型 ID、编辑器删除行使用独立等宽字体配置 | 统一继承代码字体 | 防止技术文本在不同位置切换字形 |
| Monaco 自己选择字体，未跟随主题代码字体 | 初始化及主题切换时同步字体 | 编辑器与删除行使用同一字体；保留 12px 字号、20px 行高 |

## 覆盖与验证

- 全量扫描 `packages/workbench/src` 的 CSS/TS/TSX/JS 字体声明和引用，96 处记录见 `font-sources.json`。
- Chromium 使用真实项目 CSS、Tailwind 和模型选择器组件验证 34 个代表性表面 × 2 种文档语言 × 2 种主题 × 3 个缩放档，共 408 项字体继承／缩放检查。
- 覆盖侧栏、设置、功能页、插件、消息频道、自动化、弹窗、菜单、顶栏、右侧面板、输入、消息编辑、正文、标题、表格、过程文字、IDE 阅读区域、子代理报告、行内代码、代码块、全屏代码、快捷键、模型 ID、编辑器删除行和 Shadow DOM。
- 将 Codex 默认字体栈与项目默认字体栈放入同一个 Chromium 渲染器，通过 `CSS.getPlatformFontsForNode` 检查 400/500/600/700 × 中文/英文，共 8 组实际字体选择，全部一致。
- 中文：PingFang SC（400 Regular、500 Medium、600/700 Semibold）；英文：.SF NS，按字重选择系统可变字体。
- 22 项外观和历史消息测试通过；生产构建通过；`git diff --check` 通过。
- 对照图 `font-comparison.png` 已检查，左右采用相同字号和字重，以便单独比较字体搭配。

## 明确保留与验收边界

- 各位置原有字号、行高、字距、字重层级继续保留；本轮没有把所有文字强制改成同一个大小。
- 用户显式选择的主题 UI 字体继续生效；主题代码字体、终端自定义字体继续生效。这些自定义配置不保证与 Codex 默认相同。
- 终端由 xterm 维护独立等宽字体和字符网格；Mermaid 标签使用代码字体；网页预览中的第三方内容保持自己的字体；预览检查浮层使用独立系统字体。
- 字体测试使用真实 CSS 的隔离样本，不等于逐个打开所有业务页面。Monaco 同步通过代码审核和构建验证，未在每种编辑器／终端状态下做现场截图。
- 实际字形比较在本机 macOS 上完成，未验证 Windows/Linux 的回退字形。截图也不是 Codex 运行窗口的截图。

运行：在 `packages/workbench` 目录执行 `node_modules/.bin/electron scripts/check-bilingual-fonts.cjs`。可通过 `FONT_AUDIT_OUTPUT` 指定保存计算样式和截图的目录。
