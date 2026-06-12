"""TUI launch and one-shot engine execution for the CLI."""

from __future__ import annotations

import asyncio

import typer

from deepseek_tui.config.models import Config


def launch_tui(config: Config) -> None:
    try:
        from deepseek_tui.tui.app import DeepSeekTUI

        DeepSeekTUI(config=config).run()
    except ImportError as exc:
        typer.echo("TUI not available — textual not installed.", err=True)
        raise typer.Exit(1) from exc


def run_one_shot(config: Config, prompt: str) -> None:
    asyncio.run(_run_one_shot_async(config, prompt))


async def _run_one_shot_async(config: Config, prompt: str) -> None:
    from deepseek_tui.client.deepseek import DeepSeekClient
    from deepseek_tui.engine.engine import Engine
    from deepseek_tui.engine.events import (
        ErrorEvent,
        TextDeltaEvent,
        ToolCallEvent,
        ToolResultEvent,
        TurnCompleteEvent,
    )
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.secrets.manager import SecretsManager

    mgr = SecretsManager()
    api_key = mgr.resolve_api_key(config)
    if not api_key:
        typer.echo("No API key configured. Run `deepseek-tui login` first.", err=True)
        raise typer.Exit(1)

    pc = config.effective_provider_config()
    client = DeepSeekClient(
        api_key=api_key,
        base_url=pc.base_url or "https://api.deepseek.com",
        timeout_seconds=float(pc.timeout),
    )
    handle = EngineHandle()
    model = config.model or config.default_text_model
    engine = await Engine.create(handle, client, config=config, default_model=model)
    engine_task = asyncio.create_task(engine.run())

    try:
        await handle.send_message(prompt)
        async for event in handle.events():
            if isinstance(event, TextDeltaEvent):
                print(event.text, end="", flush=True)
            elif isinstance(event, ToolCallEvent):
                tc = event.tool_call
                typer.echo(f"\n[tool: {tc.name}]", err=True)
            elif isinstance(event, ToolResultEvent):
                status = "ok" if event.success else "error"
                typer.echo(f"[tool result: {status}]", err=True)
            elif isinstance(event, ErrorEvent):
                typer.echo(f"\nError: {event.message}", err=True)
                break
            elif isinstance(event, TurnCompleteEvent):
                print()
                break
    finally:
        engine_task.cancel()
        await engine.shutdown_session()
