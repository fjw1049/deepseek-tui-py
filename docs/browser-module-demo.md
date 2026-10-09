# build_1004：Octop 浏览器模块

第一版接入 octop-browser 1.0.0，保留现有 Python Agent 和 Workbench。
普通网页预览不变，右侧「预览」中增加「Agent 浏览器」。

浏览器实现集中在 `src/browser/`：`service.py` 管理会话，`install.py` 安装浏览器，
`workflows.py` 录制回放，`skills.py` 生成 Skill，`video.py` 保存连续视频，
`browser_demo.html` 提供本地演示页面。工具入口保留在
`src/deepseek_tui/tools/browser.py`，HTTP 接口保留在
`src/deepseek_tui/server/browser_routes.py`。

## 本次可一起验收的功能

- 每个对话独立的 Chromium 会话，页面操作与实时画面来自同一会话。
- Agent 的 browser_use 工具：打开、读取 DOM、点击、填写、按键、滚动、
  检查页面文字、截图、开始/结束步骤录制。
- 用户接管、交还控制权、结束会话。接管会作废排队的旧操作；
  已发出的原子操作可能完成，无法撤销已经提交的动作。
- 固定步骤本地 demo：填写名称、切换通知、保存、展开结果、两次文字断言。
- 截图和步骤动图，按对话保存；结束浏览器不会删除证据。
- 演示步骤进度和中断提示；重新运行清空上轮步骤日志，保留证据。
- 文字检查支持 timeout_ms（0–10000 毫秒）；界面默认等待 3 秒。
  检查不通过或浏览器返回操作失败时，尽力保存失败现场截图。
  抛出的异常和中断也记入失败日志；浏览器断连时可能无法截图。
- 重复开始录制不会清空已有片段；达到 40 帧时结束也会返回已保存的动图。

步骤动图是动作后的页面快照。另可录制连续 WebM 视频，见第四组。固定 demo 不调用模型；
它验证执行链路，不宣称验证模型自主规划能力。

## 启动

使用 Python 3.11+（建议 3.12）。已安装 Chrome、Edge、Brave 或 Chromium 即可；
octop-browser 也能发现本机已有的 Playwright Chromium。

    uv sync --inexact --extra browser --extra dev
    cd packages/workbench
    npm ci
    npm run build
    cd ../..
    uv run --extra browser python scripts/demo-browser-module.py

脚本创建独立数据目录、Runtime（127.0.0.1:7894）及 Electron 窗口。
打开「浏览器模块演示 · build_1004」对话，右侧 + → 预览 →
Agent 浏览器 → 运行整组演示。可添加 --port 指定其他端口。
演示未配置真实模型，聊天不会产生付费模型调用。
不要将 --state-dir 指向日常数据目录，它仅用于演示数据。

要让演示窗口使用当前分支项目，启动时添加 `--workspace "$PWD"`。
指定固定的 `--state-dir` 后，重启会复用同一工作目录的演示对话。
`--electron-executable` 可指定独立 Electron 可执行文件，方便区分日常窗口与测试窗口。
接续开发状态与未完成项目见 [browser-build1004-handoff.md](browser-build1004-handoff.md)。

## 一次模块验收

1. 运行整组演示：画面中出现实际输入、开关变化、保存结果，最后显示验证通过。
2. 查看截图和步骤动图；动图应包含操作中的中间状态。
3. 再运行一次，在过程中接管：自动流程停止；点击画面或使用元素操作继续填写。
4. 交还 Agent 后重新运行；结束会话后证据仍可查看。
5. 换一个对话创建浏览器，确认不会看到或操作上一个对话的页面。

常规聊天中可要求 Agent 使用 browser_use 验证指定页面，需要自行配置模型。
浏览器操作按照现有工具审批策略执行，批准范围绑定本次动作及浏览器状态。

## 模块测试

    uv run --extra browser --extra dev pytest tests/test_browser_module.py tests/contract/test_browser.py
    DEEPSEEK_BROWSER_E2E=1 uv run --extra browser --extra dev pytest tests/test_browser_module.py
    cd packages/workbench
    npm run typecheck
    npm test -- BrowserWorkspace DevBrowserPanel dev-browser

浏览器通过本地 CDP 工作，localhost 不经系统代理。调用方应只访问获准页面，
不应把 localhost 浏览器当作网络沙箱。截图可能包含页面个人信息，由用户控制保留。
会话最多 8 个，步骤录制最多 40 帧；达到上限自动生成动图。
动态文件只保留在运行时数据目录，不进入代码仓库。

## 后续模块

Electron 被测实例、跨任务共享登录，
尚未接入本版。底层的私有 CDP 截图接口集中在
`src/browser/service.py`，依赖固定为 1.0.0，升级时需重跑真实浏览器测试。

来源与许可证见 THIRD_PARTY_NOTICES.md。

## 第二组：环境、登录状态与流程回放

右侧 Agent 浏览器 →「会话、环境与流程回放」：

1. 「检测环境」读取运行时 Python、Octop 依赖和可用浏览器。
   「重启并接管浏览器」结束当前操作，重新启动本对话浏览器。
   不在故障后自动重试可能产生重复提交的动作。浏览器安装见第三组。
2. 在会话结束时开启「保留此对话的登录状态」，再启动浏览器。
   Chrome 网站数据按对话保存在本机，关闭会话不会清除；关闭开关只切回临时模式。
   「清除保存的登录数据」会删除保存的配置，保留截图与流程。默认仍为临时模式。
3. 先运行本地 demo，再接管，点击「录制可回放流程」。填写名称，点击保存，
   点击「停止并保存流程」。点录制条目查看步骤，在参数框填写新名称，再执行流程。
   回放会真实操作页面，支持接管中断，并生成截图与步骤动图。

录制复用 Octop RecordController、SemanticProcessor 和 RecordingStore；
回放通过当前会话执行，避免默认全局回放器重新寻找浏览器。输入值按 mask-all
处理，回放参数仅在本次运行内存中使用，不写入回放报告；页面文本、URL、截图
仍可能包含个人信息。录制产生的数据仅保存在当前对话目录。

当前回放支持单页面的打开、跳转、点击、填写、按键、勾选和下拉选择，以及
Octop 生成的 URL 检查。多标签页、滚动步骤等会在执行前报错，不能声称完整支持
Octop 所有回放能力。页面定位必须唯一，失效定位需要重新录制。
回放步骤执行成功不等于业务验证成功，仍应检查具体页面结果。

模块验证覆盖：环境与接口鉴权、配置隔离、断连恢复、录制参数脱敏、真实表单回放、
接管中断、持久网站存储和清除。真实测试使用本地演示页面，不登录外部账户。

## 第三组：浏览器安装与 Skill 交付

同一面板中的「安装或校验 Chromium」使用 Octop 的 install_chromium_stream。
安装器独立运行，展示最近 40 条日志，支持取消和失败后重试；关闭 Runtime 会终止
安装器及其进程组。完整安装可能下载 Chromium、安装 Playwright，Linux 上还会
尝试补齐系统依赖。已有可用 Chromium 时直接校验。安装不是每次启动时自动执行。

录制条目 → 查看步骤 → 填写 Skill 名称与用途 →「生成并预览 Skill」→
「安装到当前项目」。生成物是自包含的 SKILL.md，使用 browser_use 而非 Octop CLI。
工具补充了 select 和 set_checked，以表达下拉选择和目标勾选状态。
安装调用现有 Skill 安装器，目标为当前项目 .agents/skills，同名冲突不会覆盖；
在应用市场的已安装 Skill 中管理，新对话能按既有发现机制读取。

预览与安装之间使用内容摘要校验，修改名称、描述或录制步骤后需要重新预览。
输入示例不会导出；来源页面文字与 URL 仍可能包含个人信息，应审阅完整内容。
如果录制来源是内置 file 页面，生成物会要求 local_page_url 参数，在使用时提供
对应的 http/https 页面地址，避免生成依赖本机包路径且无法调用的 Skill。
录制结构、格式和安装发现已测试；尚未验证真实模型自主执行生成 Skill 的成功率。

## 第四组：连续视频、地址同步与证据导出

Runtime 的 PATH 中存在 FFmpeg 时，演示和回放会自动保存 WebM 视频；
也可接管后使用「开始连续录像」和「结束并保存录像」。视频独立于动作锁采集，
包含步骤间等待时的画面，每秒 5 帧、最长 180 秒，不包含音频。
达到上限后停止采集，点击结束录像或结束会话可将文件加入证据列表。
缺少 FFmpeg 时仍可执行演示、截图和步骤 GIF，手工开启视频会明确提示依赖缺失。
录像错误独立展示，不将截图/GIF 冒充连续视频。

地址栏跟随主页面实际地址（包括重定向和页内跳转）更新；地址没有变化时，
轮询不会覆盖正在输入的新地址。当前对话从工作台传入浏览器面板，切换对话会
重新绑定对应会话。元素操作中可直接用选择器点击，方便接管后录制表单提交。

「导出验收证据包」会生成本机 ZIP 并在文件管理器中定位，包含最近 80 步、
12 份截图/GIF/视频以及 report.json。正在执行或录制视频时需先结束。
report.json 分别记录执行状态、明确的文字断言及其预期内容；没有文字断言时
verification 为 not_checked，不能将操作完成视为业务验证通过。
关闭浏览器和重启 Runtime 后仍可导出已保存证据；包中不含登录 profile 或流程输入参数，
但页面 URL、断言文字及图像可能含有隐私内容。

更新后需重启 Runtime。正在运行的旧 BrowserRun 对象无法使用新录像模块，
仅刷新前端不足以完成后端升级。
