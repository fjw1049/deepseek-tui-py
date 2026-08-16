# 安全加固批次：用户可感知的行为变化（Release Note）

> 日期：2026-08-16
> 背景：`docs/SECURITY_FIX_PLAN_2026-08-14.md` 第一批/第三批修复落地。
> 本文只列**用户可感知的行为变化**与迁移方法，不重复方案细节。

---

## 1. Shell / MCP 子进程不再继承密钥类环境变量（C5）

模型发起的 Shell 命令和 MCP stdio server 的子进程环境现在经过清洗：
名字以 `_API_KEY` / `_TOKEN` / `_SECRET` / `_PASSWORD` / `_ACCESS_KEY` /
`_ACCESS_KEY_ID` / `_PRIVATE_KEY` / `_CREDENTIALS` 结尾（大小写不敏感）的
变量不再传入子进程。

**影响**：依赖「父进程环境里恰好有 `GITHUB_TOKEN` / `AWS_*`」的 MCP server
或 Shell 工作流会静默失效。

**迁移**：在 `mcp.json` 的 `env` 里显式声明该变量（显式声明的条目原样透传）；
Shell 场景在命令里显式读取密钥管理工具（如 `op read`、`pass`），而不是依赖
继承的环境。

配套变化：`printenv` / `set` 移出免审批白名单，`find -exec/-delete` 升档为
需要审批，管道按最坏一段定级（`cat f | nc host port` 不再算只读）。

## 2. 飞书 inbound 机器人默认只读（A3/B3）

`/v1/automation/feishu/inbound` 触发的 agent 会话改为
`auto_approve=False`：写文件、Shell 等受控工具会进入审批，而 inbound 线程
没有审批通道，实际上等于**默认只读**（读类工具不受影响）。

cron / 定时自动化管线不受影响，仍以 `auto_approve=True` 无人值守运行——
那是用户在配置里显式声明的自动化通道。

**迁移**：如确需飞书机器人执行写操作，目前只能接受审批挂起到超时的行为；
正式的「无人值守写权限」开关待产品拍板（方案 A3 问题 2）。

另：feishu webhook 未配置 `DEEPSEEK_FEISHU_WEBHOOK_SECRET` 时 inbound 一律
401（原来是不校验放行）；`*-test-send` 的目标锁定为配置里的默认
`chat_id` / `mail_to`，请求体无法再改投递目标。

## 3. 项目级配置不再能覆盖安全键（A1/A4）

仓库里的 `deepseek-tui.toml` / `.deepseek-tui.toml` / `.deepseek/config.toml`
/ `.env` 不再能设置：`approval_policy`、`sandbox_mode`、`allow_shell`、
`api_key`、`base_url`、`hooks`、`profile`、`features.automations`、
`providers.*.api_key/base_url/extra_headers/extra_body`，以及
`managed_config_path` 等加载位置指针。被忽略的键会在日志里打 warning。

**影响**：此前在项目配置里设置上述键的工作流会失效（这正是修复目的）。
模型、locale、instructions、providers 的 `model` 等非安全键不受影响。

## 4. `task_create` 不再允许模型自提权（A3）

工具 schema 删除 `mode` / `allow_shell`；`auto_approve` 继承当前会话档位
（不再默认 `True`）；`workspace` 必须落在当前会话工作区内。

**影响**：此前依赖 `task_create(mode="yolo", allow_shell=true)` 的提示词
工作流不再生效；非 auto 会话中创建的后台任务会把受控工具审批桥回主会话，
无桥接时拒绝。

## 5. 其他

- `fetch_url` 拒绝回环 / RFC1918 / 链路本地地址（含 169.254.169.254），
  重定向逐跳复查；抓取本机/内网地址的用法不再可用。
- `write_file` / `edit_file` 拒绝写 `.env`、`id_rsa`、`*.pem`、
  `.git/hooks/*` 等敏感路径（读侧名单不变）。
- `deepseek-tui serve --insecure` 只允许绑定回环地址；legacy app-server
  默认启用 bearer token 认证（token 写入 `~/.deepseek/runtime.token`）。
- 审批「本会话记住」的指纹现在包含命令 flag（`git push` ≠
  `git push --force`）和 cron 任务内容，同类授权范围收窄，可能被多问几次。

## 已知残留（已记录，后续批次处理）

- 主路径 `approval_policy=auto` 仍推导 `trust_mode=True`（A2 待产品拍板，
  见 `tools/runtime.py` 注释；子代理路径已解耦）。
- `fetch_url` 的 DNS 检查与连接分离，存在理论上的 rebinding 窗口。
