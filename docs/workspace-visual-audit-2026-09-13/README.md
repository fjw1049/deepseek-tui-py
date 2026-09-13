# 文件、编辑与更改视图审核

日期：2026-09-13。范围：当前工作区桌面工作台的 WorkspaceFileTree、WorkspaceEditorPanel、WorkspaceEditorSurface、MarkdownDocumentPreview、DiffView、ChangeInspector、IdeWorkspaceLayout，以及相关主题与 CSS。

## 结论

用户感到“不够优雅”有具体实现原因：**顶部基线不齐、状态标记失效、代码阅读规则不统一、预览与源码切换缺少完整闭环。** 优先修正这些问题，再调整视觉风格，收益比继续增加背景、圆角和强调色更大。

这不是与当前 Codex 界面的逐像素比较。原生界面读取超时，未获得运行中应用的完整逐屏截图。本轮完成源码追踪、当前 Tailwind 编译、Electron 隔离 CSS 渲染和计算样式测量；隔离页面使用源代码结构样本，不能代替完整组件与真实数据验收。未修改应用实现；开始时 index.css 已存在用户工作区改动，审核使用该版本并保留它。

## 应优先修复的确定问题

### 1. 未保存圆点在静止状态不可见

- 位置：`src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:264`；`src/renderer/src/index.css:1610`。
- dirty 圆点位于关闭按钮内部，而整个关闭按钮默认 `opacity: 0`。悬停时父按钮变为可见，圆点又被另一条规则设为 `opacity: 0`，换成 X。稳定状态下并没有达到注释所说的“未保存显示圆点”。
- 隔离渲染确认深浅色父按钮 opacity 都为 0。
- 影响：离开标签后看不到未保存状态，Git 更改的空心圆点和编辑铅笔也不能准确替代它。
- 建议：dirty 标签的关闭槽保持可见，只切换槽内圆点与 X；Git 状态、编辑模式、未保存状态分别定义。

### 2. 主题切换没有更新 Monaco 代码主题

- 位置：`src/renderer/src/components/workspace-editor/WorkspaceEditorSurface.tsx:64,142,259`；`src/renderer/src/lib/monaco-editor-setup.ts:71`。
- `monacoTheme` 仅在标签变化或挂载时重新计算。监听 `data-theme` 的 MutationObserver 调用的是 `syncFont`，只更新 fontFamily。
- CSS 又立即把编辑器背景切换为新主题颜色，语法 token、选区、行号和查找控件仍可能保留旧 Monaco 主题。
- 影响：当前文件保持打开时切换深浅色，容易出现新背景配旧前景色的低对比度界面。
- 建议：同一次外观同步更新 Monaco 主题及字体；复测同一文件、双栏、查找框和选区。该项为源码确认，尚未完成真实 Monaco 交互复现。

### 3. 多处文件树悬停背景类未生成

- 位置：`src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:398,460`；`tailwind.config.js` 的变量色配置。
- 源码使用 `hover:bg-ds-hover/55` 等带透明度后缀的变量色类。当前配置未提供支持这种组合的颜色格式。
- 使用当前源码重新运行 Tailwind 后，生成样式中没有对应 `/55` 悬停规则；隔离 CSSOM 检查也确认缺失。不能仅凭 JSX 中有类名认定效果已实现。
- 影响：未选中的文件行、目录行缺少预期背景反馈，表现比选中态生硬。不是所有 hover 都失效，例如独立编写的 CSS 仍有效。
- 建议：优先修当前视图中的无效类，用有效 token 或显式 color-mix，再统一 hover、active、focus 的强度。

### 4. 查找把文档切为源码，但没有明确返回预览入口

- 位置：`src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:406–447`。
- Markdown/HTML 阅读状态点击查找会设置 `sourceFindOpen=true`，显示 Monaco。该状态只在换标签或进入编辑时重置；关闭 Monaco 查找框不会重置它。
- 影响：用户只是查找文本，却改变了整个文档的呈现；关闭查找后仍停在源码视图。
- 建议：提供明确的“预览 / 源码”切换，查找行为服从当前视图；或在关闭源码查找时恢复预览。

### 5. 切换文件重新创建编辑器，阅读位置与编辑历史缺乏保留

- 位置：`src/renderer/src/components/workspace-editor/WorkspaceEditorSurface.tsx:249`。
- `<Editor key={tab.id}>` 随文件切换卸载重建，没有提供稳定的 model path，也没有实现每个文件的 viewState 保存/恢复。当前安装的 @monaco-editor/react 默认卸载时会 dispose model；保留文本内容不等于保留撤销栈、光标和滚动位置。
- 影响：来回阅读文件缺乏连续感；编辑后切走再返回可能失去原撤销历史。
- 建议：按稳定文件 URI 管理模型与每个 pane 的 viewState，在关闭文件时释放。复测两个长文件交替切换、撤销和分栏。此项为源码及本地依赖实现核对，尚未完成真实交互复现。

### 6. 标签溢出缺少当前文件跟随

- 位置：`src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:193–215,250`。
- 溢出只检测总宽度并加右侧渐隐；没有在当前标签变化时滚动到所选标签，也没有依据滚动位置调整边缘遮罩。
- 同名文件仅显示 basename，路径需要悬停才能看到；现有 breadcrumb 工具函数并未接入编辑器标题。
- 影响：从文件树打开靠后的标签，当前文件名可能留在可视范围之外；两个 `index.ts` 很难区分。
- 建议：选中标签自动进入可视范围；仅对重名标签显示最短区分路径，必要时用轻量路径栏。遮罩随滚动边界更新。

## 直接影响观感的排版问题

### 7. 顶部基线不齐，字号与容器尺寸不协调

- 位置：`src/renderer/src/index.css:1694–1737`；`WorkspaceFileTree.tsx:482`；`index.css:8092`。
- 文件树标题 40px、IDE 文件标签栏 28px、更改视图标题 36px。文件树与编辑器相邻时，水平分割线产生 12px 的台阶。
- 通用覆盖又把文件名、标签按钮统一设为 15px，部分 JSX 原设计为 12.5px；标签内上下 padding 仍存在。
- 隔离实测：40px 与 28px；文件标签栏的继承行高 23.25px，15px 字号。侧栏密度、标签高度和文字尺寸没有一起设计。
- 建议起点：相邻标题统一 36px；文件行 28–30px，文件名约 13–14px；代码 14–15px。数值是设计候选，必须结合用户字号偏好和中文实屏验收，不应强行缩小一切。

### 8. 更改视图强制拆开代码标识符，且没有语法高亮

- 位置：`src/renderer/src/components/DiffView.tsx:414,426,492`。
- 表格 `table-fixed` 配合 `break-all whitespace-pre-wrap`，统一和左右对比都可能在变量、路径中间断行。普通编辑器则 `wordWrap: 'off'`，切到更改视图后同一行完全变形。
- 隔离验证：350px 样本中一行代码高度 89px，约四行，computed word-break 为 break-all。
- Diff 内容直接渲染字符串，没有语法 token；新增/删除整行文字再染绿/红，读代码的结构信息被变更颜色取代。
- 建议：代码默认保持行结构，允许横向滚动，提供可选换行；窄视图优先 unified。以淡底与 gutter 表达增删，保留语法色，必要时强调真正变化的字符范围。

### 9. 编辑器把删除内容直接插进源码阅读区

- 位置：`src/renderer/src/lib/apply-editor-diff-highlights.ts:7–23,36–43,89–100`；`index.css:8631–8646`。
- 新增背景应用在整行和嵌套 span，半透明背景存在叠色风险。删除块独立生成 DOM，固定 56px 左 padding、15px 字号、20px 行高和红色文字，无语法高亮。
- 普通文件内容中会出现不存在于当前文件的删除行，且左右对齐依赖硬编码值，与 Monaco 实际 gutter/字号配置脱节。
- 建议：常规编辑视图优先细 gutter 标记；在专门更改视图显示删除内容。若保留内联 diff，位置、字体、行高要取自当前编辑器配置，避免多层半透明背景叠加。
- 该项叠色程度与删除块实际对齐尚需真实 Monaco 截图验证；不是已完成的像素测量。

### 10. Markdown 阅读排版不适合所有宽度

- 位置：`src/renderer/src/index.css:6257–6290`。
- 阅读列最大宽度 1120px；段落和列表统一两端对齐，启用自动断词。中文、英文、路径混排在窄栏里容易出现不自然的字间与词间空隙，宽屏则一行过长。
- 同一文档在普通右栏是 16px，在 IDE 是 15px；字体、代码块、表格又存在单独覆盖。
- 建议：正文左对齐；阅读列按文字长度限制，先试 70–85ch；窄栏减小页边距。中英文使用同一明确的字号与行高层级，代码块独立滚动。
- 这是设计判断；1120px 本身并非功能错误，需要长中文段落和英文文档实屏比较。

### 11. 文档代码块没有复用代码高亮能力

- 位置：`src/renderer/src/components/workspace-editor/MarkdownDocumentPreview.tsx:19`。
- 文档只有 ReactMarkdown + remarkGfm，没有代码块 renderer 或语法高亮插件；带语言的 fenced code block 仍是普通 pre/code。聊天另有 Shiki，编辑器又使用 Monaco。
- 影响：同一代码从聊天到文档再到编辑器，呈现差异很明显。
- 建议：复用现有代码高亮基础能力，但保持文档自己的简洁代码块外观，无需把聊天控件整套搬进来。

### 12. 文件树状态色过重且语义不完整

- 位置：`src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:384–387,414,458–464`；`index.css:1387–1406`。
- 文件只按“有 patch”着绿色，不区分新增/修改；目录有子文件变更也整段名称变绿。选中态再叠加色字、背景、左强调线和加粗。
- 影响：变更多时导航树大面积着色，与代码增删色争抢注意力；“修改”和“新增”不容易区分。
- 建议：文件名保持主要中性色，尾部使用紧凑 M/A/D 等状态或细小标记；选中态选择一项主要强调，其余减弱。保留不依赖颜色的状态含义。

## 建议的改进顺序与验收

1. **修复状态与连续性**：dirty、主题同步、有效 hover、预览返回、model/viewState 保留。验证切主题、保存前后、查找退出、文件往返及撤销。
2. **统一空间节奏**：文件树/编辑器/更改标题的基线；文件行和标签的字号、图标、间距；同名与溢出标签。验证 1280/1440 宽窗口及最窄右栏。
3. **统一内容渲染**：代码与 diff 的字体/行高/换行策略、语法色、删除行展现；Markdown 的阅读列与对齐。用长路径、中文注释、长代码行、表格、混合段落验证。
4. **最后降低视觉噪声**：导航状态色、强调线、重复边框、工具按钮常显数量。保留清晰键盘焦点，避免只追求“淡”而降低可辨认性。

建议目标：导航安静、内容清晰、状态准确、切换连续。不是简单把所有字号缩小、所有背景改白，或再追加一层 !important。

## 验证资料

- `probe.cjs`：可复跑的隔离 CSS 探针。不是完整组件测试。
- `computed.json`：Electron 计算样式结果。
- `isolated-light.png`：隔离结构样本截图，不是应用全貌或最终设计稿。
- 构建命令（在 packages/workbench 下）：`node node_modules/tailwindcss/lib/cli.js -i src/renderer/src/index.css -o /tmp/workspace-visual-audit.css`。
- 探针命令（同目录）：`./node_modules/.bin/electron ../../docs/workspace-visual-audit-2026-09-13/probe.cjs`。

未进行功能修改，因此没有运行整库测试；没有声称完成实时应用全流程验收。
