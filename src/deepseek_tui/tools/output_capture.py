"""Bounded Shell output with readable, size-limited spill files."""

from __future__ import annotations

import asyncio
import uuid

MEMORY_LIMIT = 64 * 1024
DISK_LIMIT = 8 * 1024 * 1024


class OutputCapture:
    def __init__(self) -> None:
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0
        self.saved = 0
        self.path = None
        self._file = None
        self._spill_attempted = False
        self._spill_failed = False

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        if self.total + len(chunk) > MEMORY_LIMIT and not self._spill_attempted:
            self._spill_attempted = True
            from deepseek_tui.tools.runtime import spillover_path

            try:
                self.path = spillover_path(f"shell-{uuid.uuid4().hex}")
                if self.path is None:
                    raise OSError("No spill directory")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._file = self.path.open("xb")
                self._write(bytes(self.head) + bytes(self.tail))
            except OSError:
                self._spill_failed = True
                self.close()
        self._write(chunk)
        self.total += len(chunk)
        head_part = min(len(chunk), MEMORY_LIMIT // 2 - len(self.head))
        self.head.extend(chunk[:head_part])
        self.tail.extend(chunk[head_part:])
        if len(self.tail) > MEMORY_LIMIT // 2:
            del self.tail[: -MEMORY_LIMIT // 2]

    def _write(self, chunk: bytes) -> None:
        if self._file is None:
            return
        try:
            portion = chunk[: max(0, DISK_LIMIT - self.saved)]
            self._file.write(portion)
            self.saved += len(portion)
        except OSError:
            self._spill_failed = True
            self.close()

    def close(self) -> None:
        if self._file is not None:
            file, self._file = self._file, None
            try:
                file.close()
            except OSError:
                self._spill_failed = True

    def preview(self) -> bytes:
        if self.total <= MEMORY_LIMIT:
            return bytes(self.head + self.tail)
        if self._spill_failed or self.path is None:
            detail = "Full output unavailable: spill write failed."
        elif self.total > self.saved:
            detail = f"Saved first {self.saved} bytes to {self.path}; disk limit reached."
        else:
            detail = f"Full output saved to {self.path}."
        marker = f"\n[Output truncated: {self.total} bytes captured. {detail}]\n".encode()
        return bytes(self.head) + marker + bytes(self.tail)


async def collect_process(process) -> tuple[bytes, bytes]:
    """Drain both pipes concurrently, even after memory/disk budgets are reached."""

    async def drain(stream) -> bytes:
        capture = OutputCapture()
        try:
            if stream is not None:
                while chunk := await stream.read(65536):
                    capture.append(chunk)
        finally:
            capture.close()
        return capture.preview()

    tasks = [asyncio.create_task(drain(process.stdout)), asyncio.create_task(drain(process.stderr))]
    try:
        stdout, stderr = await asyncio.gather(*tasks)
        await process.wait()
        return stdout, stderr
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
