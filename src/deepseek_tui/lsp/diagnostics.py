"""LSP diagnostic models and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    """LSP diagnostic severity."""

    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


@dataclass(slots=True)
class Diagnostic:
    """A single LSP diagnostic."""

    severity: Severity
    line: int
    column: int
    message: str
    source: str | None = None


@dataclass(slots=True)
class DiagnosticBlock:
    """Diagnostics for a single file."""

    path: str
    diagnostics: list[Diagnostic]


def render_blocks(blocks: list[DiagnosticBlock]) -> str:
    """Render diagnostic blocks as markdown."""
    if not blocks:
        return ""
    lines: list[str] = []
    for block in blocks:
        lines.append(f"**{block.path}**")
        for diag in block.diagnostics:
            severity_label = {
                Severity.ERROR: "error",
                Severity.WARNING: "warning",
                Severity.INFORMATION: "info",
                Severity.HINT: "hint",
            }.get(diag.severity, "unknown")
            loc = f"{diag.line}:{diag.column}"
            source_tag = f" [{diag.source}]" if diag.source else ""
            lines.append(f"  - {loc} {severity_label}{source_tag}: {diag.message}")
        lines.append("")
    return "\n".join(lines).rstrip()
