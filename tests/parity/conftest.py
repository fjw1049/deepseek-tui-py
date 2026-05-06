"""Shared helpers for parity tests.

These helpers load reference fixtures captured from the Rust implementation
(under ``docs/DeepSeek-TUI-main/crates/``) and provide small utilities used
across the Phase A–E parity tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

PARITY_ROOT = Path(__file__).parent
RUST_FIXTURES_ROOT = PARITY_ROOT / "rust_fixtures"
RUST_SOURCE_ROOT = (
    PARITY_ROOT.parent.parent / "docs" / "DeepSeek-TUI-main" / "crates"
)


@pytest.fixture(scope="session")
def rust_source_root() -> Path:
    """Absolute path to the frozen Rust reference source tree."""
    assert RUST_SOURCE_ROOT.exists(), (
        f"Rust reference tree not found at {RUST_SOURCE_ROOT}. "
        "Parity tests need it — do not delete docs/DeepSeek-TUI-main/."
    )
    return RUST_SOURCE_ROOT


@pytest.fixture(scope="session")
def rust_fixtures_root() -> Path:
    """Absolute path to captured Rust reference fixtures."""
    return RUST_FIXTURES_ROOT


def load_json_fixture(relative_path: str) -> Any:
    """Load a JSON fixture under ``tests/parity/rust_fixtures/``."""
    path = RUST_FIXTURES_ROOT / relative_path
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_text_fixture(relative_path: str) -> str:
    """Load a text fixture under ``tests/parity/rust_fixtures/``."""
    path = RUST_FIXTURES_ROOT / relative_path
    return path.read_text(encoding="utf-8")


def iter_fixtures(sub_dir: str, pattern: str = "*.json") -> Iterator[Path]:
    """Yield every fixture file under a sub-directory."""
    root = RUST_FIXTURES_ROOT / sub_dir
    if not root.exists():
        return iter(())
    return iter(sorted(root.rglob(pattern)))
