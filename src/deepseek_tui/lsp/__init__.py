"""LSP integration for post-edit diagnostics."""

from deepseek_tui.lsp.client import LspClient, LspTransport, StdioLspTransport
from deepseek_tui.lsp.diagnostics import Diagnostic, DiagnosticBlock, Severity, render_blocks
from deepseek_tui.lsp.hooks import edited_paths_for_tool, parse_patch_paths
from deepseek_tui.lsp.manager import LspConfig, LspManager
from deepseek_tui.lsp.registry import Language, detect_language, server_for

# Key used in ToolContext.metadata for the LspManager instance.
LSP_MANAGER_KEY = "lsp_manager"

__all__ = [
    "LSP_MANAGER_KEY",
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
    "edited_paths_for_tool",
    "parse_patch_paths",
    "render_blocks",
    "server_for",
]
