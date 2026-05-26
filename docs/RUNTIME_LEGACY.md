# Runtime API — Legacy routes

## Current layout (Stage 8)

| Surface | Prefix | Response shape | Consumers |
|---------|--------|----------------|-----------|
| **Parity (Workbench)** | `/v1/*` | Bare JSON / SSE | `packages/workbench`, `tests/contract` |
| **Legacy App Server** | `/legacy/*` (and some root aliases) | `{ "ok": true, … }` envelope | Older Python integrations, parity tests |

Workbench **only** calls `/v1/*`. Do not point the Electron UI at legacy routes.

## Legacy SSE (`/threads/{id}/events/stream`)

The non-`/v1` stream route polls `events_since` for **30 × 100ms (~3s)** per HTTP response, then sends `event: done`. It exists for older integrations that reconnect with `since_seq`. **Do not use it for Workbench** — use `GET /v1/threads/{id}/events` (long-lived backlog + live via `runtime_api/sse.py`).

## Deprecation plan

1. **Now**: Legacy routes remain for one minor; document-only deprecation (this file).
2. **Next minor**: Log warning on first legacy request per process.
3. **Next major**: Remove `/legacy` mount; migrate callers to `/v1`.

## Port default

- **Workbench / `--http`**: `7878`
- **Legacy `serve` without `--http`**: `8787` (unchanged for backward compatibility)

Use explicit `--port` when running both TUI legacy server and Workbench on one machine.
