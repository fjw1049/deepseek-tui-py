**Browser harness 第二轮修复 · 2026-10-12**

本文件保留第二轮结果；录制路径捕获和直接子 frame 回放的后续修复见 [第三轮记录](ROUND3.md)。

延续 [第一轮修复](FIXES.md)，保留既有未提交修改。本轮优先补齐输入的焦点约束和 open shadow 回放，所有缺陷先用隔离 Chromium / 本地页面或工作流预检测试复现。

**本轮变更**

| 问题与实际影响 | 修复 | 回归证据 |
|---|---|---|
| 普通字符 `press` 返回成功，但输入框仍为空；`+` 无法解析。 | 区分文字按键与 raw 快捷键，支持 ASCII 标点、Shift 字符和 `Ctrl++`。使用原生 CDP 按键文本，保留浏览器默认行为可被页面取消的语义。 | `a`、`Shift+a`、Space、`+`、`Shift+1` 每次只插入一个字符，keydown/beforeinput/input/keyup 都是 trusted；取消 keydown 后不会强行写入。 |
| Ctrl+Alt+A、Ctrl+Shift+A 被附加 `selectAll`，错误地选择全文。 | 编辑命令只用于对应 Ctrl 或 Meta 组合；SelectAll 不接受 Alt/额外 Shift。 | 两种组合键保持原来的 [1,1] 光标范围；已有 Ctrl+A 和 Meta 全选回归保留。 |
| 给不可聚焦的 role=button 发 Enter，实际按键落在之前的输入框。 | 观察目标聚焦后必须仍是实际焦点，否则返回 `target_focus_failed` / `not_executed`；dispatch 前再次确认焦点。 | 指定不可聚焦目标后，之前输入框的 keydown 计数仍为 0。 |
| 页面阻止 mousedown 默认聚焦时，fill/type 会改写之前的输入框。 | 点击后、删除前、插入前确认当前实际焦点；同一检查覆盖根页面、open shadow、同源 frame 和 scoped 跨域 frame。失败时不发文字/删除输入。 | 原缺陷把 KEEP 改成 replacement 或插入文字；现在 KEEP、TARGET 保留，input 事件数为 0。准备点击已经发送时仍保留保守的 unknown 回执，提醒先观察，避免自动重复。 |
| fill 的全选只有 keydown，且页面看到的是无修饰键的 a。 | 全选和 Backspace 统一走成对按键路径；macOS 使用 Meta+A，其他平台使用 Ctrl+A，并保留 CDP 编辑命令。 | 页面看到成对的 a / Backspace 事件及正确修饰键；replacement 达到确认状态。 |
| Shadow DOM 内 aria-labelledby 误用 document 中同 ID 的标签。 | 在元素自己的树中查找引用标签；名称变化仍触发旧观察拒绝。 | 外层 Outer name 与内层 Inner name 共用 ID，观察读取 Inner name；内层名称改变后旧 ref 的 fill 返回 target_changed。 |
| 大 Shadow DOM 没有单独的读取范围。 | `observe` 增加 `shadow_path`，依次进入唯一的 open shadow host，可结合 frame_id 和原有分页。结果保留 `scope_shadow_path`。selector 也在观察的树内解析；嵌套元素不再广告会误指向父页的 ID selector。 | 270 个 shadow 按钮可读取后 20 个；上下文压力下路径和分页位置保留；跨域及 OOPIF 内的 scoped shadow 读取和输入通过。 |
| 已保存的 shadowPath 步骤无法回放；绕过入口预检的 `_step` 会误填父页同 selector、同名输入框。 | 预检接受有效 shadowPath，候选 selector 在指定树内观察，再通过当前 ref 执行统一目标检查。路径缺失/歧义不会回退父页。framePath 仍明确拒绝，包含直接 `_step` 调用。 | 双层 shadow 输入被正确替换，父页 parent 保留；缺失路径拒绝；公共 start_replay 流程完成并只修改 child。 |
| 自动遍历的同源 frame 绕过了 scoped frame 的 CSS 变换检查。 | 在逐层父 frame 坐标校验时，拒绝 frame 或祖先的 transform / perspective / zoom / translate / rotate / scale。 | 带 scale 的同源 frame 返回 frame_coordinates_unavailable、not_executed，按钮未点击。 |
| 工作流后续无效按键、checkbox 值或缺少变量，在执行前序步骤后才报错。 | 开始前验证所有相关参数及 checkbox 的替换结果。 | 三种损坏工作流在接管前拒绝：owner、generation、demo_task 保持原状态，第一步 click 未调用。 |

人工输入仍保持 keyDown / text / keyUp 分开的传输方式，raw keyDown 不额外插入字符。`type` 按当前或点击后的光标位置插入文字；它不承诺在末尾追加。需要替换整个字段时使用 fill。

**验证范围**

本轮新增 27 个回归用例。综合后端回归 **262 通过、1 跳过**；跳过项为缺少 FFmpeg 的编码测试。相关源码和 Chrome / 观察 / 上下文回归文件的定向 Ruff、Python 编译和 diff 空白检查通过。

最终输出和源码散列见 [验证日志](round2-validation-results.txt)、[源码清单](round2-manifest.json)。综合后端命令沿用 FIXES.md 的 16 个测试文件，并包含本轮新增测试。前端代码本轮未改，第一轮的 31 个前端测试与类型检查保留为其验证证据。

按键文本与 rawKeyDown 的区分参考 [Chrome DevTools Protocol 的 Input 定义](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json)。实际可用性结论来自本项目真实 Chromium 测试，不从协议说明推断。

**仍有边界**

- 本轮支持已经携带 shadowPath 的步骤回放。依赖内的 recorder.js 当前仍输出空 framePath/shadowPath，Shadow DOM 原始事件捕获尚未完整补齐，不能声称“录制到回放”的完整 shadow 支持。
- framePath 自动回放、深层跨域 frame、CSS 变换 frame、closed shadow、上传下载管理和原生弹窗仍未完整支持。对应 frame 路径和变换当前会明确拒绝。
- ASCII 按键和本机 macOS Chromium 已验证；不同键盘布局及其他平台尚未实测。任意文字/中文输入仍通过 type/fill。
- 未调用真实账号、外部页面或付费模型；实际模型的长任务表现和业务完成率仍待验收。没有安装 FFmpeg。
