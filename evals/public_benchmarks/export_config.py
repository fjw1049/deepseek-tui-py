"""Private pipe used by the adapter; never redirect this module into a log."""

import json
from pathlib import Path

from deepseek_tui.client.network import read_network_settings
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.state.secrets import SecretsManager

if __name__ == "__main__":
    original = ConfigLoader().load(
        provider="endpoint", model="glm-5-3", workspace=Path.cwd(), no_project_config=True
    )
    pc = original.effective_provider_config().model_copy(deep=True)
    pc.api_key = None
    pc.temperature = 1.0
    pc.max_tokens = 65536
    pc.timeout = 300
    cfg = Config(
        provider="endpoint",
        model="glm-5-3",
        api_key=SecretsManager().resolve_api_key(original),
        providers={"endpoint": pc},
        sandbox_mode="danger-full-access",
        approval_policy="never",
        features=FeatureConfig(
            subagents=False, tasks=False, web_search=False, mcp=False, plugins=False
        ),
    )
    print(
        json.dumps(
            {
                "config": cfg.model_dump(mode="json"),
                "network": read_network_settings().model_dump(mode="json"),
                "request_limit": 600,
                "idle_timeout_sec": 900,
                "task_timeout_sec": 21600,
            }
        )
    )
