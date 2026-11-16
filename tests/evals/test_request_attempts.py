"""Attempt receipts survive errors/cancellation without inventing missing usage."""
import asyncio
import json

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    StreamThinkingDelta,
    Usage,
)
from evals.harness import HarnessContext
from evals.harness.budget import BudgetedClient, BudgetExceeded


class Client(LLMClient):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.calls = 0

    async def stream_chat_completion(self, request):
        self.calls += 1
        for event in self.events:
            if isinstance(event, BaseException):
                raise event
            yield event


async def test_attempt_receipt_distinguishes_thinking_truncation_from_empty():
    ctx = HarnessContext(workspace=".", remaining_live_requests=2)
    inner = Client([StreamThinkingDelta(thinking="private text"),
                    StreamDone(truncated=True, usage=Usage(output_tokens=12))])
    client = BudgetedClient(inner, ctx)
    request = MessageRequest(model="test", messages=[])
    _ = [e async for e in client.stream_chat_completion(request)]
    receipt = ctx.trace[-1]
    assert receipt['request'] == 1
    assert receipt['outcome'] == 'completed'
    assert receipt['truncated'] is True
    assert receipt['has_thinking'] and not receipt['has_text']
    assert receipt['usage']['output_tokens'] == 12
    assert receipt['elapsed_ms'] >= 0
    assert 'private text' not in json.dumps(receipt)
    inner.events = [StreamDone()]
    _ = [e async for e in client.stream_chat_completion(request)]
    assert ctx.trace[-1]['request'] == 2
    assert ctx.trace[-1]['usage'] is None
    assert not ctx.trace[-1]['has_thinking']
    with pytest.raises(BudgetExceeded):
        _ = [e async for e in client.stream_chat_completion(request)]
    assert inner.calls == 2


@pytest.mark.parametrize('error,outcome', [
    (TimeoutError('timeout'), 'error'),
    (asyncio.CancelledError(), 'cancelled'),
])
async def test_failed_attempt_records_unknown_usage(error, outcome):
    ctx = HarnessContext(workspace=".", remaining_live_requests=1)
    client = BudgetedClient(Client([error]), ctx)
    with pytest.raises(type(error)):
        request = MessageRequest(model='test', messages=[])
        _ = [e async for e in client.stream_chat_completion(request)]
    assert ctx.trace[-1]['outcome'] == outcome
    assert ctx.trace[-1]['usage'] is None
    assert ctx.trace[-1]['truncated'] is None
    assert ctx.remaining_live_requests == 0


async def test_error_event_is_not_a_completed_attempt():
    ctx = HarnessContext(workspace=".", remaining_live_requests=1)
    events = [StreamTextDelta(text='partial'),
              StreamError(message='no retry', retryable=False), StreamDone()]
    client = BudgetedClient(Client(events), ctx)
    _ = [e async for e in client.stream_chat_completion(MessageRequest(model='test', messages=[]))]
    assert ctx.trace[-1]['outcome'] == 'error'
    assert ctx.trace[-1]['has_text']
    assert ctx.trace[-1]['retryable'] is False


async def test_product_meter_persists_receipts_without_prompt_content(tmp_path, monkeypatch):
    from deepseek_tui.client import factory
    from deepseek_tui.config.models import Config
    from deepseek_tui.protocol.messages import Message
    from evals.product_server import install_meter

    monkeypatch.setattr(factory, 'build_llm_client', lambda config: Client([StreamDone()]))
    path = tmp_path / 'usage.json'
    install_meter(path, 1, 32)
    client = factory.build_llm_client(Config())
    request = MessageRequest(model='test', messages=[Message.user('private prompt')])
    _ = [e async for e in client.stream_chat_completion(request)]
    raw = path.read_text()
    saved = json.loads(raw)
    assert saved['attempts'][0]['outcome'] == 'completed'
    assert saved['attempts'][0]['usage'] is None
    assert 'private prompt' not in raw
    assert saved['requests'] == 1


async def test_judge_finishes_the_stream_before_returning_its_verdict(monkeypatch):
    from deepseek_tui.config.models import Config
    from evals import judge
    from evals.schema import EvalCase

    verdict = {'verdict': 'pass', 'claims_complete': True,
               'criteria': [{'id': 1, 'met': True, 'evidence': 'artifact checked'}]}

    class ClosingClient(Client):
        ended = False
        closed_after_stream = False

        async def stream_chat_completion(self, request):
            async for event in super().stream_chat_completion(request):
                yield event
            self.ended = True

        async def close(self):
            self.closed_after_stream = self.ended

    inner = ClosingClient([StreamTextDelta(text=json.dumps(verdict)), StreamDone()])
    monkeypatch.setattr(judge.ConfigLoader, 'load', lambda *a, **kw: Config(model='test'))
    monkeypatch.setattr(judge, 'build_llm_client', lambda config: inner)
    ctx = HarnessContext(workspace='.', remaining_live_requests=1)
    case = EvalCase(id='review', suite='test', runner='product_session', grader='rubric',
                    expect={'rubric': ['Deliver a usable artifact']})
    assert (await judge._ask('packet', ctx, case)).verdict == 'pass'
    assert inner.closed_after_stream
    assert ctx.requests == 1
    assert ctx.trace[-1]['type'] == 'request_finished'
    assert ctx.trace[-1]['outcome'] == 'completed'
