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
