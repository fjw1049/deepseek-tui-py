"""Install a frozen checkout in the official task container, then use its Engine."""

import asyncio
import json
import shlex
from pathlib import Path

from harbor.agents.installed.base import BaseInstalledAgent


class WorkbenchAgent(BaseInstalledAgent):
    @staticmethod
    def name():
        return "deepseek-workbench"

    def __init__(self, *args, bundle, repo, bootstrap_dir, **kwargs):
        super().__init__(*args, **kwargs)
        self.bundle, self.repo, self.bootstrap_dir = Path(bundle), Path(repo), Path(bootstrap_dir)

    async def install(self, environment):
        await environment.upload_file(self.bundle, "/installed-agent/source.tar.gz")
        arch = (await environment.exec(command="uname -m", user="root")).stdout.strip()
        await environment.upload_file(
            self.bootstrap_dir / f"uv-{arch}.tar.gz", "/installed-agent/uv.tar.gz"
        )
        command = (
            "cd /installed-agent && tar xzf source.tar.gz && "
            "tar xzf uv.tar.gz --strip-components=1 && "
            "UV_PYTHON_INSTALL_DIR=/installed-agent/python ./uv venv "
            "--python 3.12 /installed-agent/venv && "
            "UV_PYTHON_INSTALL_DIR=/installed-agent/python ./uv pip install "
            "--python /installed-agent/venv/bin/python /installed-agent/source "
            "> /logs/agent/install.log 2>&1 && "
            "./uv pip freeze --python /installed-agent/venv/bin/python "
            "> /logs/agent/runtime-packages.txt && "
            "mkdir -p /installed-agent/state && chmod 777 /installed-agent/state"
        )
        await self.exec_as_root(environment, command=command, timeout_sec=900)

    async def run(self, instruction, environment, context):
        exporter = await asyncio.create_subprocess_exec(
            str(self.repo / ".venv/bin/python"),
            "-m",
            "evals.public_benchmarks.export_config",
            cwd=self.repo,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        private, error = await asyncio.wait_for(exporter.communicate(), 30)
        if exporter.returncode:
            raise RuntimeError("Private configuration export failed")
        await self._upload_config_text(
            environment,
            content=private.decode(),
            remote_path="/installed-agent/private.json",
            filename="private.json",
        )
        await self._upload_config_text(
            environment,
            content=instruction,
            remote_path="/installed-agent/instruction.txt",
            filename="instruction.txt",
        )
        await self.exec_as_root(environment, command="chmod 600 /installed-agent/private.json")
        logs = shlex.quote(str(self.environment_logs_dir))
        await self.exec_as_agent(
            environment,
            command=(
                "/installed-agent/venv/bin/python "
                "/installed-agent/source/evals/public_benchmarks/worker.py "
                f"/installed-agent/private.json /installed-agent/instruction.txt {logs} "
                f"> {logs}/worker-console.log 2>&1"
            ),
            timeout_sec=21700,
        )
        status = await environment.exec(command=f"cat {logs}/status.json")
        data = json.loads(status.stdout)
        context.n_input_tokens = data["usage"]["input_tokens"]
        context.n_output_tokens = data["usage"]["output_tokens"]
        context.n_cache_tokens = data["usage"]["cache_read_input_tokens"]
        context.metadata = {
            "runtime_state": data["state"],
            "requests": data["requests"],
            "metered_requests": data["metered_requests"],
        }
