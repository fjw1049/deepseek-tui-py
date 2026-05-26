# Workbench 待办 backlog

> 与 [`WORKBENCH_HANDOVER.md`](./WORKBENCH_HANDOVER.md) 第九节集成债互补：本节是可批量实现的**任务清单**，不要求按 Stage 顺序逐个完成。

## P0 — 聊天闭环验证 ✅ 2026-05-26

- [x] 本机 `./scripts/dev-workbench.sh` 手动打开 Electron，发一条消息确认 UI 流式回复（用户手验「你好」通过）
- [x] 自动化聊天路径：`./scripts/smoke-workbench-chat.sh`（SSE + turn.completed + agent 回复）
- [x] 带 auth 路径：`./scripts/smoke-workbench-auth.sh`（401 无 Bearer + Bearer 聊天）
- [x] SSE contract：generator 回放 + payload 形状
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
- [ ] on-request 审批 UI 手验（Timeline 点允许/拒绝）— 代码就绪，待本机点一次

## P1 — 性能 / 正确性收尾 ✅ 2026-05-26

- [x] `ensureRuntime` 5s TTL 缓存（`runtime-ready-cache.ts` + vitest）
- [x] `formatRuntimeError` 识别 SSE `runtime_auth_required:` 前缀
- [x] SSE 仅用 `Authorization` header（不再把 token 放进 URL query）
- [x] http_mode 关闭 uvicorn 默认 access log（防 token 进 stderr）
- [x] Settings fingerprint IPC 用 `resolveEffectiveRuntimeToken`

## P2 — 工作台功能

- [x] Diff / 文件预览与 `file_change` item 事件对齐（`file_change_completion_detail` 合成 unified diff）
- [x] `RuntimeDiagnosticsDialog` 展示 Python 版本、`runtime_api` mode（probe 带 Bearer token）
- [ ] 插件市场（`PluginMarketplaceView`）— 可永久 defer
- [ ] `docs/WORKBENCH_ARCHITECTURE.md` 序列图

## P2 — 打包发布

- [ ] electron-builder macOS `.dmg`
- [ ] 安装包内嵌 Python 或 documented venv bootstrap
- [ ] 移除 `electron-updater` / R2 publish 脚本（或 fork 专用 release 流程）

## 集成债 / 文档

- [x] `contracts/sse-event.schema.json` + `errors.schema.json` + `tests/contract/test_contract_schemas.py`
- [ ] Legacy `/legacy` 路由 CHANGELOG 废弃说明
- [ ] **8.token.dual-write**：同一端口只应有一个托管方（GUI spawn 或 CLI，不要并行写 `runtime.token`）；稳态靠 reclaim + 共享 token 文件，见 HANDOVER 原则 B

## 已完成（2026-05-25 — 2026-05-26）

- [x] `runtime_api/` 裸 JSON + SSE + approval bridge + auth
- [x] `serve --http --port 7878 --insecure|--auth-token`
- [x] `thread_manager`：`agent_reasoning`、`title`、HTTP 审批、`tool.input` on item.started
- [x] `tests/contract/` **39** 项通过
- [x] `scripts/smoke-workbench-chat.sh` + `scripts/smoke-workbench-auth.sh`
- [x] `packages/workbench/` fork + Python spawn + auth 链闭环（1609774）
- [x] GUI 安全默认值 + SSE 重连上限（961a36b）
- [x] token 可见性 + Regenerate IPC（91393bb）
- [x] ensureRuntime probe 缓存（c059016）
- [x] `--insecure` 忽略 token 文件 + SSE/diagnostics auth 收尾（Stage 8.4）
- [x] `file_change_completion_detail` + diagnostics probe Bearer
- [x] `scripts/dev-workbench.sh`, `scripts/contract-check.sh`
