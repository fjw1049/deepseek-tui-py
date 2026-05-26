# DeepSeek Workbench — 接手指南 / WORKBENCH HANDOVER

> 本文档是 **Stage 8+（桌面工作台）** 的单一规划真相源。读完即可知道：要建什么、文件放哪、先后次序、验收标准。
>
> **前置阅读**：[`docs/HANDOVER.md`](./HANDOVER.md)（Python 运行时/TUI parity 已完成部分）、[`docs/DeepSeek-TUI-main/docs/RUNTIME_API.md`](./DeepSeek-TUI-main/docs/RUNTIME_API.md)（HTTP 契约参考）、[`docs/DeepSeek-GUI-master/`](./DeepSeek-GUI-master/)（**只读** UI/托管参考，不直接依赖其 Rust 二进制）。
>
> 最后更新：2026-05-25 — 初版全量文件规划（未开始实现）。

---

## 一、项目是什么

**源（能力）**：本仓库 `src/deepseek_tui/` — 约 4.5 万行 Python，Engine + 70+ 工具 + Textual TUI + 部分 App Server（1323 pytest passed）。

**源（参考 UI）**：`docs/DeepSeek-GUI-master/` — Electron + React 工作台，通过 `deepseek serve --http` 接 Rust Runtime。**我们只借鉴产品形态与 IPC 模式，运行时换成 Python。**

**目标**：新增 **DeepSeek Workbench** — 本地桌面应用，让用户**不必进终端**也能完成：选工作区 → 多会话聊天 → 流式看推理/工具/改动 → 审批敏感操作 → 审查 diff。

**不是目标（v1 不做）**：

- 不重写 Engine / Tools
- 不嵌入 TUI 终端输出解析
- 不复刻 Claw / 飞书 / GUI 自更新 / npm 下载 Rust 二进制
- 不追求与 DeepSeek-GUI 像素级一致

---

## 二、关键决策（拍板项 — 实现前勿改）

| 决策 | 选择 | 理由 |
|------|------|------|
| 产品名 | **DeepSeek Workbench** | 与 `deepseek-tui` CLI 区分 |
| 集成边界 | **HTTP + SSE**（`/v1/*`） | 与 Rust/GUI 参考一致；GUI 无 Node 直连 Engine |
| Python 入口 | `deepseek-tui serve --http` | 对齐参考 GUI 的 `serve --http` 语义 |
| CLI 别名 | 可选 `deepseek` → 同入口 | 方便 GUI 默认 binary 名 |
| 默认端口 | **7878** | 与 RUNTIME_API / 参考 GUI 一致 |
| 桌面栈 | **Electron 34 + electron-vite + React 19** | 参考已验证 SSE 代理 / 子进程托管 |
| 前端状态 | **Zustand** | 与参考一致 |
| API 契约 | **`contracts/runtime-api.openapi.yaml`** 单一真相源 | 防 `{ok:true}` 包装漂移 |
| 旧 App Server 路由 | **`/legacy/*` 或根路径保留 1 个 minor** | 不 break 已有 Python 集成测试；GUI 只认 parity 路由 |
| TUI | **保留** | Power user / SSH 场景 |
| 真实 API 测试 | 契约测试 + 可选 live marker | 延续 HANDOVER 原则 A |
| 参考 GUI 代码 | **fork 后瘦身**，非 submodule | 去 Claw/updater/deepseek-tui npm |

---

## 三、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  packages/workbench  (Electron)                              │
│  Renderer ←→ Preload (dsApi) ←→ Main (spawn/proxy/IPC)      │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP + SSE 127.0.0.1:7878
┌───────────────────────────▼─────────────────────────────────┐
│  src/deepseek_tui/app_server/runtime_api/  (新建)            │
│  FastAPI Rust-parity 路由 + Auth + SSE live + Approval 挂起   │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  RuntimeThreadManager + Engine + Tools  (已有，小改)         │
└─────────────────────────────────────────────────────────────┘
```

**数据流**：用户 → React → `window.dsApi` → Main `runtimeRequest` / SSE → Python `runtime_api` → `RuntimeThreadManager` → `Engine`。

---

## 四、当前状态 vs 目标状态

### 4.1 Runtime API（Python 后端）

| 能力 | 现在 | Stage 8 目标 |
|------|------|--------------|
| 响应形状 | `{ok, threads}` 包装 | 裸 `ThreadRecord[]` / `ThreadDetail` / `StartTurnResponse` |
| Health | `/healthz` | `/health` + alias |
| SSE | `/events` JSON；`/events/stream` 3s 窗口 | `/v1/threads/{id}/events` 长连接 + backlog + live |
| 审批 | 内部 auto approve/deny | `approval.required` 挂起 + `POST /v1/approvals/{id}` |
| Auth | 无 | 可选 Bearer / `?token=` |
| 推理流 | 无 `agent_reasoning` | `ThinkingDeltaEvent` → item + delta |
| CLI | `serve --port 8787` | `serve --http --port 7878 --auth-token ...` |
| 契约测试 | 无 | `tests/contract/` 全绿 |

### 4.2 桌面 GUI

| 能力 | 现在 | Stage 8 目标 |
|------|------|--------------|
| Electron 应用 | 无 | `packages/workbench/` 可 dev + 可打包 |
| 聊天闭环 | 无 | 发消息 / SSE / 审批 / interrupt |
| Diff 审查 | TUI 有 | Workbench 面板 |
| 设置 | TUI + config.toml | GUI 设置页 + 同步 config |

---

## 五、仓库目录规划（全量文件清单）

> 标记：**[N]** 新建 · **[M]** 修改 · **[K]** 从参考 GUI 移植/瘦身 · **[R]** 保留不动 · **[D]** 日后废弃

### 5.1 契约层 `contracts/`

```
contracts/
├── runtime-api.openapi.yaml          [N] 主契约：health/threads/turns/events/approvals
├── sse-event.schema.json             [N] SSE data: { seq, event, payload, ... }
├── errors.schema.json                [N] 4xx/5xx 统一 error body
└── README.md                         [N] 如何改契约 → 跑 contract 测试
```

### 5.2 Python Runtime API `src/deepseek_tui/app_server/`

```
app_server/
├── __init__.py                       [M] 导出 run_http_runtime / build_runtime_app
├── server.py                         [M] 双 app：legacy + runtime_api 挂载
├── legacy/                           [N] 现有 routes/runtime 迁入（可选，或同文件标记 deprecated）
│   ├── routes.py                     [M] 原 /thread /prompt 等
│   └── runtime.py                    [R]
├── runtime_api/                      [N] ★ GUI 唯一 HTTP 面
│   ├── __init__.py
│   ├── app.py                        [N] build_runtime_fastapi_app()
│   ├── auth.py                       [N] Bearer + query token middleware
│   ├── errors.py                     [N] ApiError → JSONResponse
│   ├── responses.py                  [N] 裸 JSON 响应 helper
│   ├── deps.py                       [N] get_thread_manager / get_settings
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── health.py                 [N] GET /health
│   │   ├── threads.py                [N] CRUD/list/summary/fork/resume
│   │   ├── turns.py                  [N] start/steer/interrupt/compact
│   │   ├── events.py                 [N] GET .../events SSE (replay+live)
│   │   ├── approvals.py              [N] POST /v1/approvals/{id}
│   │   ├── user_inputs.py            [N] POST /v1/user-input(s)/{id}  (P1)
│   │   ├── workspace.py              [N] GET /v1/workspace/status
│   │   ├── skills.py                 [N] GET /v1/skills  (P2)
│   │   └── tasks.py                  [N] GET /v1/tasks... (P2)
│   ├── sse.py                        [N] runtime_event_payload + sse_json framing
│   └── approval_bridge.py            [N] pending map + Engine 挂起/恢复
├── runtime_threads.py                [M] + title 字段；UpdateThreadRequest 扩展
├── thread_manager.py                 [M] 审批挂起；ThinkingDelta；subscribe 接 SSE
├── broadcast.py                      [R]
├── engine_bridge.py                  [R]
└── sse.py                            [M] 或合并进 runtime_api/sse.py
```

### 5.3 CLI `src/deepseek_tui/cli/`

```
cli/
└── app.py                            [M]
    ├── serve 增加 --http, --auth-token, --insecure, --cors-origin
    ├── 默认 port 7878（breaking：文档说明从 8787 迁移）
    └── 可选顶层命令 alias（若加 deepseek 入口见 pyproject）
```

### 5.4 配置与路径

```
config/models.py                        [M] RuntimeServerConfig: port/auth/cors
config/paths.py                         [M] workbench 数据目录说明（文档级）
pyproject.toml                          [M] optional [workbench] / scripts 文档
```

### 5.5 桌面应用 `packages/workbench/`

```
packages/workbench/
├── package.json                        [N]
├── electron.vite.config.ts             [K] 从参考 GUI 改 productName
├── electron-builder.config.cjs         [K] 瘦身：无 deepseek-tui npm
├── tsconfig.json                       [K]
├── tsconfig.node.json                  [K]
├── tsconfig.web.json                   [K]
├── tailwind.config.js                  [K]
├── postcss.config.js                   [K]
├── eslint.config.js                    [K]
├── vitest.config.ts                    [K]
│
├── src/
│   ├── main/
│   │   ├── index.ts                    [K] 改 spawn → deepseek-tui serve --http
│   │   ├── runtime-process.ts          [K] 原 deepseek-process.ts，去 npm 安装器
│   │   ├── settings-store.ts           [K] 去 Claw/deepseek-updater 字段
│   │   ├── ipc/
│   │   │   ├── register-app-ipc-handlers.ts  [K] 去 Claw/飞书 handlers
│   │   │   └── app-ipc-schemas.ts      [K]
│   │   ├── services/
│   │   │   ├── terminal-service.ts     [P2]
│   │   │   ├── git-service.ts          [P2]
│   │   │   └── workspace-service.ts    [K]
│   │   └── logger.ts                   [K]
│   │
│   ├── preload/
│   │   ├── index.ts                    [K] dsApi（可保留 dsGui 别名）
│   │   └── index.d.ts                  [K]
│   │
│   ├── renderer/
│   │   ├── main.tsx                    [K]
│   │   ├── App.tsx                     [K]
│   │   ├── AppShell.tsx                [K]
│   │   ├── index.css                   [K]
│   │   ├── agent/
│   │   │   ├── types.ts                [K]
│   │   │   ├── registry.ts             [K] PythonRuntimeProvider
│   │   │   └── python-runtime.ts       [N] 原 deepseek-runtime.ts 改名
│   │   ├── store/
│   │   │   ├── chat-store.ts           [K] 去 Claw actions
│   │   │   ├── chat-store-types.ts     [K]
│   │   │   ├── chat-store-helpers.ts   [K]
│   │   │   ├── chat-store-runtime-helpers.ts [K]
│   │   │   ├── chat-store-app-actions.ts     [K]
│   │   │   └── chat-store-schedulers.ts      [K]
│   │   ├── components/               [K] v1 子集见 5.6
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── locales/en|zh/            [K] 去 Claw 文案
│   │   └── i18n.ts                   [K]
│   │
│   └── shared/
│       ├── ds-api.ts                   [K] 原 ds-gui-api.ts，删 Claw 类型
│       ├── app-settings.ts             [K] 瘦身
│       ├── openai-compat-url.ts      [K]
│       └── generated/                  [N] OpenAPI codegen（可选 hand-written v1）
│           └── runtime-api.types.ts
│
├── scripts/
│   └── postinstall.cjs                 [K] 仅 electron 依赖，无 deepseek 二进制
│
└── tests/
    ├── agent/python-runtime.test.ts    [N] mock dsApi
    └── main/runtime-process.test.ts    [N]
```

### 5.6 Renderer 组件 v1 范围（从参考 GUI 移植）

| 组件 | 文件 | v1 |
|------|------|-----|
| 连接状态 | `ConnectionStatusBar.tsx` | ✅ |
| 侧栏 | `chat/Sidebar.tsx`, `SidebarProjectsSection.tsx` | ✅ |
| 时间线 | `chat/MessageTimeline.tsx`, `StreamdownAssistant.tsx` | ✅ |
| 输入 | `chat/FloatingComposer.tsx` | ✅ |
| 顶栏 | `chat/WorkbenchTopBar.tsx` | ✅ |
| Diff | `DiffView.tsx`, `ChangeInspector.tsx` | ✅ |
| 文件预览 | `WorkspaceFilePreviewPanel.tsx` | ✅ |
| 设置 | `SettingsView.tsx` | ✅ 无 Claw  Tab |
| 首次引导 | `InitialSetupDialog.tsx` | ✅ |
| 诊断 | `RuntimeDiagnosticsDialog.tsx` | ✅ |
| 终端 | `AppTerminalPanel.tsx` | P2 |
| Git | `GitBranchPicker.tsx` | P2 |
| Claw | `SidebarClaw*.tsx` | ❌ 不做 |
| 插件市场 | `PluginMarketplaceView.tsx` | P2 |

### 5.7 测试 `tests/`

```
tests/
├── contract/                           [N] ★ 必须先于 GUI 绿
│   ├── conftest.py                     [N] ASGI app fixture
│   ├── test_health.py
│   ├── test_threads_crud.py
│   ├── test_turns_lifecycle.py
│   ├── test_events_sse.py              [N] httpx SSE client
│   ├── test_approvals.py
│   └── test_auth.py
├── integration/
│   └── test_workbench_smoke.py         [N] P2: 起 runtime + 一条 turn（可选）
└── parity/                             [R] 现有 1323 测试不动
```

### 5.8 脚本与文档

```
scripts/
├── dev-workbench.sh                    [N] 并行：runtime + electron-vite dev
├── contract-check.sh                   [N] openapi diff + pytest tests/contract
└── package-workbench-mac.sh            [N] P2

docs/
├── WORKBENCH_HANDOVER.md               [N] ← 本文档
├── WORKBENCH_ARCHITECTURE.md           [N] Sprint 0 产出：序列图 + 模块图
├── RUNTIME_API_PY.md                   [N] 从 openapi 生成或手写 Python 版
└── HANDOVER.md                         [M] 第三节追加 Stage 8 指针

README.md                               [M] Workbench 快速开始一节
```

### 5.9 根目录 monorepo（可选渐进）

**Phase A（推荐先做）**：不移动 `src/deepseek_tui`，仅新增 `packages/workbench/` + `contracts/`。

**Phase B（整理）**：`packages/runtime` symlink → `src/deepseek_tui`；npm workspace root `package.json`。

---

## 六、Stage 8 路线图（实现顺序）

### Stage 8.0 — 契约与脚手架（3–4 天） ✅ 部分完成

| 任务 | 文件 | 验收 | 状态 |
|------|------|------|------|
| OpenAPI 初稿 | `contracts/runtime-api.openapi.yaml` | 覆盖 GUI v1 用到的 15 个 endpoint | ✅ 12+ paths |
| 契约测试骨架 | `tests/contract/conftest.py` | `pytest tests/contract` 可收集 | ✅ |
| Workbench 空壳 | `packages/workbench/package.json` + `src/main/index.ts` | `npm run dev` 开空窗 | ✅ fork 完成 |
| 开发脚本 | `scripts/dev-workbench.sh` | 一条命令起双进程 | ✅ |
| 架构文档 | `docs/WORKBENCH_ARCHITECTURE.md` | 序列图 + 模块职责 | ⬜ backlog |

### Stage 8.1 — Runtime API P0（5–7 天） ✅ 完成

| 任务 | 文件 | 验收 | 状态 |
|------|------|------|------|
| 裸 JSON 路由 | `runtime_api/routes.py` | contract tests 全绿 | ✅ |
| SSE 长连接 | `runtime_api/sse.py` | curl -N 持续收 event | ✅；contract 测 generator + payload（ASGI 无限流限制） |
| 审批挂起 | `approval_bridge.py` | 无 token 时 pending 直到 POST | ✅ |
| Health + CLI | `cli/app.py`, `server.py` | `serve --http --port 7878` | ✅ |
| 推理 item | `thread_manager.py` | SSE 有 agent_reasoning delta | ✅ |

### Stage 8.2 — Electron 托管（4–5 天） ✅ 完成

| 任务 | 文件 | 验收 | 状态 |
|------|------|------|------|
| Spawn Python | `deepseek-process.ts`, `resolve-python-runtime.ts` | GUI 自动起 runtime | ✅ |
| Config 同步 | `deepseek-config.ts` | Settings 改 key/policy 写 config.toml | ✅ |
| HTTP/SSE 代理 | `main/index.ts` | 与参考 GUI 同 IPC 名 | ✅ 沿用参考实现 |
| Preload API | `preload/index.ts` | `window.dsGui` 类型完整 | ✅ 沿用参考实现 |
| 设置存储 | `settings-store.ts` | patch 后 restart runtime | ✅ 沿用参考实现 |
| GUI 瘦身 | fork 删 Claw/updater | 无 npm 二进制依赖 | ✅ |
| 端到端 smoke | `scripts/smoke-workbench-chat.sh` | SSE turn.completed + 回复 | ✅ 自动化 |
| Electron UI smoke | `./scripts/dev-workbench.sh` | 手动发一条看 Timeline 流式 | ⬜ 待本机手验 |

### Stage 8.3 — 聊天闭环（5–7 天） ✅ 2026-05-26

| 任务 | 文件 | 验收 | 状态 |
|------|------|------|------|
| Provider | `deepseek-runtime.ts` | connect/list/send/SSE | ✅ |
| Store | `chat-store.ts` | 多会话 + 流式 blocks | ✅ |
| UI | Timeline + Composer + Sidebar | 手动：发一条收到流式回复 | ✅ 用户手验 |
| 审批 UI | Timeline approval 块 | on-request 策略下可点允许 | ⬜ 待手验 |

### Stage 8.4 — 工作台（5 天） 🔄 进行中

| 任务 | 文件 | 验收 | 状态 |
|------|------|------|------|
| Diff | `runtime_threads.py` + `ChangeInspector` | `edit_file`/`write_file`/`apply_patch` 完成时有 unified diff | ✅ contract |
| 设置/诊断 | `RuntimeDiagnosticsDialog` + probe auth | `/v1/workspace/status` 在 Bearer 下返回 python_version | ✅ |
| 契约 schema | `contracts/sse-event.schema.json` | contract 测试锁定 payload 形状 | ✅ |

### Stage 8.5 — 打包（5 天，P2）

| 任务 | 验收 |
|------|------|
| electron-builder | macOS `.dmg` 可安装 |
| 嵌入/文档化 Python | 新机器 README 可跑通 |

---

## 七、工作方法论（继承 HANDOVER + Workbench 补充）

### 7.1 继承 HANDOVER 的原则 A / B

- **A**：`runtime_api` + SSE + approval 路径必须有 **contract 测试**；可选 `@pytest.mark.live` 跑真 LLM 一条 turn。
- **B**：`runtime_api` 每个 route 必须被 **contract 测试或 GUI smoke** 触发；Electron 每个 IPC 必须有 **preload 类型 + 至少一个调用方**。

### 7.2 Workbench 特有规则

1. **契约先行**：改 API 先改 `contracts/*.yaml`，再改 Python，再改 TS；顺序反了不许 merge。
2. **参考 GUI 只抄模式，不抄依赖**：禁止引入 `deepseek-tui` npm 包；spawn 本机 venv 的 `deepseek-tui`。
3. **瘦身清单**：从参考 fork 时删除 Claw、gui-updater、deepseek-updater、飞书 OAuth、R2 publish 脚本。
4. **双入口共存**：TUI 与 Workbench 可同时跑，但**不要**共享同一 runtime 端口（除非用户刻意）。
5. **Legacy 路由**：旧 `{ok:true}` 响应保留在 non-/v1 或 `/legacy` 至少一个 minor 版本，CHANGELOG 声明废弃。

### 7.3 每个子 Stage 的提交模板

```
Stage 8.X: <summary>

## Contract / GUI impact
- OpenAPI: <paths changed>
- GUI: <screens affected>

## Files
- <path>: <what>

## Verification
- pytest tests/contract -q  → N passed
- npm run typecheck (workbench) → ok
- Manual: <one line>

Co-Authored-By: ...
```

### 7.4 完成后更新本文档

- 在 **第八节「已完成」** 追加一行（格式同 HANDOVER 第二节表格）。
- 集成债写入 **第九节**。

---

## 八、已完成（Stage 8）

| Stage | 日期 | 核心产出 | 测试 |
|-------|------|----------|------|
| 8.0–8.1 | 2026-05-25 | `runtime_api/`、`serve --http`、contract tests、`packages/workbench` fork | `pytest tests/contract` 10 passed |
| 8.2 | 2026-05-25 | Python spawn + fork 瘦身 + smoke-workbench-chat | contract 18 passed + SSE smoke |
| 8.3 | 2026-05-26 | auth 链闭环 + GUI 手验聊天 + authed smoke | contract 32 passed + `smoke-workbench-auth.sh` |
| 8.3 polish | 2026-05-26 | ensureRuntime TTL、token fingerprint、SSE 401 UX、probe 缓存 | workbench vitest 13+ passed |
| 8.4 | 2026-05-26 | file_change diff 合成、diagnostics Bearer probe、SSE/error schema | contract 39 passed |

**待办批量清单**：见 [`WORKBENCH_BACKLOG.md`](./WORKBENCH_BACKLOG.md)

---

## 九、集成债清单（Workbench）

| 条目 | Stage | 内容 | 恢复条件 |
|------|-------|------|----------|
| ⬜ 8.legacy.envelope | 8.1 | 旧 `{ok,threads}` 与 parity `/v1` 双轨 | 文档 deprecated + 下 major 删除 |
| ⬜ 8.port.8787 | 8.1 | CLI 默认 port 从 8787→7878 breaking | CHANGELOG + `--port` 兼容 |
| ⬜ 8.gui.claw | — | 故意不做 Claw | 用户要求 v3 单独立项 |
| ⬜ 8.gui.updater | 8.5 | 无 electron-updater | 发布渠道定后再做 |
| ⬜ 8.pack.python | 8.5 | 安装包需预装 Python | embedded python 或 installer 脚本 |
| ⬜ 8.batch-2#F3.events | 8.1 | HANDOVER 已记：SSE 30-tick | **Stage 8.1 必须还清** → 移至 [`WORKBENCH_BACKLOG.md`](./WORKBENCH_BACKLOG.md) P0 |
| ⬜ 8.gui.trim | 8.2+ | Claw/updater/npm 二进制代码仍在 fork 中 | [`WORKBENCH_BACKLOG.md`](./WORKBENCH_BACKLOG.md) P1 批量删 |

---

## 十、GUI v1 调用的 Runtime 端点清单（契约覆盖检查表）

实现 `runtime_api` 时按此表逐条打勾：

| Method | Path | 用途 |
|--------|------|------|
| GET | `/health` | 连接探测 |
| GET | `/v1/threads?limit=` | 列表会话 |
| POST | `/v1/threads` | 创建（workspace/mode/auto_approve/trust_mode） |
| GET | `/v1/threads/{id}` | 详情 + items + latest_seq |
| PATCH | `/v1/threads/{id}` | title / archived |
| POST | `/v1/threads/{id}/turns` | 发消息 → `{thread, turn}` |
| POST | `/v1/threads/{id}/turns/{tid}/interrupt` | 中断 |
| POST | `/v1/threads/{id}/turns/{tid}/steer` | 插队 |
| GET | `/v1/threads/{id}/events?since_seq=` | **SSE** |
| POST | `/v1/approvals/{id}` | 审批 |
| POST | `/v1/user-inputs/{id}` | 用户选择题（P1） |
| GET | `/v1/workspace/status` | 诊断页 |

---

## 十一、与现有仓库差别（完成后预期）

| 维度 | 现在 | Stage 8 完成后 |
|------|------|----------------|
| 用户入口 | TUI only | TUI + Workbench |
| 新增代码 | — | ~2–2.5 万行 TS + ~3k 行 Python runtime_api |
| Engine | 不变 | 不变 |
| app_server | 混合 legacy + 非 parity | + `runtime_api/` 产品级 |
| 测试 | 1323 parity | + ~40–60 contract + 少量 vitest |
| 发布物 | `pip install` | + `.dmg` / `.exe`（P2） |
| docs/DeepSeek-GUI-master | 参考 | 仍参考，可不随产品发布 |

---

## 十二、跨 AI 接手速查

1. 读 **本文档第五节** 找要改的文件路径。
2. 读 **`contracts/runtime-api.openapi.yaml`**（Sprint 0 后存在）确认形状。
3. 跑 **`pytest tests/contract -q`** — 必须全绿再动 GUI。
4. 跑 **`scripts/dev-workbench.sh`** 做手动验证。
5. Rust 行为疑问 → `docs/DeepSeek-TUI-main/crates/tui/src/runtime_api.rs`。
6. UI 交互疑问 → `docs/DeepSeek-GUI-master/src/renderer/`（只读）。
7. **待办 backlog** → [`docs/WORKBENCH_BACKLOG.md`](./WORKBENCH_BACKLOG.md)

---

## 十三、给接手 AI 的三句话

1. **Workbench 是新产品，Engine 是旧资产** — 别重写 brain，把 HTTP 脖子和 Electron 脸接正。
2. **OpenAPI + contract 测试是门禁** — 没有绿测试的 API 改动一律回滚。
3. **参考 GUI 是剪贴板，不是依赖** — fork 时删掉 Claw 和 Rust 二进制逻辑。

---

**本文档随 Stage 8 推进更新第八节。与 [`HANDOVER.md`](./HANDOVER.md) 冲突时：Stage 0–7 以 HANDOVER 为准；Stage 8+ 以本文档为准。**
