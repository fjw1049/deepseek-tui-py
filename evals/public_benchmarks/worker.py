"""Run the real Engine inside a Harbor task container with an append-only trace."""
# ruff: noqa: ASYNC240 -- small synchronous startup/trace writes are intentionally durable.

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import time
from pathlib import Path

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.client.factory import build_llm_client
from deepseek_tui.config.models import Config
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.protocol.responses import StreamDone, StreamError


def encode(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


def failure_kind(message):
    text = message.lower()
    if any(
        word in text
        for word in (
            "insufficient_quota",
            "insufficient balance",
            "quota exceeded",
            "usage limit",
            "余额不足",
            "额度不足",
            "payment required",
        )
    ):
        return "quota"
    if any(
        word in text
        for word in (
            "unauthorized",
            "invalid api key",
            "authentication",
            "status code 401",
            "status code 403",
        )
    ):
        return "authentication"
    return "api_error"


class Recorder:
    def __init__(self, directory, secrets=()):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = (self.directory / "trace.jsonl").open("a", buffering=1)
        self.secrets = [value for value in secrets if value]
        self.last_progress = time.monotonic()

    def scrub(self, text):
        for value in self.secrets:
            text = text.replace(value, "[REDACTED]")
        return text

    def write(self, kind, **data):
        self.last_progress = time.monotonic()
        self.file.write(
            self.scrub(
                json.dumps(
                    {"time": time.time(), "type": kind, **data}, default=encode, ensure_ascii=False
                )
            )
            + "\n"
        )

    def status(self, data):
        temporary = self.directory / "status.tmp"
        temporary.write_text(
            self.scrub(json.dumps(data, default=encode, ensure_ascii=False, indent=2))
        )
        temporary.replace(self.directory / "status.json")


class RecordedClient(LLMClient):
    def __init__(self, inner, recorder, limit):
        super().__init__(retry_config=RetryConfig(max_transparent_retries=0, max_error_retries=0))
        self.inner, self.recorder, self.limit = inner, recorder, limit
        self.requests = self.metered = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        self.fatal = None
        self.consecutive_errors = 0

    def cache_fingerprint_units(self, request):
        return self.inner.cache_fingerprint_units(request)

    async def close(self):
        await self.inner.close()

    async def stream_chat_completion(self, request):
        if self.requests >= self.limit:
            self.fatal = "request_limit"
        if self.fatal:
            raise RuntimeError(self.fatal)
        self.requests += 1
        self.recorder.write("model_request", request_id=self.requests, request=request)
        completed = False
        had_error = False
        try:
            async for event in self.inner.stream_chat_completion(request):
                self.recorder.write("provider_event", request_id=self.requests, event=event)
                if isinstance(event, StreamError):
                    had_error = True
                    message = json.dumps(encode(event))
                    self.recorder.write("api_error", message=message)
                    kind = failure_kind(message)
                    if kind != "api_error":
                        self.fatal = kind
                if isinstance(event, StreamDone):
                    completed = not had_error
                    if event.usage is not None:
                        self.metered += 1
                        self.usage["input_tokens"] += event.usage.total_input_tokens
                        self.usage["output_tokens"] += event.usage.output_tokens
                        self.usage["cache_read_input_tokens"] += event.usage.cache_read_input_tokens
                yield event
        except Exception as exc:
            kind = failure_kind(str(exc))
            if kind != "api_error":
                self.fatal = kind
            self.recorder.write("api_error", message=str(exc), category=kind)
            raise
        finally:
            self.consecutive_errors = 0 if completed else self.consecutive_errors + 1
            if self.consecutive_errors >= 3:
                self.fatal = self.fatal or "persistent_api_error"
            self.recorder.write(
                "request_finished", request_id=self.requests, completed=completed, usage=self.usage
            )


async def run(private_path, instruction_path, logs_dir):
    private = json.loads(Path(private_path).read_text())
    Path(private_path).unlink()  # Credentials are not left in the agent workspace/logs.
    state = Path("/installed-agent/state")
    state.mkdir(exist_ok=True)
    os.environ["DEEPSEEK_HOME"] = str(state)
    (state / "network.json").write_text(json.dumps(private["network"]))
    cfg = Config.model_validate(private["config"])
    cfg.skills_dir = state / "skills"
    cfg.notes_path = state / "notes.md"
    cfg.mcp_config_path = state / "mcp.json"
    recorder = Recorder(
        logs_dir, [cfg.api_key, *cfg.effective_provider_config().extra_headers.values()]
    )
    public_config = cfg.model_dump(mode="json")
    public_config["api_key"] = "[REDACTED]"
    (recorder.directory / "runtime-config.json").write_text(
        recorder.scrub(json.dumps(public_config, indent=2))
    )
    client = RecordedClient(build_llm_client(cfg), recorder, private["request_limit"])
    handle = EngineHandle()
    engine = engine_task = next_event = None
    started = time.time()
    result = {"state": "running", "started_at": started, "pid": os.getpid(), "model": cfg.model}
    recorder.status(result)
    try:
        engine = await asyncio.wait_for(
            Engine.create(
                handle,
                client,
                config=cfg,
                working_directory=Path.cwd(),
                default_model=cfg.model,
                max_tool_round_trips=private["request_limit"],
                start_mcp=False,
            ),
            timeout=120,
        )
        engine.default_top_p = 1.0
        recorder.write("runtime_ready", cwd=str(Path.cwd()), model=cfg.model)
        engine_task = asyncio.create_task(engine.run())
        await handle.send_message(Path(instruction_path).read_text(), max_tokens=65536)
        events = handle.events().__aiter__()
        next_event = asyncio.create_task(events.__anext__())
        while True:
            done, _ = await asyncio.wait(
                (next_event, engine_task), timeout=5, return_when=asyncio.FIRST_COMPLETED
            )
            result.update(
                updated_at=time.time(),
                requests=client.requests,
                metered_requests=client.metered,
                usage=client.usage,
                idle_seconds=time.monotonic() - recorder.last_progress,
            )
            recorder.status(result)
            if next_event in done:
                event = next_event.result()
                kind = type(event).__name__
                recorder.write(kind, event=event)
                if kind == "TurnCompleteEvent":
                    result.update(
                        state="completed" if event.success else "runtime_error",
                        error=event.error_message,
                    )
                    (recorder.directory / "final.json").write_text(
                        recorder.scrub(
                            json.dumps(encode(event), default=encode, ensure_ascii=False, indent=2)
                        )
                    )
                    break
                if kind == "TurnCancelledEvent":
                    result.update(state="cancelled", error=event.reason)
                    break
                if kind == "UserInputRequiredEvent":
                    result.update(
                        state="needs_user_input",
                        error="Noninteractive benchmark requires autonomous completion",
                    )
                    break
                next_event = asyncio.create_task(events.__anext__())
            if client.fatal:
                result.update(state=client.fatal)
                break
            if engine_task in done:
                engine_task.result()
                raise RuntimeError("Engine exited before a terminal event")
            if time.monotonic() - recorder.last_progress > private["idle_timeout_sec"]:
                result.update(state="idle_timeout")
                break
            if time.time() - started > private["task_timeout_sec"]:
                result.update(state="task_timeout")
                break
    except Exception as exc:
        result.update(state=client.fatal or "runtime_error", error=f"{type(exc).__name__}: {exc}")
        recorder.write("worker_error", error=result["error"])
    finally:
        result.update(
            state=client.fatal or result["state"],
            finished_at=time.time(),
            requests=client.requests,
            metered_requests=client.metered,
            usage=client.usage,
            cost_usd=None,
        )
        recorder.status(result)
        recorder.write("worker_finished", result=result)
        for task in (engine_task, next_event):
            if task is not None:
                task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(t for t in (engine_task, next_event) if t), return_exceptions=True
                ),
                10,
            )
            if engine:
                await asyncio.wait_for(engine.shutdown(), 10)
            await asyncio.wait_for(client.close(), 10)
        except Exception as exc:
            recorder.write("shutdown_error", error=str(exc))
        recorder.file.close()
    return result


if __name__ == "__main__":
    import sys

    outcome = asyncio.run(run(*sys.argv[1:]))
    print(json.dumps({"state": outcome["state"], "requests": outcome["requests"]}), flush=True)
    # The verifier still runs after a failed agent turn; infrastructure status is separate.
    sys.exit(0)
