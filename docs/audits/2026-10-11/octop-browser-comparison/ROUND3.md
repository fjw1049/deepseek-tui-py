**Browser harness 第三轮修复 · 2026-10-12**

本轮延续 [第二轮](ROUND2.md)，补齐 open shadow / 直接子 frame 的事件采集、语义步骤生成和回放。保留原有未提交修改；没有修改安装目录中的 octop-browser，也没有升级依赖。

**实现与验证**

| 问题 | 当前处理 | 验证证据 |
|---|---|---|
| 录制把 shadow 内的 input/button 当作外层 host，路径为空。 | 新增 Workbench 采集脚本，使用 composedPath 定位实际目标；监听已有、动态创建的 open shadow roots，并记录有序 host selector。沿用 Octop 的 nonce 校验、事件存储、脱敏和语义基础处理。 | 原失败用例无法找到带 shadowPath 的 fill；现在已有 / 动态 shadow 的真实录制 → 生成步骤 → 回放通过，Save 只记录和执行一次。 |
| 防抖输入在点击后才落盘，立即停止时会丢失。 | 在点击、键盘操作、提交和停止前提交待记录输入；同一字段的 input/change 依据版本和值避免重复。 | 立即停止也有 fill；录制步骤中的 fill 先于 Save。 |
| 不同树中同名 / 同 ID 字段被合并；mask-all 使不同编辑值都相等。 | 按连续作用域编译步骤；为已经脱敏的编辑赋予独立引用，再统一生成输入参数和步骤 ID。原始事件不被修改。 | 父页 / shadow / frame，以及同字段不同时间的两个编辑保留为两个输入；checkbox false 不因脱敏被改成 true。 |
| 直接子 frame 的录制路径缺失，已保存路径也不能回放。 | 为直接子 frame 安装独立采集上下文，包括跨域和 OOPIF；记录 owner selector 与内部 shadowPath。回放通过 DOM.describeNode 的 frameId 和当前父关系解析，不按 URL 猜选 iframe。 | 同源 frame 的按钮真实录制回放通过；不同端口跨域与不同主机 OOPIF 内的 shadow 输入完整录制回放通过。 |
| frame 换地址后，同名按钮仍会被点击。 | 新录制保存已脱敏的 frameUrl；回放在目标动作前核对完整地址，只有敏感查询值按既有脱敏规则比较。 | 已复现旧逻辑仍点击；修复后错误地址拒绝，原按钮没有变化；敏感 token 不进入事件或步骤文件。 |
| 模型生成 Skill 缺少 frame/shadow 的执行入口说明。 | observe 增加 frame_selector，可和 shadow_path / 内部 selector 组合。导出 Skill 使用相同 scope 校验，并明确按作用域读取、核对地址、使用新 ref，不回退父页面。 | frame_selector 实际解析后点击子 frame 成功；生成 Skill 保留路径与作用域说明。 |
| 页面脚本派生的 click 被再次录制，回放可能重复业务操作。 | click / keydown 只收集 trusted 浏览器事件；输入状态仍兼容现有输入/选择路径。 | Primary 的处理器调用 Secondary.click()；录制只保留 Primary，回放时副作用计数为 1。 |
| 重复录制遗留监听器、history / attachShadow 包装和注入脚本。 | 停止时移除监听、观察器、overlay、新文档脚本和 binding，恢复原方法；启动失败也清理已经注入的部分并关闭独立连接。 | 第二轮 SPA navigation 只记一次，第一轮事件数量不再增加；注入后人为失败仍恢复 history，recording 全局状态清空。 |
| 原事件限流/大小限制会静默丢数据，存储异常可能终止接收循环。 | 限流、超限、存储失败和已知未支持作用域记录 capture_warning；停止保存已有证据并标记 failed，自动回放和 Skill 导出拒绝不完整记录。 | 三种采集失败有明确警告且不写原始输入；深层 frame 的不完整记录保留为可查看证据，但不能接管并自动播放。 |
| 输入值可能通过目标名称、textarea/contenteditable 文本或初始 value 属性泄露。 | 目标名称和标签复用观察层的安全文本读取，不以字段 value 作为名字；输入内容以参数占位符持久化。 | textarea、contenteditable、input 初始属性及已填写的私有标记不出现在记录元数据中。 |

录制开始连接当前 Workbench 标签；其他标签的采集继续沿用隔离浏览器内的既有发现机制。多标签自动回放仍是未支持能力，预检保持拒绝。

**验证范围**

本轮新增 26 个回归用例，综合后端 **288 通过、1 跳过**（缺少 FFmpeg）。覆盖第一轮的 16 个文件及新增 `tests/test_browser_recording.py`。日志与源码散列见 [验证日志](round3-validation-results.txt) 和 [源码清单](round3-manifest.json)。

定向 Ruff、Python 编译、采集脚本的 Node 语法检查、diff 空白检查通过。离线构建 wheel 通过，逐字节确认 wheel 包含当前 recording.py / recording.js。前端文件本轮未改，第一轮前端验证保留为历史证据。

核心代码：[recording.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/recording.py)、[recording.js](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/recording.js)、[frames.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/frames.py)、[workflows.py](/Users/fjw/Desktop/deepseek-tui-py-main/src/deepseek_tui/browser/workflows.py)。

frame owner 的 frameId 定义参照 [Chrome DevTools Protocol 的 DOM.Node](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json)；操作可用性的证据来自本项目真实 Chromium 测试。

**仍未完成的边界**

- 回放与完整录制目前限定直接子 frame；深层 frame 不完整采集会报错。父文档内 open shadow 所包含的 iframe owner 尚未支持。CSS 变换 frame 仍拒绝坐标执行。
- closed shadow、上传/下载管理、原生弹窗与多标签回放未完整实现。页面持续重建 frame / shadow 的极端时序仍需更系统的压力验收。
- 新增 frame 捕获通过发现与刷新上下文完成；本轮没有把所有动态页面时序都当作已验证。没有运行完整 Electron UI、真实账号、外部站点、付费模型或 FFmpeg 编码。
- recording 结果的 passed 仍表示路径执行；没有业务验证规则时仍不代表用户任务成功。历史记录若未包含 frameUrl，仍只具备其已有的目标语义校验。
