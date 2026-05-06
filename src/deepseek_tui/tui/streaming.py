from __future__ import annotations


class LineBuffer:
    """Buffers streaming text and commits only complete lines."""

    def __init__(self) -> None:
        self._buffer: str = ""
        self._committed: list[str] = []

    def push(self, delta: str) -> None:
        self._buffer += delta

    def commit_complete_lines(self) -> list[str]:
        lines = self._buffer.split("\n")
        if len(lines) > 1:
            complete = lines[:-1]
            self._committed.extend(complete)
            self._buffer = lines[-1]
            return complete
        return []

    def finalize(self) -> list[str]:
        if self._buffer:
            self._committed.append(self._buffer)
            result = [self._buffer]
            self._buffer = ""
            return result
        return []

    @property
    def committed(self) -> list[str]:
        return self._committed

    @property
    def pending(self) -> str:
        return self._buffer
