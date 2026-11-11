"""The product runtime on a disposable home, so evals never open the user's threads."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from deepseek_tui.config.loader import ConfigLoader
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--provider")
    parser.add_argument("--model")
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
