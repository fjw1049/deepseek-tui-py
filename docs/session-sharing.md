# 会话分享与跨设备恢复

日常操作只有两步：公司电脑点击「分享 → 复制链接」，家里打开链接后点击「在应用中继续 → 继续此对话」。无需填写服务地址或密钥。网页展示只读对话；每次继续都会创建独立的本地副本，原电脑无需保持开机。

桌面安装包注册 `deepseek-gui://share?url=...` 链接协议。需要安装新版客户端才能从网页唤起；开发模式不修改系统协议注册，可在应用中点击「分享 → 打开分享」粘贴链接。打开链接只预览，不会自动导入或执行任务。

## 默认托管服务与验收状态

应用默认连接 `https://deepseek-workbench-shares.major-emu-7913.chatgpt.site`，无需配置。源码位于 `services/session-shares`。使用 R2 存储快照、D1 保存有效期、撤销凭据哈希和上传额度。站点已部署并设为公开访问。

**2026-09-25 交付验收：**本地 Worker 的真实 HTTP 上传、读取、浏览器页面、跨用户目录恢复和撤销均通过。线上部署状态为 succeeded，但从当前电脑访问 `/health` 和上传接口被平台 Cloudflare 返回 403，因此线上跨设备链路尚未验收通过，不能宣称功能已完整交付。需要可从使用者网络访问的托管入口。

默认服务每份快照最大 8 MiB，每个出口 IP 每日最多 30 次上传，全站每日最多 1000 次。失败上传也计入额度。撤销凭据按链接独立生成，仅保存在创建电脑的 `shares/<token>.json`，不包含在分享 URL 或快照中；服务端只存哈希。收到链接的人不能撤销。

链接到期立即拒绝访问；在后续创建分享或访问到期链接时分批清理过期数据，不承诺精确到期时物理删除。快照不做端到端加密，包含会话中持久化的工具内容和附件；拿到链接的人能读取完整快照。

## 可选：自行部署 FastAPI 服务

分享服务是独立的 FastAPI 应用，不运行模型或工具，也不需要暴露桌面端 Runtime。服务代码随本项目提供，使用项目的 Python 环境：

```sh
# 首次生成一个随机上传密钥，保存到服务器的环境配置中
python -c 'import secrets; print(secrets.token_urlsafe(32))'

export DEEPSEEK_SHARE_UPLOAD_KEY='<上面生成的密钥>'
export DEEPSEEK_SHARE_DIR='/srv/deepseek-shares'
python -m uvicorn deepseek_tui.server.share_service:create_app \
  --factory --host 127.0.0.1 --port 8787 --no-access-log
```

将自己的 HTTPS 域名反向代理到此端口。保留整个路径，不添加 URL 前缀；代理请求体上限设为至少 33 MiB、超时至少 60 秒。数据目录需要持久化和仅服务账号可读。上传密钥至少 24 个字符，不要提交到代码仓库。不要在代理访问日志中记录带分享令牌的 URL。

维护者只需在需要创建链接的电脑上，通过「设置 → 数据 → 高级：自行部署分享服务」一次性配置服务地址和管理密钥。接收电脑从链接自动识别服务地址，无需任何分享服务配置；读取链接不会发送本机保存的管理密钥。配置存放在用户数据目录的 `sharing.json`，不随会话快照导出。远程服务要求 HTTPS；本地测试允许 `http://127.0.0.1:8787`。

这是一套适合个人或可信团队的独立服务：持链接者可读取该快照，持上传密钥者可以创建分享，并撤销已知链接。当前没有账号隔离、私有账号链接或端到端加密。快照在服务端以 JSON 保存。过期访问返回 410 并清理文件；未再次访问的过期文件可由服务器维护任务清理。

## 使用

1. 公司电脑：结束当前轮执行，点击「分享 → 复制链接」。自动生成有效期 7 天的链接并复制。
2. 家里电脑：打开网页链接，点击「在应用中继续」。应用显示预览，点击「继续此对话」。
3. 仅继续聊天时，应用自动创建独立的空工作目录，无需选择项目。
4. 需要操作已有本地项目，可展开「需要操作本地项目？」选择文件夹。
5. 需要携带代码修改，分享前在「更多选项」里勾选。恢复时会在确有需要时弹出项目选择器。
6. 当前链接可在分享弹窗内撤销；关闭客户端后，已知链接仍可通过撤销 API 管理。撤销不能收回已导入的副本。

默认地址已内置；连接失败会明确报错，不要求普通用户填写服务器资料。代码文件与运行环境的迁移仍受下述限制。

## 恢复范围

- 保留持久化的完整聊天、工具记录、上下文压缩快照、目标状态以及引用的图片附件。
- 为本地会话、轮次和记录生成新 ID。历史命令不会自动重新运行。
- 自动批准、信任权限、原会话系统提示覆盖、模型密钥和插件登录状态不从原会话复制。
- 首次加载模型上下文时加入迁移提示，说明新工作目录及历史结果的来源。
- 运行中的终端、子任务、待批准动作和远端进程不迁移。依赖环境需要在目标电脑准备好。
- 默认托管服务总请求上限 8 MiB；自建 FastAPI 快照上限 32 MiB，项目原始文件总量上限 16 MiB。缺失图片、格式版本不支持或数据损坏会明确报错。

## 携带代码修改

选择项目修改时，源工作目录必须是 Git 仓库根目录。快照包含 HEAD 提交号、相对 HEAD 的文件修改/删除/可执行位，以及未被 Git 忽略的新增文件。忽略文件不随新增文件打包；已经被 Git 跟踪的文件仍会包含。分享前检查项目中是否有不适合传出的内容。

目标电脑选择的仓库必须已经拥有该基准提交，可先通过正常的 Git fetch 获取。当前不会通过链接传输完整 Git 仓库或未推送的基准提交。

恢复会在所选仓库旁创建 `<项目名>-shared-<随机标识>` 的 detached worktree，并让新会话使用它。所选仓库的工作目录和索引保持不变。恢复后的修改可以正常提交；完成后可通过 Git 管理或移除该 worktree。

修改中的符号链接、Git 子模块和路径越界不支持。恢复失败会清理新建 worktree。未勾选携带项目文件时，只恢复会话，需自行确保目标文件与历史上下文一致。

## 接口

本地 Runtime（沿用 Runtime 的认证）：

- `GET/PUT /v1/sharing/settings`：读取非敏感配置 / 保存地址与上传密钥。
- `POST /v1/sharing/shares`：`thread_id`、`include_project`、`expires_in_days`。
- `POST /v1/sharing/preview`：`url`，返回摘要、最近消息及文件清单。
- `POST /v1/sharing/restore`：`url`、`workspace`、`restore_project`，返回新会话。
- `POST /v1/sharing/revoke`：`url`。

分享服务：`POST /v1/shares`、`GET/DELETE /v1/shares/{token}`、`GET /s/{token}`。自建 FastAPI 的创建和删除要求 Bearer 上传密钥；默认托管服务创建不需要密钥，删除需要该链接独立的 Bearer 撤销凭据。读取凭随机链接令牌授权。上传和撤销仅使用维护者配置的地址。读取使用用户提供的 HTTPS 分享链接（本地测试允许 loopback HTTP），不携带上传凭据，不跟随远端重定向。

## 验证

```sh
DEEPSEEK_API_KEY=test-only-not-a-real-key .venv/bin/pytest -q tests/contract/test_session_sharing.py tests/contract/test_session_import.py tests/contract/test_session_hydration.py
cd packages/workbench
npm test -- src/renderer/src/components/SessionSharing.test.ts
```


默认托管服务本地验收（先安装 `services/session-shares` 的依赖并启动 Wrangler）：

```sh
cd services/session-shares
npm run db:generate  # 仅变更 schema 时生成新的迁移
npx wrangler d1 migrations apply session-shares --local
npx wrangler dev --ip 127.0.0.1 --port 8791
# 另一终端
npm test
# 仓库根目录：测试数据为临时目录内的合成会话，不使用真实用户会话
DEEPSEEK_API_KEY=test-only-not-a-real-key DEEPSEEK_SHARE_TEST_ORIGIN=http://127.0.0.1:8791 .venv/bin/pytest -q tests/contract/test_session_sharing.py -k real_http_share
```
