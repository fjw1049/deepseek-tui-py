# DeepSeek Workbench — Architecture

> Companion to [`WORKBENCH_HANDOVER.md`](./WORKBENCH_HANDOVER.md). Stage 8 product surface.

## Components

```mermaid
sequenceDiagram
  participant U as User
  participant R as Renderer (React)
  participant M as Electron Main
  participant P as Python runtime_api
  participant E as Engine

  U->>R: Composer / Sidebar
  R->>M: window.dsGui (IPC)
  M->>P: HTTP /v1/* + SSE (Bearer)
  P->>E: RuntimeThreadManager
  E-->>P: EngineEvent stream
  P-->>M: text/event-stream
  M-->>R: onSseEvent
  R-->>U: Timeline blocks
```

| Layer | Path | Role |
|-------|------|------|
| Contract | `contracts/runtime-api.openapi.yaml` | Single truth for `/v1` JSON + SSE |
| Runtime API | `src/deepseek_tui/app_server/runtime_api/` | FastAPI routes, auth, approval bridge |
| Threads | `src/deepseek_tui/app_server/thread_manager.py` | Engine lifecycle, SSE events, trust_mode |
| Workbench | `packages/workbench/` | Electron host + React UI |
| Legacy | `app_server/legacy/` + `/legacy` mount | Old `{ok:true}` envelope (deprecated) |

## Request paths

- **Spawn**: Main process runs `python -m deepseek_tui serve --http --port 7878 --auth-token …`
- **Auth**: Bearer in `Authorization` header only (no query token)
- **Token file**: `~/.deepseek/runtime.token` — Python seeds if empty; GUI reads, never overwrites non-empty file
- **Approvals**: `ApprovalRequiredEvent` → `approval.required` SSE → GUI POST `/v1/approvals/{id}` → `ApprovalBridge`
- **Steer**: GUI POST `…/steer` → `EngineHandle.steer()` (mid-turn queue)
- **User input**: `UserInputRequiredEvent` → SSE → POST `/v1/user-inputs/{id}`

## Verification

```bash
pytest tests/contract -q
./scripts/smoke-workbench-auth.sh
cd packages/workbench && npm run typecheck
```
