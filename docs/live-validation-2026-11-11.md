# 企业微信与 macOS TextEdit 实机验收 · 2026-11-11

用户提供专用企业微信 webhook 并授权发送一条验收消息，同时确认 Mac 已解锁。本次补足此前受环境限制的两项验收，没有调用付费模型。

## 企业微信：通过

通过实际 `TaskManager` 生成并持久化任务结果，经 `AutomationManager` 保存/重读凭据引用，再调用生产 `try_deliver_completed_run` → `_WecomSink` → `wecom_webhook_send_text`，实际发往用户指定的企业微信机器人。没有用直接 curl 代替项目投递链。

- Run ID：`wecom-live-20261111T114746Z-93d52b`
- Task ID：`task_bbcc3a4d`
- 实际 HTTP POST 次数：**1**；响应 **HTTP 200，errcode=0，errmsg=ok**。
- 持久化状态顺序：**pending → sending → sent**；`delivery_done=true`、`delivery_attempts=1`。
- 重新打开运行记录后再次调用投递入口，返回“不需投递”，没有第二次网络请求。
- 用户已核对测试群并明确确认：**已收到，且只有一条**。
- 磁盘运行记录和 `to_public_dict()` 均未包含 webhook 密钥/完整地址。密钥通过隐藏终端输入读取，没有写入测试脚本、报告或日志；验收后删除仅用于本次测试的凭据库，保留脱敏证据。

本次是正常明确成功的投递，因此直接成为 sent，无需人为制造 uncertain 或额外点击确认。真实群未用于超时/断线重发实验，避免产生重复消息；不明投递与人工确认的本地 HTTP/API/界面测试仍见此前记录。

机器证据：[wecom-verification.json](validation/live-2026-11-11/wecom-verification.json)。

## macOS TextEdit：通过

通过项目自身的 `CuaSession` → `bridge.mjs` → 已安装 LCU 操作原生 TextEdit；没有用 AppleScript、Shell 写文件冒充 GUI 输入/保存。

1. 按 bundle ID 获取 TextEdit，在文件选择面板新建文稿。
2. 切换为纯文本，输入带唯一标记的中英文内容。
3. 保存对话框选择测试临时目录，以 UTF-8 保存。
4. AX 状态显示正确文件路径、文件名和完整正文。
5. 随后独立读取保存文件，逐字节与预期 UTF-8 比较，**91 字节完全一致**。
6. 原生工具接受 `Saved TextEdit validation document` 完成收据；项目 CUA 会话已关闭。

文稿标记：`cua-textedit-20261111-7_724frr`。

SHA-256：`34798085ad3aeb4627f89333e53dd4f00c7021eb2e2b49d0613faa3b02ef0604`。

证据：[cua-verification.json](validation/live-2026-11-11/cua-verification.json)、[保存结果副本](validation/live-2026-11-11/textedit-output.txt)。原件路径记录在 JSON 中；仓库副本仅在 GUI 保存并核验后复制留存。

过程中一次快捷键调用报告应用未激活，重新读取 AX 状态后恢复。保存弹窗中的连续键盘/粘贴批处理没有达到预期定位，随后采用字段 `setValue` 和逐步状态核对完成；正文的 paste 最终字节验证通过。现有证据不足以把弹窗行为归因为 paste 实现缺陷，没有做猜测式源码修改。这也说明操作返回成功不能代替最终 UI 和文件核验。

## 验收边界

本次通过的是指定企业微信机器人和本机 macOS TextEdit 的实际链路。Windows/Linux 安装包、Linux 原生桌面、其他外部渠道仍未验收；后台任务持久文件撤销等产品事项仍见运行时升级报告。本轮没有改变此前 **Python 4,354 / 前端 2,091** 的回归测试口径，也没有重新运行与本次证据补充无关的全量测试。
