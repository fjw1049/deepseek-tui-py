"""Exercise endpoint probing over real loopback HTTP, without paid model requests."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from deepseek_tui.client import factory
from deepseek_tui.client.network import NetworkSettings


@pytest.fixture
def endpoint_server(monkeypatch):
    requests = []
    response = {"body": {}, "status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body, self.headers))
            data = json.dumps(response["body"]).encode()
            self.send_response(response["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        "deepseek_tui.client.network.read_network_settings", lambda: NetworkSettings(mode="direct")
    )
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests, response
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("protocol", ["chat", "responses", "anthropic"])
async def test_probe_uses_runtime_protocol(endpoint_server, monkeypatch, protocol):
    url, requests, response = endpoint_server
    # Route a loopback server through the same host decision as the official provider.
    monkeypatch.setattr(factory, "is_openai_host", lambda _: protocol == "responses")
    field = {"chat": "choices", "responses": "output", "anthropic": "content"}[protocol]
    response["body"] = {"model": "fixture", field: [], "status": "completed"}
    result = await factory.test_endpoint(
        url, "fixture-key", "fixture", protocol="anthropic" if protocol == "anthropic" else "openai"
    )
    assert result.success, result.message
    path, body, headers = requests[0]
    assert path == "/v1/" + {
        "chat": "chat/completions", "responses": "responses", "anthropic": "messages"
    }[protocol]
    assert body["stream"] is False
    if protocol == "responses":
        assert "input" in body and "messages" not in body
        assert body["store"] is False
        assert "max_output_tokens" in body and "max_tokens" not in body
    else:
        assert body["messages"]
    assert headers["x-api-key" if protocol == "anthropic" else "Authorization"] == (
        "fixture-key" if protocol == "anthropic" else "Bearer fixture-key"
    )


@pytest.mark.parametrize("body", [{"error": "wrong endpoint"}, {"choices": "invalid"}])
async def test_probe_rejects_invalid_success_body(endpoint_server, body):
    url, _, response = endpoint_server
    response["body"] = body
    assert not (await factory.test_endpoint(url, "fixture", "fixture")).success
