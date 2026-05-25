# Workbench 待办 backlog

> 与 [`WORKBENCH_HANDOVER.md`](./WORKBENCH_HANDOVER.md) 第九节集成债互补：本节是可批量实现的**任务清单**，不要求按 Stage 顺序逐个完成。

## P0 — 聊天闭环验证

- [ ] 本机 `./scripts/dev-workbench.sh` 手动打开 Electron，发一条消息确认 UI 流式回复
- [x] 自动化聊天路径：`./scripts/smoke-workbench-chat.sh`（SSE + turn.completed + agent 回复）
- [x] SSE contract：generator 回放 + payload 形状（ASGI httpx 无限流已知限制，不测 HTTP body 读取）
- [x] `interrupt` / `steer` contract 路由测试

## P1 — GUI 瘦身（fork 后批量删） ✅ 2026-05-25

参考 HANDOVER 5.7，Claw/updater/npm 二进制 **已从 fork 删除**（settings 里保留 disabled 默认以兼容旧 JSON）。

| 删除目标 | 状态 |
|---------|------|
| `claw-runtime.ts`, `claw-schedule-*`, `SidebarClaw*` | ✅ 已删 |
| `deepseek-updater.ts`, `gui-updater.ts` | ✅ 已删 |
| `resolve-deepseek-binary.ts` | ✅ 已删 |
| `package.json` → `deepseek-tui` npm 依赖 | ✅ 已删 |
| Renderer Claw 入口 | ✅ 已删 |

## P1 — Runtime API 补全

- [x] OpenAPI 覆盖第十节 12+ endpoint（`contracts/runtime-api.openapi.yaml`）
- [x] `POST /v1/user-inputs/{id}` 404 contract 测试
- [x] 审批挂起：`ApprovalBridge.register` → POST allow 集成测试
- [x] CORS middleware + `--cors-origin` CLI + contract 测试
- [ ] user-input 真实挂起集成测试（需 mock `UserInputRequiredEvent` + active engine）

## P2 — 工作台功能

- [ ] Diff / 文件预览与 `file_change` item 事件对齐
- [ ] `RuntimeDiagnosticsDialog` 展示 Python 版本、`runtime_api` mode
- [ ] 插件市场（`PluginMarketplaceView`）— 可永久 defer
- [ ] `docs/WORKBENCH_ARCHITECTURE.md` 序列图

## P2 — 打包发布

- [ ] electron-builder macOS `.dmg`
- [ ] 安装包内嵌 Python 或 documented venv bootstrap
- [ ] 移除 `electron-updater` / R2 publish 脚本（或 fork 专用 release 流程）

## 已完成（2026-05-25）

- [x] `runtime_api/` 裸 JSON + SSE + approval bridge + auth
- [x] `serve --http --port 7878 --insecure|--auth-token`
- [x] `thread_manager`：`agent_reasoning`、`title`、HTTP 审批
- [x] `thread_manager`：`TurnCompleteEvent` usage 字段映射（`input_tokens`/`output_tokens` → JSON `prompt_tokens`/`completion_tokens`；修复 turn 永久 `in_progress`）
- [x] HTTP smoke：`POST /v1/threads` + `POST .../turns` + poll `GET .../threads/{id}` → `completed` + agent 回复（~5s）
- [x] `tests/contract/` **18** 项通过
- [x] `scripts/smoke-workbench-chat.sh` SSE 聊天路径 smoke
- [x] OpenAPI 12+ paths、CORS、`--cors-origin`
- [x] Claw/updater/npm 二进制从 `packages/workbench` 删除
- [x] `packages/workbench/` fork + `resolve-python-runtime.ts`
- [x] `deepseek-process.ts` / `deepseek-config.ts` → Python spawn
- [x] `scripts/dev-workbench.sh`, `scripts/contract-check.sh`
- [x] `contracts/runtime-api.openapi.yaml` 初稿
