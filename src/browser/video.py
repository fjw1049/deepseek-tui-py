"""Bounded, continuous browser capture using the existing CDP session and FFmpeg."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path


class BrowserVideo:
    # Capture independently of the action lock, including waits and page animations.
    fps = 5
    max_seconds = 180

    def __init__(self, path: Path, capture: Callable[[], Awaitable[bytes]]):
        self.path = path
        self.capture = capture
        self.task: asyncio.Task | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.stopping = asyncio.Event()
        self.error: str | None = None
        self.frames = 0

    async def start(self) -> None:
        executable = shutil.which("ffmpeg")
        if not executable:
            raise ValueError("Continuous video requires FFmpeg on the Runtime PATH")
        self.process = await asyncio.create_subprocess_exec(
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "image2pipe",
            "-framerate",
            str(self.fps),
            "-vcodec",
            "mjpeg",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libvpx",
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            "-b:v",
            "1M",
            str(self.path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.task = asyncio.create_task(self._record())

    async def _record(self) -> None:
        assert self.process and self.process.stdin
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            while not self.stopping.is_set() and loop.time() - started < self.max_seconds:
                frame = await self.capture()
                # Duplicate delayed frames to keep playback close to elapsed wall time.
                due = min(int((loop.time() - started) * self.fps) + 1, self.max_seconds * self.fps)
                while self.frames < due:
                    self.process.stdin.write(frame)
                    await asyncio.wait_for(self.process.stdin.drain(), timeout=5)
                    self.frames += 1
                try:
                    await asyncio.wait_for(self.stopping.wait(), timeout=1 / self.fps)
                except TimeoutError:
                    pass
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__
        finally:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=10)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
                self.error = "Video encoder did not finish in time"
            if self.process.returncode and not self.error:
                self.error = "Video encoder failed"

    async def stop(self) -> None:
        self.stopping.set()
        if self.task:
            await self.task
