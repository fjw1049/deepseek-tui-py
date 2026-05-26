# Workbench 待办 backlog

> 与 [`WORKBENCH_HANDOVER.md`](./WORKBENCH_HANDOVER.md) 第九节集成债互补。

## P0 — 聊天闭环验证 ✅

- [x] dev / smoke / auth / SSE / interrupt / steer contract
- [x] trust_mode → Engine.tool_context
- [x] steer 插队（`handle.steer` + chat-store）
- [x] on-request 审批 UI 手验清单 → [`WORKBENCH_APPROVAL_MANUAL_TEST.md`](./WORKBENCH_APPROVAL_MANUAL_TEST.md)
- [x] user-input 真 turn 集成测 → `test_turn_user_input_integration.py`

## P1 — GUI 瘦身 ✅（运行时）

- [x] Claw/updater/npm 二进制已删
- [x] 技能扫描目录迁至 `settings.skills.extraDirs`（兼容旧 `claw.skills.extraDirs` JSON）

## P1 — Runtime API ✅

- [x] OpenAPI + contract + CORS + approvals + user-inputs

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

## 集成债 / 文档 ✅

- [x] contract schemas、token 双写防护、header-only auth、since_seq 400
- [x] [`RUNTIME_LEGACY.md`](./RUNTIME_LEGACY.md) legacy 废弃说明
- [x] README 7878/8787 端口说明

## 测试计数

`pytest tests/contract -q` → **49+**（随新增用例更新）
