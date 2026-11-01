# Browser Use 独立复现演示

这是依据本次调查目标新写的最小实现，使用 Playwright Core 1.58.2 驱动独立 Chrome 会话。无需项目主程序、LLM 或账号。它演示“观察 → 定位 → 预检查 → 执行 → 等待效果 → 再观察”的完整闭环；Codex 的具体证据与未覆盖部分由上级目录的逆向报告说明。本目录不包含 Codex 专有 bundle。

## 一键验收

在当前机器上，无需另装依赖：

```sh
PLAYWRIGHT_MODULE_PATH=/Users/fjw/.local/share/rea/node_modules/playwright-core \
/Users/fjw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-10-11/codex-browser-use/replica/browser-use.mjs --demo
```

程序会读取上级 `demo.html` 与 `frame.html`，启动临时只读 HTTP 服务，运行真实 Chrome headless，退出时关闭浏览器、服务，并删除专用临时浏览器配置。所有表单只改变页面内存。保留上级两份验收页面即可独立于项目主程序复跑。

其他机器可在此目录运行 `npm ci`，然后运行 `npm run demo`。需要 Node 20 或更新版本，以及本机 Chrome。macOS 默认可执行文件为 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`；其他路径通过 `CHROME_EXECUTABLE_PATH` 指定。`playwright-core` 不会下载浏览器。`package-lock.json` 固定依赖版本和完整性摘要。

成功输出为一行 JSON，包含通过数与结果目录。当前验收为 **18/18**，输出保存在 `results/`：

- `report.json`：18 项断言、每次操作的 execution/effect/observation、最终语义快照。
- `before.png`：首个标签页初始状态。
- `verified.png`：首个标签页完成表单、frame、Shadow、遮挡及接管检查后的状态。
- `after.png`：第二个标签页中“提交已完成、观察失败”恢复后的状态，保存次数为 1。

验收覆盖：语义填写提交与保存次数 1；有限条件等待；重复目标拒绝；唯一可见目标；遮挡时拒绝与解除后成功；跨源 frame；开放 Shadow DOM；新观察淘汰旧观察；接管中拒绝与恢复后重新观察；预检查期间接管与导航均阻止派发；错误标签页 token 拒绝；标签页状态保持；动作完成但观察失败的恢复且不重放；效果超时单独记录。

## 持续工具协议

不加 `--demo` 时，程序启动一个持久浏览器上下文，逐行读取 stdin JSON，并逐行输出 JSON。这个会话及标签页持续到进程退出。`id` 原样返回，错误返回 `error`。输入结束后自动关闭浏览器。

```sh
PLAYWRIGHT_MODULE_PATH=/Users/fjw/.local/share/rea/node_modules/playwright-core \
/Users/fjw/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node browser-use.mjs
```

先运行一个本地 HTTP 页面服务，输入：

```json
{"id":1,"op":"open","url":"http://localhost:8000/demo.html"}
```

保留返回的 `result.sessionId/tabId/generation/token`。操作必须携带最新观察头；下面的 `...` 必须替换为真实返回值，`generation` 也必须照用：

```json
{"id":2,"op":"act","observation":{"sessionId":"...","tabId":"...","generation":0,"token":"..."},"action":"fill","target":{"role":"textbox","name":"项目名称","scope":{"role":"region","name":"本地表单"}},"value":"演示项目"}
```

每次操作返回新 `observation`，下一步使用它的观察头。提交示例：

```json
{"id":3,"op":"act","observation":{"sessionId":"...","tabId":"...","generation":0,"token":"..."},"action":"click","target":{"role":"button","name":"保存项目","scope":{"role":"region","name":"本地表单"}},"effect":{"text":"已保存：演示项目","scope":{"role":"region","name":"本地表单"},"timeout":1500}}
```

| op | 参数与作用 |
| --- | --- |
| `open` | `url`，新建标签页并返回观察；仅允许 HTTP localhost/127.0.0.1 |
| `switch` | `tabId`，切换已归属此会话的标签页并返回新观察 |
| `observe` | 读取当前标签页及所有 frame 的语义树 |
| `act` | `observation`、`action`、`target`；fill 另需 `value`；可选 `effect` |
| `wait` | `condition`，只等待一个可见的精确文本；可带 `frame/scope/timeout` |
| `takeover` | 暂停自动动作，所有旧观察失效 |
| `resume` | 恢复自动动作，之后必须重新观察 |

`target` 固定用精确 `role/name`。可加 `scope: {role, name}` 缩小范围；`frame` 是 iframe 的精确 `title`，例如 `"跨源验证表单"`。可见候选不是恰好一个时直接拒绝，不用序号猜测。效果用精确文本及可选相同范围验证，最长 3000 ms。

## 执行事实与效果

`execution.state` 的含义：

- `rejected`：观察、范围、唯一性或预检查不满足，未派发实际 click/fill。trial click 可能滚动页面。
- `completed`：浏览器动作调用已返回。业务结果仍须看 `effect`。
- `unknown`：实际动作调用抛错，动作可能已经生效，不能据此重放。

`effect.state` 为 `verified` 或 `unverified`；后者包括结果文本等待超时。`effect: null` 表示没有要求效果验证或动作未完成。动作成功后如果观察失败，会保留 execution/effect，并返回 `requiresObserve: true`，要求重新观察；原观察已失效。演示不做外层动作重试。Playwright 自身仍有有限的可操作性等待。

## 借鉴行为与本地设计选择

此次实现采用会话与标签页显式绑定、语义定位、严格唯一性、限定范围、frame、条件等待及操作后检查这些行为目标。`results/` 只证明本演示运行结果，不证明 Codex 曾执行这些操作；Codex 静态分析、实际运行观察和推断应分别以逆向报告为准。

以下是为了可验证而新增的设计选择：随机观察 token；全局 generation；每次新观察、动作、切换标签页、frame 导航、接管与恢复都淘汰旧观察；预检查前及实际派发前再次校验；明确区分 execution/effect；用只读本地页面及观察失败注入验证不重放。750 ms 点击预检查、1000 ms 动作超时、3000 ms 等待上限也属于本演示的选择，不是 Codex 的实际常量。

## 边界

- 人工接管必须通过 `takeover/resume` 明确信号触发。headless 验收模拟接管状态，不提供可视接管界面；已派发到浏览器的命令不能原子撤回。实现以单一串行调用者为前提。
- 同一进程维持会话及标签页，退出删除配置；不提供跨进程会话恢复、真实账号、cookie 导入或弹窗管理。
- 观察使用 ARIA 文本树，单个 frame 最多保留 16000 字符，并标注 `truncated`。这是有损字符串裁剪，可能切断层级，**未实现结构化投影、稳定 target registry 或项目报告中的 G1 改进**。
- 导航和显式接管会使观察失效；任意外部 DOM 修改、手工点击与异步内容变化无法全部自动检测。实际动作前重新定位并检查可操作性也不能保证页面快照原子一致。
- 只实现 click/fill、精确文本等待、单层 title 指定 frame 和开放 Shadow DOM。没有闭合 Shadow DOM、跨源网络追踪、坐标操作、上传下载、拖拽或 LLM 决策循环。
- 页面请求限制为 HTTP loopback；此限制是演示范围，不等同于完整网络隔离。局部本地 Chrome 运行通过并不证明生产网站兼容。

这些边界均属于后续产品化工作，不以当前通过数替代。修改后重新运行 `--demo` 即可复核现有闭环。
