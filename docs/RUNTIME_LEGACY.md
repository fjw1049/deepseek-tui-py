# Runtime API — Legacy routes

## Current layout (Stage 8)

| Surface | Prefix | Response shape | Consumers |
|---------|--------|----------------|-----------|
| **Parity (Workbench)** | `/v1/*` | Bare JSON / SSE | `packages/workbench`, `tests/contract` |
| **Legacy App Server** | `/legacy/*` (and some root aliases) | `{ "ok": true, … }` envelope | Older Python integrations, parity tests |

Workbench **only** calls `/v1/*`. Do not point the Electron UI at legacy routes.

## Deprecation plan

1. **Now**: Legacy routes remain for one minor; document-only deprecation (this file).
2. **Next minor**: Log warning on first legacy request per process.
3. **Next major**: Remove `/legacy` mount; migrate callers to `/v1`.

## Port default

- **Workbench / `--http`**: `7878`
- **Legacy `serve` without `--http`**: `8787` (unchanged for backward compatibility)

Use explicit `--port` when running both TUI legacy server and Workbench on one machine.
