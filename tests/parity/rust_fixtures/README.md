# Rust reference fixtures

This directory holds reference samples captured from (or hand-extracted
from) the Rust implementation at `docs/DeepSeek-TUI-main/crates/`. These
are used by `tests/parity/` to prove that the Python port matches Rust
behavior byte-for-byte where possible, and semantically where not.

## Conventions

- One sub-directory per audited layer: `protocol/`, `secrets/`, `state/`,
  `client/`, `engine/`, `tools/`, `mcp/`.
- Prefer `.json` for structured captures, `.sse.log` for raw SSE streams,
  `.sql` for schema samples.
- Each fixture file name should reference its Rust source file, e.g.:
  - `protocol/event_frame_session_start.json`  (from
    `crates/protocol/src/lib.rs:370-451` EventFrame variants)
  - `client/sse_deepseek_v4_thinking.log`      (captured from a real
    call in `crates/tui/src/client/chat.rs`)

## Populating fixtures

Fixtures are added incrementally as each Stage-1+ parity test lands.
Phase A starts with:

1. `protocol/event_frame_samples.json`  — one object per `EventFrame`
   variant (20 variants per Phase A audit).
2. `secrets/precedence_cases.json`      — `{env, config, keyring}` →
   expected `resolved_source` and value.
3. `state/schema.sql`                    — the Rust SQLite schema
   (captured from `crates/state/src/lib.rs`).

When adding a new fixture, also add a unit test under `tests/parity/phase_X/`
that loads it and asserts Python parity.
