import pytest

from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.orchestrator import PostTurnOrchestrator


class _RecordingPipeline:
    name = "rec"

    def __init__(self) -> None:
        self.after: list[TurnEvidence] = []
        self.flush: list[TurnEvidence] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def after_turn(self, evidence: TurnEvidence) -> None:
        self.after.append(evidence)

    async def flush_before_loss(self, evidence: TurnEvidence) -> None:
        self.flush.append(evidence)


@pytest.mark.asyncio
async def test_orchestrator_runs_pipelines_in_order() -> None:
    first = _RecordingPipeline()
    first.name = "first"
    second = _RecordingPipeline()
    second.name = "second"
    orch = PostTurnOrchestrator([first, second], flush_timeout_s=1.0)
    ev = TurnEvidence(
        thread_id="t",
        user_text="x",
        workspace="/w",
        messages=[],
        had_tool_calls=False,
        success=True,
    )
    await orch.after_turn(ev)
    assert first.after == [ev]
    assert second.after == [ev]
    await orch.flush_before_loss(ev)
    assert first.flush[0].flush_mode is True
