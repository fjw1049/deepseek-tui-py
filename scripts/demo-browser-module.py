"""Launch an isolated Workbench + Octop browser demo without a model API call."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7894)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args()
    home = args.state_dir or Path(tempfile.mkdtemp(prefix="workbench-browser-demo-"))
    home.mkdir(parents=True, exist_ok=True)
    if (home / "settings.json").exists() and not (home / "demo-thread.txt").exists():
        raise RuntimeError("Use an empty directory or a previous browser-demo directory")
    workspace = home / "workspace"
    workspace.mkdir(exist_ok=True)
    os.environ["DEEPSEEK_HOME"] = str(home)
    os.environ["DEEPSEEK_PYTHON"] = sys.executable
    os.environ["PYTHONPATH"] = str(ROOT / "src")
    os.environ["DEEPSEEK_GUI_BUILT_RENDERER"] = "1"
    os.environ.pop("ELECTRON_RENDERER_URL", None)
    os.environ.pop("VITE_DEV_SERVER_URL", None)
    os.environ.pop("ELECTRON_RUN_AS_NODE", None)
    token = secrets.token_urlsafe(32)
    os.environ["DEEPSEEK_RUNTIME_TOKEN"] = token
    settings = {
        "version": 1,
        "locale": "zh",
        "theme": "light",
        "workspaceRoot": str(workspace),
        "deepseek": {
            "port": args.port,
            "autoStart": False,
            "runtimeToken": token,
            "apiKey": "local-demo-no-model",
            "baseUrl": "http://127.0.0.1:9",
        },
    }
    (home / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    (home / "runtime.token").write_text(token, encoding="utf-8")
    (home / "runtime.token").chmod(0o600)
    (home / "config.toml").write_text(
        'api_key = "local-demo-no-model"\nbase_url = "http://127.0.0.1:9"\n'
        "[features]\nmcp = false\nautomations = false\n",
        encoding="utf-8",
    )

    import uvicorn

    from deepseek_tui.config.models import Config, FeatureConfig
    from deepseek_tui.server.app import build_fastapi_app
    from deepseek_tui.server.runtime import AppRuntime
    from deepseek_tui.server.threads.models import CreateThreadRequest

    config = Config(
        api_key="local-demo-no-model",
        base_url="http://127.0.0.1:9",
        features=FeatureConfig(mcp=False, tasks=False, subagents=False, automations=False),
    )
    runtime = AppRuntime(config=config, working_directory=workspace)
    app = build_fastapi_app(runtime, http_mode=True, auth_token=token)
    original_lifespan = app.router.lifespan_context
    gui = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal gui
        async with original_lifespan(app):
            thread = await app.state.thread_manager.create_thread(
                CreateThreadRequest(title="浏览器模块演示 · build_1004", workspace=str(workspace))
            )
            (home / "demo-thread.txt").write_text(thread.id, encoding="utf-8")
            if not args.no_gui:
                main_js = ROOT / "packages/workbench/out/main/index.js"
                electron = ROOT / "packages/workbench/node_modules/.bin/electron"
                if not main_js.exists():
                    raise RuntimeError(
                        "Build the GUI first: cd packages/workbench && npm run build"
                    )
                entry = home / "launch.cjs"
                entry.write_text(
                    "const {app}=require('electron');\n"
                    "app.setPath('userData'," + json.dumps(str(home / "electron")) + ");\n"
                    "app.setName('Workbench Browser Demo');\n"
                    "app.on('browser-window-created',(_,w)=>{"
                    "w.on('page-title-updated',e=>{e.preventDefault();"
                    "w.setTitle('build_1004 · 浏览器模块演示')});});\n"
                    "import(" + json.dumps(main_js.as_uri()) + ");\n",
                    encoding="utf-8",
                )
                gui = await asyncio.create_subprocess_exec(str(electron), str(entry), cwd=ROOT)
            print(f"Demo data: {home}", flush=True)
            print("打开演示对话 → 右侧 + → 预览 → Agent 浏览器 → 运行整组演示", flush=True)
            try:
                yield
            finally:
                if gui and gui.returncode is None:
                    gui.terminate()
                    try:
                        await asyncio.wait_for(gui.wait(), timeout=5)
                    except TimeoutError:
                        gui.kill()
                        await gui.wait()
                await runtime.shutdown()

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
