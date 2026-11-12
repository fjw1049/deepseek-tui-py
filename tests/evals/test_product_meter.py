import json
from types import SimpleNamespace

import pytest

from deepseek_tui.client import factory
from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.models import Config
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, Usage
from evals.harness.budget import BudgetExceeded
from evals.product_server import install_meter
from evals.runner import RunOptions, run_evaluations
from evals.schema import EvalCase, EvalObservation, GradeResult


async def test_product_clients_share_durable_budget_and_count_failed_attempts(
    tmp_path, monkeypatch,
):
    path = tmp_path / "meter.json"
    calls = []

    class Client(LLMClient):
        async def stream_chat_completion(self, request):
            calls.append(request)
            assert json.loads(path.read_text())["requests"] == len(calls)
            if len(calls) == 2:
                raise TimeoutError("no usage returned")
            yield StreamDone(usage=Usage(input_tokens=100, output_tokens=10))

    monkeypatch.setattr(factory, "build_llm_client", lambda config: Client())
    monkeypatch.setattr("evals.harness.budget.calculate_turn_cost_estimate_from_usage",
                        lambda *args: SimpleNamespace(usd=.01))
    install_meter(path, max_requests=2, max_output_tokens=64)
    first = factory.build_llm_client(Config())
    second = factory.build_llm_client(Config())
    request = MessageRequest(model="fake", messages=[], max_tokens=999)
    _ = [e async for e in first.stream_chat_completion(request)]
    with pytest.raises(TimeoutError):
        _ = [e async for e in second.stream_chat_completion(request)]
    with pytest.raises(BudgetExceeded):
        _ = [e async for e in first.stream_chat_completion(request)]
    assert len(calls) == 2 and all(c.max_tokens == 64 for c in calls)
    meter = json.loads(path.read_text())
    assert meter["requests"] == 2
    assert meter["metered_requests"] == meter["priced_requests"] == 1
    assert meter["known_cost_usd"] == .01


@pytest.mark.parametrize("priced", [1, 2])
async def test_runner_combines_product_and_review_cost_without_double_counting(
    tmp_path, monkeypatch, priced,
):
    async def harness(case, context):
        context.requests += 1
        context.metered_requests += 1
        context.priced_requests += 1
        context.cost_usd += .03
        context.usage.update(product_requests=2, product_metered_requests=2,
                             product_priced_requests=priced, product_metered_trials=1)
        return EvalObservation()

    monkeypatch.setattr("evals.runner.run_harness", harness)
    monkeypatch.setattr("evals.runner.grade", lambda *args: GradeResult(passed=True, score=1))
    case = EvalCase(id="cost", suite="test", runner="product_session", grader="rubric", live=True,
                    input={"turns": ["task"]}, expect={"rubric": ["done"]})
    output, _ = await run_evaluations(
        RunOptions(mode="live", output_dir=tmp_path / "run"), cases=[case],
    )
    usage = json.loads((output / "cases.jsonl").read_text())["observation"]["usage"]
    assert usage["requests"] == 3 and usage["review_requests"] == 1
    assert usage["metered_requests"] == 3
    assert usage["known_cost_usd"] == .03
    assert ("cost_usd" in usage) == (priced == 2)
    assert not usage.get("unmetered_product_trials")
