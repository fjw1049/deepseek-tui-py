# 剩余实现与本机验收（2026-11-11）

接续 `remaining-audit-2026-11-11.md`。用户确认没有 Windows/Linux 测试机，本轮完成 macOS 可执行的实现与验收。已有修复、公开接口和旧数据读取能力保留；未提交、推送或发布。

## 本轮实现

| 项目 | 实际变化与边界 |
|---|---|
| 自动化额外浏览器能力 | 已保存自动化的编辑界面增加独立授权开关，GET/PUT `/v1/automations/{id}/permissions`。普通 CRUD 和模型工具不能授予权限。权限绑定任务正文、工作区、摘要设置及授权版本；修改作用域、撤销或重新授权都会使旧排队授权失效。每次浏览器调用前重新检查。已经开始的操作可能完成。 |
| 浏览器会话隔离 | 有授权的无人值守任务使用私有 BrowserService 和临时任务会话，不复用用户登录状态；子代理使用独立会话。任务结束关闭浏览器。原生 CUA 仍不开放给 cron，也不在准备阶段偷偷建立原生 CUA 连接。 |
| 兼容入口退役 | 增加只读统计 CLI，聚合现有 `legacy_tool_used` 事件。必须明确完整日志覆盖并达到 30 天才可标记人工复核候选；无日志不代表零使用，工具不会自动删入口。 |
| 大模块边界 | 将 `dispatch.py` 的旧工具映射、参数修复分别移入 `legacy_tools.py`、`tool_arguments.py`；旧导入保留。流解析不再为参数修复加载整个 dispatch。没有拆分其余无明确收益的模块。 |
| 参数修复真实错误 | 原尾逗号正则会损坏字符串中的 `,}` / `,]`。改为识别字符串和转义状态，只移除结构性尾逗号。用最终写出的真实文件内容验证。 |
| 独立安装包后端 | 旧 after-pack 依赖已移除的 npm/Rust 包，启动器只找开发机 Python。现从 `uv.lock` 导出生产依赖，构建项目 wheel，携带 uv 管理的本平台 Python；包内优先启动自身后端，不注入源码目录。源码/锁文件/目标架构不匹配时拒绝打包。构建完成后再替换旧产物，安装目录允许其他用户读取。 |
| 依赖及实际构建内容 | 更新兼容范围内的 MCP、飞书、Axios、Zod 等锁定依赖；Monaco 升级到 0.57 并适配导出路径与 hover 配置。显式使用 DOMPurify 3.4.17，覆盖 Monaco 的内嵌清洗器导入；Mermaid 改用 ESM 构建，避免继续加载包含旧清洗器的预打包脚本；局部约束其 KaTeX 到已修复版本。本机锁定 KaTeX 0.18.10。 |
| 技能 ZIP 导入 | 确认原文本路径检查无法阻止“符号链接 + 同名文件”的外部覆盖。统一提取函数拒绝 ZIP 符号链接，普通文件/目录兼容。真实恶意 ZIP 的外部目标保持原样；正常 SKILL.md 解压成功。 |

浏览器授权不是任意远端副作用的撤销承诺。用户显式授权的浏览器操作可以修改页面状态；原生桌面权限、任意文件系统越界、未信任 MCP 均不因此开放。

## 已执行验收

| 验收 | 结果 |
|---|---|
| Python 全量 | **4,380 passed / 175 skipped / 36 deselected，0 warnings**，192.91 秒；排除付费 live/live_mcp。不是所有跳过项都已实测。 |
| 最终前端全量 | **322 文件 / 2,097 项通过**，33.89 秒。保持所有测试和原超时，用 `--maxWorkers=4` 控制资源争用。 |
| 类型与静态检查 | TypeScript、所增 Python 模块/脚本 Ruff、`git diff --check` 通过；打包目标/过期产物/多架构目录保护测试通过。 |
| 真 Chrome 自动化 | 打开本地 HTTP 页面、点击并读取页面变化；子代理会话没有继承主任务页面状态；撤销授权后的操作被拒。没有外部消息或模型请求。 |
| 真 Chromium 渲染 | 实际 Monaco 编辑中文并更新模型；JSON Worker 返回无效 JSON 诊断；Mermaid 中文流程图及数学公式渲染；危险 onerror/javascript 链接被清洗，安全粗体保留。 |
| 构建产物清洗器 | 最终 renderer 构建中检测到 DOMPurify **3.4.17**；不能仅用 npm 依赖树推断预打包资源版本。 |
| macOS arm64 目录包 | 生成包含独立 Python 的 Dayu.app。Electron 验收脚本加载包内真实 main/preload/renderer，设置 IPC 与页面加载通过，使用独立用户数据目录。 |
| 包内后端 | 从源码目录外启动实际包内解释器；真实 HTTP 创建会话，调用真实 `write_file` 写出中文，下一次模型请求确实包含工具结果。模型是本地确定性 HTTP 夹具，非真实供应商。 |
| 包内授权 HTTP | 实际 GET/PUT 授权、读取、正文修改自动失效、重新授权及撤销均通过。测试自动化为暂停状态，不会定时执行。 |
| 冷启动 | 包内后端停止并重启后，原回合 ID 和 completed 状态保持一致。 |
| 真实用户旧记录 | 只读检查本机 118 条运行记录，全部可解析，没有发现需要迁移的明文凭据候选。没有停止用户正在运行的进程或修改这些记录；既有可重入迁移仍在下次正常启动生效。 |

前序已完成的真实文件/进程/MCP/投递异常闭环、macOS TextEdit 和企业微信接收确认继续有效，见 `live-validation-2026-11-11.md` 及前序报告。本轮没有重复向测试群发送消息，也没有新增付费模型调用。

机器可读验收证据：`validation/completion-2026-11-11.json`。关键日志：

- `/tmp/complete-python-full.log`
- `/tmp/complete-frontend-accepted.log`
- `/tmp/complete-typecheck-accepted.log`
- `/tmp/automation-browser-real.log`
- `/tmp/renderer-dependencies-acceptance.log`
- `/tmp/packaged-app-final-acceptance.log`
- `/tmp/packaged-gui-final-acceptance.log`
- `/tmp/complete-mac-package-accepted.log`

## 失败、修正与复跑

没有把失败当通过：首次前端测试受到回环端口限制、进程争用和超时影响；允许本地服务并限制并发后全量通过。Monaco 升级暴露旧 worker/URI 导出路径和 hover 类型不兼容，适配后全量复跑通过。真实 JSON Worker 验收也改用新版公开服务导出，未删去该检查。

Desktop 位于 iCloud File Provider 目录。打包及复制曾停在旧输出文件的内核读取，采样确认后只停止本轮进程，改在 `/private/tmp` 直接生成新构建。最初外链 node_modules 导致漏包，改成按锁文件干净安装生产依赖后重新打包，包内启动通过。临时验收脚本另修正了回合状态名和 HTTP 返回形状；不属于产品回归。

## 仍不能写成“全部发布工作完成”

1. **Electron 与开发构建链的跨大版本安全升级仍需审核。** 当前 Electron 为 34.5.8；完整 npm audit 不为零。不能因为 Electron 被列在 devDependencies 就忽略安装包实际携带它。需明确最低系统版本和维护分支，再验收原生模块、权限及安装升级：例如 [Electron 44 起不再支持 macOS 12](https://www.electronjs.org/blog/electron-44-0)，直接接受 npm 推荐的 45 会改变系统兼容边界。此次未用 force 强制升级，也不把该风险算作已消除。
2. 干净生产依赖安装仍报告 **extract-zip 一条 high**。项目唯一的技能导入入口已增加符号链接拒绝并通过真实 ZIP 测试；这是调用方防护，不等于上游库告警消失。应在后续替换该库或使用正式修复版本，Electron 安装阶段使用的上游依赖另随构建链处理。
3. Windows/Linux、macOS x64、Linux CUA 没有实机环境；按用户本轮确认不继续等待。macOS 验收为临时目录包及包内运行，不包含正式 Developer ID 签名、公证、DMG 拖拽安装或发布升级渠道验收。
4. 旧工具退役仍需真实 30 天覆盖数据和发布迁移窗口。当前报告明确为证据不足；保留兼容是已实施策略，不是可以立即删除的待办。
5. stdout/stderr 字段删除、更多缓存和任意大模块拆分不继续实施：前序已确认调用方依赖与收益不足；不以改动量作为完成标准。历史凭据没有发现额外迁移对象，因此不做无依据的批量改写。

依赖依据：[MCP HTTP 重定向凭据问题](https://github.com/advisories/GHSA-6prh-2h8m-c8cw)、[Zod 验证资源问题](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5)、[KaTeX 修复及触发条件](https://github.com/advisories/GHSA-238p-pmpm-9mq7)、[Monaco 0.57 官方发行记录](https://github.com/microsoft/monaco-editor/releases/tag/v0.57.0)。安全快照保留在 `/tmp/security-all-audit.json`；它在最终清除旧嵌套清洗器之前生成，不能拿其中旧版本的条数冒充最终生产树。最终干净生产安装日志为 `/tmp/package-security-dependencies-install.log`。
