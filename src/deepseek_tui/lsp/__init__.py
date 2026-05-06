"""LSP integration for post-edit diagnostics."""

from deepseek_tui.lsp.client import LspClient, LspTransport, StdioLspTransport
from deepseek_tui.lsp.diagnostics import Diagnostic, DiagnosticBlock, Severity, render_blocks
from deepseek_tui.lsp.manager import LspConfig, LspManager
from deepseek_tui.lsp.registry import Language, detect_language, server_for

__all__ = [
    "Diagnostic",
    "DiagnosticBlock",
    "Language",
    "LspClient",
    "LspConfig",
    "LspManager",
    "LspTransport",
    "Severity",
    "StdioLspTransport",
    "detect_language",
    "render_blocks",
    "server_for",
]
