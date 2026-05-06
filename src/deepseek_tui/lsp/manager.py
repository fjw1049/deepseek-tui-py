"""LSP manager for lazy server spawning and diagnostics collection."""

from __future__ import annotations

import asyncio
from pathlib import Path

from deepseek_tui.lsp.client import LspClient, StdioLspTransport
from deepseek_tui.lsp.diagnostics import Diagnostic, DiagnosticBlock, Severity
from deepseek_tui.lsp.registry import Language, detect_language, server_for


class LspConfig:
    """LSP configuration."""

    def __init__(
        self,
        enabled: bool = True,
        poll_after_edit_ms: int = 5000,
        max_diagnostics_per_file: int = 20,
        include_warnings: bool = False,
        servers: dict[str, list[str]] | None = None,
    ) -> None:
        self.enabled = enabled
        self.poll_after_edit_ms = poll_after_edit_ms
        self.max_diagnostics_per_file = max_diagnostics_per_file
        self.include_warnings = include_warnings
        self.servers = servers or {}


class LspManager:
    """Manages LSP clients and diagnostics collection."""

    def __init__(self, config: LspConfig) -> None:
        self.config = config
        self._clients: dict[Language, LspClient] = {}
        self._warned_missing: set[Language] = set()

    async def diagnostics_for(self, path: Path, content: str, seq: int) -> list[DiagnosticBlock]:
        """Get diagnostics for a file after an edit."""
        if not self.config.enabled:
            return []

        lang = detect_language(path)
        if lang == Language.OTHER:
            return []

        client = await self._get_or_spawn_client(lang)
        if client is None:
            return []

        try:
            if seq == 1:
                await client.did_open(path, content)
            else:
                await client.did_change(path, content, seq)

            await asyncio.sleep(self.config.poll_after_edit_ms / 1000.0)

            diagnostics = client.get_diagnostics(path)
            filtered = self._filter_diagnostics(diagnostics)
            if not filtered:
                return []

            return [DiagnosticBlock(path=str(path), diagnostics=filtered)]
        except Exception:
            return []

    async def _get_or_spawn_client(self, lang: Language) -> LspClient | None:
        """Get or spawn an LSP client for a language."""
        if lang in self._clients:
            return self._clients[lang]

        server_cmd = self.config.servers.get(lang.as_key())
        if server_cmd:
            command = server_cmd[0]
            args = server_cmd[1:]
        else:
            server_info = server_for(lang)
            if server_info is None:
                return None
            command, args = server_info

        try:
            transport = StdioLspTransport(command, args)
            client = LspClient(transport, lang)
            await client.start()
            self._clients[lang] = client
            return client
        except Exception:
            if lang not in self._warned_missing:
                self._warned_missing.add(lang)
            return None

    def _filter_diagnostics(self, diagnostics: list[Diagnostic]) -> list[Diagnostic]:
        """Filter and limit diagnostics."""
        filtered = []
        for diag in diagnostics:
            if diag.severity == Severity.ERROR:
                filtered.append(diag)
            elif diag.severity == Severity.WARNING and self.config.include_warnings:
                filtered.append(diag)

        filtered.sort(key=lambda d: (d.severity, d.line, d.column))
        return filtered[: self.config.max_diagnostics_per_file]

    async def close_all(self) -> None:
        """Close all LSP clients."""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
