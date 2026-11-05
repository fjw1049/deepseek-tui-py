import json

from deepseek_tui.client.token_compat import adapt_completion_tokens


def test_explicit_token_error_retries_once():
    body = json.dumps({"error": {"param": "max_tokens", "code": "unsupported_parameter", "message": "Use max_completion_tokens instead."}})
    payload = {"model": "example", "max_tokens": 1024}
    assert not adapt_completion_tokens(401, body, payload)
    assert adapt_completion_tokens(400, body, payload)
    assert payload == {"model": "example", "max_completion_tokens": 1024}
    assert not adapt_completion_tokens(400, body, payload)


def test_other_errors_leave_payload_unchanged():
    for body in ('invalid JSON', '{}', '{"error": null}', '{"error": {"param": "tool_choice"}}'):
        payload = {"max_tokens": 1024}
        assert not adapt_completion_tokens(400, body, payload)
        assert payload == {"max_tokens": 1024}


async def test_client_learns_max_completion_tokens_once_from_a_long_error():
    import httpx

    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.protocol.messages import MessageRequest

    sent: list[dict] = []
    error = json.dumps({"error": {
        # Longer than the 512 characters kept for the error message.
        "message": "Unsupported parameter: 'max_tokens'. "
        "Use 'max_completion_tokens' instead. " + "x" * 600,
        "param": "max_tokens", "code": "unsupported_parameter",
    }})
    stream = (
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent.append(payload)
        if "max_tokens" in payload:
            return httpx.Response(400, text=error)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=stream)

    client = DeepSeekClient(
        api_key="fake",
        base_url="https://example.invalid",
        transport=httpx.MockTransport(handle),
    )
    try:
        for _ in range(2):
            [e async for e in client.stream_chat_completion(
                MessageRequest(model="fixture", messages=[], max_tokens=64)
            )]
    finally:
        await client.close()
    # One rejected request, then both turns use the accepted parameter name.
    assert ["max_tokens" in p for p in sent] == [True, False, False]
    assert all(p.get("max_completion_tokens") == 64 for p in sent[1:])
