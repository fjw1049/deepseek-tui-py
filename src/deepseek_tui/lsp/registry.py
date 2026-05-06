"""Language detection and LSP server registry."""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class Language(Enum):
    """Supported languages for LSP integration."""

    RUST = "rust"
    GO = "go"
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    C = "c"
    CPP = "cpp"
    OTHER = "other"

    def as_key(self) -> str:
        """Stable lowercase key for config overrides."""
        return self.value

    def language_id(self) -> str:
        """LSP languageId for textDocument/didOpen."""
        if self == Language.OTHER:
            return "plaintext"
        return str(self.value)


def detect_language(path: Path) -> Language:
    """Detect language from file extension."""
    ext = path.suffix.lower().lstrip(".")
    if not ext:
        return Language.OTHER
    mapping = {
        "rs": Language.RUST,
        "go": Language.GO,
        "py": Language.PYTHON,
        "pyi": Language.PYTHON,
        "ts": Language.TYPESCRIPT,
        "tsx": Language.TYPESCRIPT,
        "js": Language.JAVASCRIPT,
        "jsx": Language.JAVASCRIPT,
        "mjs": Language.JAVASCRIPT,
        "cjs": Language.JAVASCRIPT,
        "c": Language.C,
        "h": Language.C,
        "cpp": Language.CPP,
        "cc": Language.CPP,
        "cxx": Language.CPP,
        "hpp": Language.CPP,
        "hxx": Language.CPP,
        "hh": Language.CPP,
    }
    return mapping.get(ext, Language.OTHER)


def server_for(lang: Language) -> tuple[str, list[str]] | None:
    """Return (command, args) for the LSP server of this language."""
    registry = {
        Language.RUST: ("rust-analyzer", []),
        Language.GO: ("gopls", ["serve"]),
        Language.PYTHON: ("pyright-langserver", ["--stdio"]),
        Language.TYPESCRIPT: ("typescript-language-server", ["--stdio"]),
        Language.JAVASCRIPT: ("typescript-language-server", ["--stdio"]),
        Language.C: ("clangd", []),
        Language.CPP: ("clangd", []),
    }
    return registry.get(lang)
