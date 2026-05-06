"""Tests for LSP integration."""

from pathlib import Path

from deepseek_tui.lsp import (
    Diagnostic,
    DiagnosticBlock,
    Language,
    LspConfig,
    Severity,
    detect_language,
    render_blocks,
    server_for,
)


def test_language_detection() -> None:
    """Test language detection from file extensions."""
    assert detect_language(Path("test.rs")) == Language.RUST
    assert detect_language(Path("test.go")) == Language.GO
    assert detect_language(Path("test.py")) == Language.PYTHON
    assert detect_language(Path("test.ts")) == Language.TYPESCRIPT
    assert detect_language(Path("test.tsx")) == Language.TYPESCRIPT
    assert detect_language(Path("test.js")) == Language.JAVASCRIPT
    assert detect_language(Path("test.c")) == Language.C
    assert detect_language(Path("test.cpp")) == Language.CPP
    assert detect_language(Path("test.txt")) == Language.OTHER
    assert detect_language(Path("noext")) == Language.OTHER


def test_server_registry() -> None:
    """Test LSP server registry."""
    rust_server = server_for(Language.RUST)
    assert rust_server is not None
    assert rust_server[0] == "rust-analyzer"

    go_server = server_for(Language.GO)
    assert go_server is not None
    assert go_server[0] == "gopls"

    python_server = server_for(Language.PYTHON)
    assert python_server is not None
    assert python_server[0] == "pyright-langserver"

    other_server = server_for(Language.OTHER)
    assert other_server is None


def test_diagnostic_rendering() -> None:
    """Test diagnostic block rendering."""
    blocks = [
        DiagnosticBlock(
            path="test.py",
            diagnostics=[
                Diagnostic(
                    severity=Severity.ERROR,
                    line=10,
                    column=5,
                    message="undefined variable",
                    source="pyright",
                ),
                Diagnostic(
                    severity=Severity.WARNING,
                    line=20,
                    column=1,
                    message="unused import",
                    source=None,
                ),
            ],
        )
    ]

    rendered = render_blocks(blocks)
    assert "test.py" in rendered
    assert "10:5" in rendered
    assert "error" in rendered
    assert "undefined variable" in rendered
    assert "20:1" in rendered
    assert "warning" in rendered
    assert "unused import" in rendered


def test_lsp_config_defaults() -> None:
    """Test LSP config defaults."""
    config = LspConfig()
    assert config.enabled is True
    assert config.poll_after_edit_ms == 5000
    assert config.max_diagnostics_per_file == 20
    assert config.include_warnings is False
    assert config.servers == {}


def test_lsp_config_custom() -> None:
    """Test LSP config with custom values."""
    config = LspConfig(
        enabled=False,
        poll_after_edit_ms=3000,
        max_diagnostics_per_file=10,
        include_warnings=True,
        servers={"rust": ["custom-rust-analyzer"]},
    )
    assert config.enabled is False
    assert config.poll_after_edit_ms == 3000
    assert config.max_diagnostics_per_file == 10
    assert config.include_warnings is True
    assert config.servers == {"rust": ["custom-rust-analyzer"]}


def test_language_id() -> None:
    """Test language ID for LSP."""
    assert Language.RUST.language_id() == "rust"
    assert Language.PYTHON.language_id() == "python"
    assert Language.OTHER.language_id() == "plaintext"
