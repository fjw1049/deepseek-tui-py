# Workbench 待办 backlog

> 与 [`WORKBENCH_HANDOVER.md`](./WORKBENCH_HANDOVER.md) 第九节集成债互补。

## P0 — 聊天闭环验证 ✅

- [x] dev / smoke / auth / SSE / interrupt / steer contract
- [x] trust_mode → Engine.tool_context
- [x] steer 插队（`handle.steer` + chat-store）
- [x] on-request 审批 UI 手验清单 → [`WORKBENCH_APPROVAL_MANUAL_TEST.md`](./WORKBENCH_APPROVAL_MANUAL_TEST.md)
- [x] user-input 真 turn 集成测 + `GET /v1/user-inputs/pending` 恢复
- [x] `config.approval_policy` → `ExecPolicyEngine`（HTTP + TUI Engine.create）
- [x] 审批 `remember` → `APPROVED_SESSION`
- [x] 子代理 mailbox 持久化 + Timeline 重载

## P1 — GUI 瘦身 ✅（运行时）

- [x] Claw/updater/npm 二进制已删（**Claw 集成仍 defer**）
- [x] 技能扫描目录迁至 `settings.skills.extraDirs`（兼容旧 `claw.skills.extraDirs` JSON）

## P1 — Runtime API ✅

- [x] OpenAPI + contract + CORS + approvals + user-inputs
- [x] `/v1/skills` + `/v1/tasks*` + `/v1/sessions` + export-session（TUI/Workbench 会话统一）

## P2 — 工作台功能 ✅（除 defer）

- [x] Diff / diagnostics / StatusEvent → Timeline system 行
- [x] 侧栏 Fork / Resume / Compact
- [x] [`WORKBENCH_ARCHITECTURE.md`](./WORKBENCH_ARCHITECTURE.md)
- [ ] 插件市场 — defer
- [x] 子代理 Delegate/Fanout Timeline 卡片（`subagent.mailbox` SSE + Workbench 卡片）

## P2 — 打包发布

- [ ] electron-builder `.dmg`
- [ ] 内嵌 Python / bootstrap 文档
- [ ] 专用 release 流程

## P2 — Claw 后台自动化（参考 GUI 同名模块，暂不在 GUI 暴露）

> **当前状态**：`app-settings.ts` 中的 `Claw*` 类型、`settings-store.ts` 的 `mergeClawSettings` /
> `ensureClawChannelWorkspaceRootsExist`、i18n 中 `claw.*` 文案均**保留**作为占位；
> GUI 没有任何组件引用这些文案/字段，用户不可见。Python 后端**完全没有**对应实现。
> 决策：保留前端骨架便于将来对接；不在 Workbench UI 暴露任何 Claw 入口。

参考实现来源：[`docs/DeepSeek-GUI-master`](./DeepSeek-GUI-master) — 同名模块。

要做时按下面顺序推进，每步可独立交付：

- [ ] **后端 Scheduler 内核**：实现 `claw_schedule_list/create/update/delete` 工具 + 持久化（`~/.deepseek/claw/schedules.json`）+ 后台 tick task；让 Engine 在工具白名单里能调用
- [ ] **后端 Webhook 入口**：在 `app_server` 加 `/v1/claw/webhook/{channel_id}` POST 路由，body → 触发指定 channel 的 Engine 一轮 turn；带 token 鉴权
- [ ] **IM Provider 抽象**：定义 `ImProvider` 接口（send/receive/bind），先实现 Feishu（OAuth + 长连接 / event subscription）
- [ ] **Claw Runtime 与前台隔离**：独立 EngineHandle 池，注入 `[Claw managed instructions]` system prompt；保证后台 turn 不污染 Workbench 当前 thread
- [ ] **GUI 暴露**：Settings 加 Claw Tab（启用开关 + 默认 workspace + IM 频道列表 + 定时任务列表）；侧栏新增 Claw Workspaces 区段（`isClawWorkspacePath` 已有过滤逻辑可复用）
- [ ] **i18n 启用**：`claw.*` 文案现成，GUI 暴露时无需翻译工作
- [ ] **Relay 模式（可选）**：内网穿透 / 中转，给 IM 服务器够不到本地的部署场景

**关键决策点**（开工前需确认）：
1. IM provider 是否只做飞书？（参考 GUI 也只有飞书）
2. Scheduler 是 Python 进程内 asyncio task，还是独立 systemd/launchd 守护？
3. 后台 Agent 是否复用 Workbench 同一组 Thread Store，还是另起一套 `claw_threads/`？

**现状残留清单**（保留，不删）：
- [`app-settings.ts`](../packages/workbench/src/shared/app-settings.ts) — `ClawSettingsV1` 等 30+ 类型
- [`settings-store.ts`](../packages/workbench/src/main/settings-store.ts) — 默认值 + 工作目录创建（启动时会建 `~/.deepseekgui/claw/...` 空目录，无害）
- `locales/{en,zh}/{settings,common}.json` — `claw.*` 文案
- [`workspace-path.ts`](../packages/workbench/src/renderer/src/lib/workspace-path.ts) — `isClawWorkspacePath` 用于侧栏过滤

## 集成债 / 文档 ✅

- [x] contract schemas、token 双写防护、header-only auth、since_seq 400
- [x] [`RUNTIME_LEGACY.md`](./RUNTIME_LEGACY.md) legacy 废弃说明
- [x] README 7878/8787 端口说明

## 测试计数

`pytest tests/contract -q` → **69**；TUI smoke：`tests/test_tui_smoke.py`
