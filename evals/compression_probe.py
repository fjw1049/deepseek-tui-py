"""Live append-summary cache probe: PYTHONPATH=src python -m evals.compression_probe."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.engine.capacity import _create_summary, validate_compaction_summary
from deepseek_tui.engine.prefix_probe import fingerprint_request, first_divergence
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamError,
    StreamTextDelta,
    StreamToolCallComplete,
)


class RecordingClient:
    def __init__(self, client):
        self.client = client
        self.records = []
        self.fingerprints = []

    async def stream_chat_completion(self, request):
        row = {"tool_calls": 0, "text": "", "usage": None}
        self.records.append(row)
        self.fingerprints.append(
            fingerprint_request(request.system_prompt, request.messages, request.tools)
        )
        async for event in self.client.stream_chat_completion(request):
            if isinstance(event, StreamError):
                raise RuntimeError(event.message)
            if isinstance(event, StreamTextDelta):
                row["text"] += event.text
            if isinstance(event, StreamToolCallComplete):
                row["tool_calls"] += 1
            if isinstance(event, StreamDone):
                row["usage"] = event.usage.model_dump() if event.usage else None
            yield event


async def main(output: Path, reasoning_effort: str | None = None):
    config = ConfigLoader().load(provider="deepseek", model="deepseek-flash")
    provider = config.effective_provider_config()
    client = build_llm_client(config)
    recorder = RecordingClient(client)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]
    messages = [
        Message.user(
            "Read these records and reply OK.\n"
            + "\n".join(
                f"Record {i}: preserve offline support and Chinese exports; status pending."
                for i in range(1500)
            )
        )
    ]
    system = "You are a coding assistant."
    try:
        request = MessageRequest(
            model="deepseek-flash",
            system_prompt=system,
            tools=tools,
            messages=messages,
            max_tokens=64 if reasoning_effort == "off" else 2048,
            reasoning_effort=reasoning_effort or config.reasoning_effort,
            tool_choice={"type": "auto"},
            temperature=provider.temperature,
            extra_body=dict(provider.extra_body),
        )
        async for _ in recorder.stream_chat_completion(request):
            pass
        messages = [*messages, Message.assistant(recorder.records[0]["text"])]
        summary = await _create_summary(
            recorder,
            messages,
            "deepseek-flash",
            system_prompt=system,
            tools=tools,
            request_template=request,
            model_config=config,
        )
        usage = recorder.records[-1]["usage"]
        result = {
            "model": "deepseek-flash",
            "reasoning_effort": request.reasoning_effort,
            "request_count": len(recorder.records),
            "summary_validation_error": validate_compaction_summary(summary),
            "first_divergence": first_divergence(*recorder.fingerprints),
            "cache_hit_ratio": usage["cache_read_input_tokens"] / usage["input_tokens"],
            "requests": recorder.records,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(output.write_text, json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Two-request DeepSeek Flash cache smoke test")
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument(
        "--output", type=Path, default=Path("evals/artifacts/compression-production-probe.json")
    )
    args = parser.parse_args()
    asyncio.run(asyncio.wait_for(main(args.output, args.reasoning_effort), timeout=180))
