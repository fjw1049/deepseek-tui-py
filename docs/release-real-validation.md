# 发布前真实验收清单

每次记录构建版本、平台、测试时间、运行 ID、日志位置和结果。未经实际运行不得填写通过。测试仅使用临时工作区、测试群或测试邮箱；保留运行记录用于核对。

| 项目 | 操作 | 必须核对的证据 |
|---|---|---|
| macOS / Windows / Linux 安装包 | 各自安装 → 启动 → 发送消息 → 调用 read_file 和工作区写入 → 重启 | 版本/架构、模型回复、文件实际内容、重启后历史；不能以交叉构建成功代替安装运行 |
| 原生 CUA | 使用项目自身 CuaSession，在 macOS TextEdit / Linux 文本编辑器中新建文档，输入独特标记，保存到临时目录 | 工具调用/审批、文件原始字节、完成收据、会话关闭；不能以外部 CUA 工具替代项目链路 |
| 真实第三方渠道 | 指定测试群/邮箱发送含 run ID 的一条消息，核对接收端和本地 sent 状态 | 接收端 ID/正文、本地状态；正常已确认发送不应要求再次人工确认 |
| 结果不明的投递 | 仅在受控测试接收端模拟已收但响应丢失 | uncertain、不自动重发；人工确认“已收到”后变 sent，消息数量仍为一条 |
| 明确拒收后重试 | 错误目标产生明确 4xx，修改目标后再投递 | 原正文、新目标；不重复执行原任务 |
| 凭据迁移 | 临时旧记录 → 启动 → 重启 → 恢复加密备份；另测缺失凭据库 | 运行记录不含 key、备份可解密、幂等、缺失库拒绝发送，不回退目标 |
| 无人值守 | 读取、工作区写入、沙箱 shell、可信 MCP；尝试浏览器/未信任 MCP/越界写 | 前者按环境权限工作；后者拒绝并显示需要人工协助，子代理不能放大权限 |

真实第三方测试需要用户给出渠道、明确的测试目的地及已有配置名称。当前机器无法替代其他 OS 的安装验收；供应商可用性和模型决策质量另用小额真实模型预算验证。

## 2026-11-11 已执行记录

- macOS 原生 CUA / TextEdit：通过 GUI 输入、保存以及 91 字节 UTF-8 原文核验，完成收据已接受。
- 用户指定企业微信机器人：HTTP 200 / errcode=0；本地 sent，实际仅发送一次；用户确认收到且只有一条。
- 证据与过程边界：[实机验收记录](live-validation-2026-11-11.md)。其余平台/渠道不因此视为通过。

- 后台任务恢复（后续补充）：真实临时文件、真实 Engine/子代理及异常退出进程通过；生产任务恢复路由通过本地 HTTP 验证预览不写入、GBK 字节恢复、重复恢复和拒绝旧任务续跑。见 [剩余事项复审记录](remaining-audit-2026-11-11.md)。

- 后续浏览器授权、实际包内后端与界面、冷启动、渲染依赖和 ZIP 验收见 [剩余实现与本机验收](completion-implementation-2026-11-11.md)。Windows/Linux 无测试机，用户确认本轮先完成本机验收；目录包测试不等于正式签名安装验收。

## 构建独立后端

要求安装 uv 并有 uv 管理的 Python 3.12。先在目标操作系统和架构构建运行时，再打包；不会用本机 Python 假装跨平台产物。

```sh
cd packages/workbench
npm ci
npm run prepare:runtime
npm run dist:mac:arm64
```

Windows x64 / Linux x64 在各自原生机器运行 `prepare:runtime` 后执行 `dist:win` / `dist:linux`。macOS x64 同理。预构建运行时可以通过 `DEEPSEEK_GUI_PYTHON_RUNTIME` 指向目录；源码或 uv.lock 改动后须重新构建。双架构发布使用一个集合目录，其下分别放 `darwin-arm64/manifest.json` 和 `darwin-x64/manifest.json` 及对应完整运行时，再将该集合目录设为上述变量。旧的单一 Rust/npm 二进制下载和 `DEEPSEEK_GUI_RUNTIME_CACHE` 不再使用。

Desktop/iCloud 文件提供程序若出现阻塞，应在普通本地目录的完整工作副本构建并执行 `npm ci`，不要用外链 node_modules 代替干净依赖安装，也不要让 build 与 pack 并发操作同一输出目录。

可重复执行的本机验收（项目根目录或 workbench 目录按命令所示）：

```sh
# 根目录：只使用本地 HTTP 模型夹具，实际启动包内后端、写文件并重启核验历史。
.venv/bin/python scripts/verify-packaged-runtime.py /path/to/Dayu.app/Contents/Resources/python-runtime
PYTHONPATH=src .venv/bin/python scripts/verify-automation-browser.py

# workbench 目录：使用实际 Electron/Chromium；数据保存在临时目录。
node scripts/after-pack.test.cjs
DEEPSEEK_ACCEPTANCE_RESOURCES=/path/to/Dayu.app/Contents/Resources electron scripts/smoke-startup.cjs
electron scripts/check-renderer-dependencies.cjs
```

Electron 命令也可改为 `./node_modules/.bin/electron`。原生 CUA 和第三方消息继续使用上表流程；不默认重复发送已有接收确认的测试消息。
