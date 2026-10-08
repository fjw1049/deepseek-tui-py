# build_1004：Octop 浏览器模块

第一版接入 octop-browser 1.0.0，保留现有 Python Agent 和 Workbench。
普通网页预览不变，右侧「预览」中增加「Agent 浏览器」。

## 本次可一起验收的功能

- 每个对话独立的 Chromium 会话，页面操作与实时画面来自同一会话。
- Agent 的 browser_use 工具：打开、读取 DOM、点击、填写、按键、滚动、
  检查页面文字、截图、开始/结束步骤录制。
- 用户接管、交还控制权、结束会话。接管会作废排队的旧操作；
  已发出的原子操作可能完成，无法撤销已经提交的动作。
- 固定步骤本地 demo：填写名称、切换通知、保存、展开结果、两次文字断言。
- 截图和步骤动图，按对话保存；结束浏览器不会删除证据。

步骤动图是动作后的页面快照，不是连续视频。固定 demo 不调用模型；
它验证执行链路，不宣称验证模型自主规划能力。

## 启动

使用 Python 3.11+（建议 3.12）。已安装 Chrome、Edge、Brave 或 Chromium 即可；
octop-browser 也能发现本机已有的 Playwright Chromium。

    uv sync --extra browser --extra dev
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

Octop 的操作回放及生成 Skill、连续视频、Electron 被测实例、跨任务持久登录，
尚未接入本版。演示结果不代表这些功能完成。底层的私有 CDP 截图接口集中在
browser.py，依赖固定为 1.0.0，升级时需重跑真实浏览器测试。

来源与许可证见 THIRD_PARTY_NOTICES.md。
