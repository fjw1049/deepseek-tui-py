"""The product runtime on a disposable home, so evals never open the user's threads."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config
from deepseek_tui.integrations import skills
from deepseek_tui.server import AppServerOptions, run_http

_USER_SKILL_DIRECTORIES = (
    "agents_global_skills_dir", "claude_global_skills_dir", "cursor_global_skills_dir",
    "codex_global_skills_dir", "_user_ecosystem_skills_dir",
)


def hide_user_skills() -> None:
    """Skills in the developer's home must not steer a trial.

    Replacing HOME instead would also move Chrome's, which then stalls on local pages.
    """
    for name in _USER_SKILL_DIRECTORIES:
        setattr(skills, name, lambda *_args: None)


def install_meter(path: Path, max_requests: int, max_output_tokens: int) -> None:
    """Meter clients in this disposable process, including preflight and retries."""
    from deepseek_tui.client import factory
    from evals.harness import HarnessContext
    from evals.harness.budget import BudgetedClient

    context = HarnessContext(workspace=str(path.parent), remaining_live_requests=max_requests,
                             max_output_tokens=max_output_tokens)
    original = factory.build_llm_client

    def save() -> None:
        snapshot = {"requests": context.requests, "metered_requests": context.metered_requests,
                    "priced_requests": context.priced_requests, "known_cost_usd": context.cost_usd,
                    "usage": context.usage}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot), encoding="utf-8")
        temporary.replace(path)

    def build(config: Config) -> LLMClient:
        return BudgetedClient(original(config), context, on_update=save)

    factory.build_llm_client = build
    save()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--max-product-requests", type=int, default=20)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    args = parser.parse_args()
    config = ConfigLoader().load(
        provider=args.provider,
        model=args.model,
        workspace=args.workspace,
        no_project_config=True,
    )
    # An eval has nobody to answer: a question must not wait out the turn timeout.
    config.unattended = True
    hide_user_skills()
    install_meter(args.workspace / "product-usage.json", args.max_product_requests,
                  args.max_output_tokens)
    from evals.compression_experiment import configure_compression

    configure_compression()
    options = AppServerOptions(
        host="127.0.0.1",
        port=args.port,
        http_mode=True,
        working_directory=args.workspace,
        auth_token=args.token,
    )
    asyncio.run(run_http(options, config=config))


if __name__ == "__main__":
    main()
