"""Smoke test proving the parity test harness itself works.

This test does NOT yet test any behavior parity — it only verifies:

1. The ``tests/parity/`` package imports.
2. The Rust reference source tree is available.
3. The ``rust_fixtures/`` directory is resolvable.

Real parity tests (Phase A–E) will be added starting in Stage 1.
"""

from __future__ import annotations

from pathlib import Path


def test_parity_harness_ready(rust_source_root: Path, rust_fixtures_root: Path) -> None:
    assert rust_source_root.is_dir()
    assert (rust_source_root / "tui" / "src").is_dir(), (
        "Rust tui/src/ not found — the reference tree is incomplete."
    )
    # rust_fixtures_root may or may not exist at Stage 0; accept either.
    assert rust_fixtures_root.parent.is_dir()


def test_rust_source_has_expected_modules(rust_source_root: Path) -> None:
    """Sanity-check the modules we plan to audit against."""
    expected = [
        "protocol/src",
        "config/src",
        "secrets/src",
        "state/src",
        "mcp/src",
        "hooks/src",
        "app-server/src",
        "execpolicy/src",
        "tui/src/tools",
        "tui/src/core",
        "tui/src/lsp",
        "tui/src/commands",
        "tui/src/prompts",
        "tui/src/sandbox",
    ]
    missing = [name for name in expected if not (rust_source_root / name).exists()]
    assert not missing, f"Rust reference tree missing modules: {missing}"
