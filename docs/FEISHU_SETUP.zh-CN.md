# 飞书 / Lark 接入指南

本仓库支持两种飞书能力：

| 能力 | 用途 | 依赖 |
|------|------|------|
| **出站投递** | 定时自动化任务把 Agent 结果发到飞书 | `config.toml` 的 `[automation.feishu]` + Runtime |
| **入站对话** | 在飞书里发消息，由 Agent 回复 | 长连接桥 `docs/CodeWhale-main/integrations/feishu-bridge` |

Workbench：**设置 → Claw → 飞书 / Lark** 可填写凭证、接收人 ID，并发送测试消息。

---

## 一、飞书开放平台（必做）

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，创建 **企业自建应用**。
2. 在「凭证与基础信息」复制 **App ID**、**App Secret**。
3. 启用 **机器人** 能力。
4. 在「权限管理」申请并发布（或测试企业内生效）：
   - 接收消息
   - 发送消息
   - 获取用户 open_id（配对时常用）
5. 把应用安装到你的企业/测试租户。

国际版 Lark：将 `domain` 设为 `lark`，并在 [Lark Developer](https://open.larksuite.com/) 创建应用。

---

## 二、本地凭证（定时投递 + 测试消息）

任选其一：

### A. Workbench GUI（推荐）

1. 启动 Workbench，确保 **设置 → 基础** 里 Runtime 已连接（`deepseek serve --http`）。
2. 打开 **设置 → Claw → 飞书 / Lark**。
3. 填写 App ID、App Secret，保存。
4. 填写 **接收人 ID**（见下文「如何拿到 open_id」）。
5. 点击 **发送测试消息**，在飞书里应收到一条测试文本。

### B. 手动配置文件

在 `config.toml` 增加（与邮件 `[automation]` 同文件）：

```toml
[automation]
feishu_chat_id = "oc_xxxxxxxx"

[automation.feishu]
app_id = "cli_xxxxxxxx"
app_secret = "xxxxxxxx"
domain = "feishu"
chat_id = "oc_xxxxxxxx"
```

也可用环境变量：`DEEPSEEK_FEISHU_APP_ID`、`DEEPSEEK_FEISHU_APP_SECRET`。旧路径 `automation/feishu.toml` 仍可作为兜底读取。

---

## 三、如何拿到 open_id / chat_id

- **私聊机器人**：首次发消息后，运行长连接桥（见第四节），桥会拒绝未授权聊天并打印 `open_id=ou_...`，复制到 Workbench「接收人 ID」。
- **群聊**：使用 `chat_id`（`oc_...`），需在开放平台开通群机器人权限；群消息默认可要求 `/ds` 前缀（桥接配置）。

---

## 四、手机端对话（长连接桥）

出站投递 **不需要** 公网 URL。要在飞书里 **主动发消息让 Agent 执行**，需要 Node 长连接桥：

```bash
# 在项目根目录
bash scripts/start-feishu-bridge.sh
```

首次使用：

1. 进入 `docs/CodeWhale-main/integrations/feishu-bridge`，`npm install`。
2. 复制 `.env.example` 为 `.env`，填入与 `feishu.toml` 相同的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`。
3. 设置 `DEEPSEEK_RUNTIME_URL=http://127.0.0.1:<你的端口>`（与 Workbench「基础」端口一致）。
4. 设置 `DEEPSEEK_RUNTIME_TOKEN`（Workbench 设置里可见，或 `~/.deepseek/runtime.token`）。
5. 首次配对可设 `DEEPSEEK_ALLOW_UNLISTED=true`，拿到 open_id 后写入 `DEEPSEEK_CHAT_ALLOWLIST` 并关闭。

桥接说明详见：`docs/CodeWhale-main/integrations/feishu-bridge/README.md`。

---

## 五、定时任务发到飞书

1. 完成第二节凭证与接收人 ID。
2. 在聊天输入框旁点 **自动化**，输入例如：

   > 每天十点把小米股票发到飞书

3. 或在设置 → Claw 查看已创建任务；投递方式为 `delivery.mode=feishu`。

邮件投递仍在 `~/.deepseek/config.toml` 的 `[automation] mail_to`；说「发到邮箱」则走邮件。

---

## 六、可选：Webhook 密钥

若暴露入站 URL（`POST /v1/automation/feishu/inbound`），可设置：

```bash
export DEEPSEEK_FEISHU_WEBHOOK_SECRET='随机长字符串'
```

重启 Runtime；桥接请求需带 `Authorization: Bearer <secret>` 或头 `X-Deepseek-Feishu-Secret`。

Workbench **设置 → Claw → 飞书** 中的「Webhook 密钥」需与上述环境变量一致（保存后请重启 Runtime 进程）。

---

## 七、故障排查

| 现象 | 处理 |
|------|------|
| 测试发送 401/502 | 检查 `feishu.toml`、应用是否发布、机器人是否已加好友 |
| 收不到定时结果 | 确认任务 `delivery.mode=feishu` 且 `to` 为正确 open_id |
| 桥接无响应 | `npm install`、`.env` 中 Runtime URL/Token、飞书应用长连接权限 |
| Runtime 未连接 | Workbench → 设置 → 基础，确认端口与 `deepseek serve --http` |
