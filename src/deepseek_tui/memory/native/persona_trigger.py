"""Persona generation trigger logic aligned with TencentDB memory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from deepseek_tui.memory.native.checkpoint import CheckpointManager
from deepseek_tui.memory.native.l3_persona import persona_path_for_workspace


@dataclass(slots=True)
class PersonaTriggerResult:
    should: bool
    reason: str = ""


class PersonaTrigger:
    def __init__(
        self,
        data_dir: Path,
        *,
        interval: int,
        workspace: str | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._checkpoint = CheckpointManager(data_dir)
        self._interval = max(1, interval)
        self._workspace = workspace

    def should_generate(self) -> PersonaTriggerResult:
        checkpoint = self._checkpoint.read()
        if checkpoint.request_persona_update:
            reason = checkpoint.persona_update_reason or "Agent requested persona update"
            return PersonaTriggerResult(True, f"主动请求: {reason}")

        if (
            checkpoint.scenes_processed > 0
            and checkpoint.last_persona_at == 0
            and self._has_scene_files()
        ):
            return PersonaTriggerResult(True, "首次冷启动：首次提取完成且有场景文件")

        if (
            checkpoint.last_persona_at > 0
            and self._has_scene_files()
            and not self._has_persona_body()
        ):
            return PersonaTriggerResult(True, "恢复：persona.md 正文丢失或为空，需要重新生成")

        if checkpoint.scenes_processed == 1 and checkpoint.memories_since_last_persona > 0:
            return PersonaTriggerResult(True, "首次 Scene Block 提取完成")

        if checkpoint.memories_since_last_persona >= self._interval:
            return PersonaTriggerResult(
                True,
                (
                    "达到阈值: "
                    f"{checkpoint.memories_since_last_persona} >= {self._interval}"
                ),
            )

        return PersonaTriggerResult(False)

    def _has_scene_files(self) -> bool:
        blocks_dir = self._data_dir / "scene_blocks"
        try:
            return any(path.suffix == ".md" for path in blocks_dir.iterdir())
        except OSError:
            return False

    def _has_persona_body(self) -> bool:
        persona_path = persona_path_for_workspace(
            self._data_dir / "persona.md",
            workspace=self._workspace,
        )
        try:
            raw = persona_path.read_text(encoding="utf-8")
        except OSError:
            return False
        body = _strip_scene_navigation(raw).strip()
        return bool(body)


def _strip_scene_navigation(raw: str) -> str:
    marker = "## Scene navigation"
    idx = raw.find(marker)
    if idx >= 0:
        return raw[:idx]
    return raw
