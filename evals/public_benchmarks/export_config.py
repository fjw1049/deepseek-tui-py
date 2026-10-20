"""Private pipe used by the adapter; never redirect this module into a log."""

import json
import os
from pathlib import Path

from deepseek_tui.client.network import read_network_settings
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.state.secrets import SecretsManager
from evals.public_benchmarks.campaign import MANIFEST_ENV, campaign_settings


def export(manifest):
    settings = campaign_settings(manifest)
    provider, model = settings["provider"], settings["model"]
    original = ConfigLoader().load(
        provider=provider, model=model, workspace=Path.cwd(), no_project_config=True
    )
    pc = original.effective_provider_config().model_copy(deep=True)
    pc.api_key = None
    pc.temperature = settings["temperature"]
    pc.max_tokens = settings["max_output_tokens"]
    pc.timeout = 300
    cfg = Config(
        provider=provider,
        model=model,
        api_key=SecretsManager().resolve_api_key(original),
        providers={provider: pc},
        sandbox_mode="danger-full-access",
        approval_policy="never",
        features=FeatureConfig(
            subagents=False, tasks=False, web_search=False, mcp=False, plugins=False
        ),
    )
    return {
        "config": cfg.model_dump(mode="json"),
        "network": read_network_settings().model_dump(mode="json"),
        "request_limit": settings["request_limit"],
        "idle_timeout_sec": settings["idle_timeout"],
        "task_timeout_sec": settings["task_timeout"],
        "max_output_tokens": settings["max_output_tokens"],
        "top_p": settings["top_p"],
    }


if __name__ == "__main__":
    # The supervisor names the campaign manifest; without one, the first campaign's values.
    path = os.environ.get(MANIFEST_ENV)
    print(json.dumps(export(json.loads(Path(path).read_text()) if path else {})))
