"""Working set management for tracking user-relevant files and context.

Mirrors `crates/tui/src/session/working_set.rs`
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepseek_tui.protocol.messages import Message


class WorkingSet:
    """Tracks files and context relevant to current user work.

    Mirrors Rust WorkingSet for pinning decisions during compaction.
    """

    _MAX_RECENT_PATHS = 100

    def __init__(self, workspace: Path | None = None) -> None:
        """Initialize working set.

        Args:
            workspace: Root workspace directory
        """
        self.workspace = workspace
        self.recent_paths: set[str] = set()
        self.recent_tool_uses: list[str] = []
        self.message_count: int = 0

    def observe_user_message(self, text: str, workspace: Path | None = None) -> None:
        """Observe user message and extract relevant paths."""
        self.message_count += 1
        self._extract_paths_from_text(text, workspace)

    def observe_references(self, references: list[Any]) -> None:
        """Track paths from expanded @mention context references."""
        for ref in references:
            target = getattr(ref, "target", None)
            if isinstance(target, str) and target:
                normalized = self._normalize_path(target, self.workspace)
                if normalized:
                    self.recent_paths.add(normalized)
        if len(self.recent_paths) > self._MAX_RECENT_PATHS:
            excess = len(self.recent_paths) - self._MAX_RECENT_PATHS
            for path in list(self.recent_paths)[:excess]:
                self.recent_paths.discard(path)

    def observe_tool_call(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        tool_output: str | None = None,
        workspace: Path | None = None,
    ) -> None:
        """Observe tool execution and track usage."""
        self.recent_tool_uses.append(tool_name)
        if len(self.recent_tool_uses) > 20:
            self.recent_tool_uses.pop(0)

        if tool_input:
            self._extract_paths_from_dict(tool_input, workspace)

        if tool_output:
            self._extract_paths_from_text(tool_output, workspace)

    def pinned_message_indices(
        self,
        messages: list[Message],
        workspace: Path | None = None,
    ) -> set[int]:
        """Determine which message indices should be pinned during compaction.

        Always pins:
        - Last 4 messages (KEEP_RECENT_MESSAGES)

        Also pins messages that reference working set files.
        """
        if not messages:
            return set()

        pinned: set[int] = set()

        # Always keep last 4 messages
        keep_recent = 4
        for i in range(max(0, len(messages) - keep_recent), len(messages)):
            pinned.add(i)

        # Pin messages that reference working set paths
        for idx, msg in enumerate(messages):
            if self._message_references_working_set(msg, workspace):
                pinned.add(idx)

        return pinned

    def top_paths(self, limit: int = 24) -> list[str]:
        """Get top working set paths for compaction context.

        Args:
            limit: Maximum number of paths to return

        Returns:
            List of paths, limited to most recent
        """
        paths = list(self.recent_paths)
        return paths[-limit:]

    def summary(self, limit: int = 24) -> str:
        """Produce a human-readable summary block for cycle carry-forward."""
        paths = self.top_paths(limit)
        if not paths:
            return ""
        lines = ["### Working Set (recent files)"]
        for p in paths:
            lines.append(f"- `{p}`")
        return "\n".join(lines)

    def _extract_paths_from_text(self, text: str, workspace: Path | None = None) -> None:
        """Extract file paths from text."""
        if not text:
            return

        # Simple path extraction: look for common patterns
        import re

        # Match common path patterns
        pattern = (
            r"(?:^|\s)([./][^\s\"\']*\.(?:py|rs|toml|json|yaml|md|txt|sh))"
        )
        for match in re.finditer(pattern, text):
            path = match.group(1)
            if path and len(path) > 2:
                normalized = self._normalize_path(path, workspace)
                if normalized:
                    self.recent_paths.add(normalized)
        if len(self.recent_paths) > self._MAX_RECENT_PATHS:
            excess = len(self.recent_paths) - self._MAX_RECENT_PATHS
            for path in list(self.recent_paths)[:excess]:
                self.recent_paths.discard(path)

    def _extract_paths_from_dict(
        self, obj: dict[str, Any], workspace: Path | None = None
    ) -> None:
        """Extract file paths from tool input dictionary."""
        if not obj:
            return

        # Check common path keys
        for key in ["path", "file", "target", "cwd"]:
            if key in obj and isinstance(obj[key], str):
                path = obj[key]
                normalized = self._normalize_path(path, workspace)
                if normalized:
                    self.recent_paths.add(normalized)

        # Check list-based path keys
        for key in ["paths", "files", "targets"]:
            if key in obj and isinstance(obj[key], list):
                for item in obj[key]:
                    if isinstance(item, str):
                        normalized = self._normalize_path(item, workspace)
                        if normalized:
                            self.recent_paths.add(normalized)

    def _normalize_path(self, path: str, workspace: Path | None = None) -> str | None:
        """Normalize a path candidate.

        Returns None if not a valid path, otherwise a normalized string.
        """
        if not path or len(path) < 2:
            return None

        # Skip very long paths
        if len(path) > 500:
            return None

        # Convert to Path for validation
        try:
            p = Path(path)
            # Return as string for working set tracking
            return str(p)
        except (ValueError, OSError):
            return None

    def _message_references_working_set(
        self, msg: Message, workspace: Path | None = None
    ) -> bool:
        """Check if message references any working set paths."""
        if not self.recent_paths:
            return False

        for block in msg.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and any(
                path in text for path in self.recent_paths
            ):
                return True
            content = getattr(block, "content", None)
            if isinstance(content, str) and any(
                path in content for path in self.recent_paths
            ):
                return True

        return False
