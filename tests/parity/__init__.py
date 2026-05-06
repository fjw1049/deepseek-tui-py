"""Parity tests against the Rust reference implementation.

Each Python module being ported must have a paired parity test that
proves behavior is equivalent to the Rust source under
`docs/DeepSeek-TUI-main/crates/`. Reference fixtures (captured from the
Rust code or hand-crafted from Rust source) live in
`tests/parity/rust_fixtures/`.

Organization:

    tests/parity/
        conftest.py            shared helpers (e.g. fixture loader)
        rust_fixtures/         Rust-side reference samples
            protocol/          event frames, envelope samples
            secrets/           precedence fixtures
            state/             SQL schema + timestamp samples
            client/            SSE logs captured from Rust client
            engine/            turn-loop transcripts
            tools/             tool payload and output pairs
            mcp/               JSON-RPC dialog captures
        phase_a/               protocol + config + secrets + state tests
        phase_b/               client + engine + execpolicy tests
        phase_c/               tools tests (one per Rust tool)
        phase_d/               mcp + lsp + hooks + app_server tests
        phase_e/               tui + cli + commands + prompts tests

Guidance:
- Prefer pytest parametrize with fixture filenames for breadth.
- Use golden-file comparison for deterministic outputs.
- Mark tests that cannot run on CI (e.g. require gh CLI) with
  `@pytest.mark.requires_gh`, and gate via env var.
"""
