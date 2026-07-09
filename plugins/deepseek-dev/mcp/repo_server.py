#!/usr/bin/env python3
"""deepseek-dev MCP server — read-only repo helpers over stdio JSON-RPC.

Framing matches deepseek_tui StdioTransport: one JSON object per line.
No third-party deps. Tools are intentionally read-only (permissions: read).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "repo_context",
        "description": (
            "Return branch, short git status, and key DeepSeek-TUI paths. "
            "Use at the start of a development task for orientation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace root; defaults to cwd.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "locate_files",
        "description": (
            "Find files under the workspace matching a glob pattern "
            "(e.g. '**/plugins.py', 'packages/workbench/**/*Plugins*'). "
            "Returns up to 40 paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern relative to workspace root.",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace root; defaults to cwd.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "suggest_tests",
        "description": (
            "Suggest pytest targets for a source file path under "
            "src/deepseek_tui/ (e.g. integrations/plugins.py → "
            "tests/test_plugins.py)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Source path relative to repo root or absolute.",
                },
                "workspace": {
                    "type": "string",
                    "description": "Optional workspace root; defaults to cwd.",
                },
            },
            "required": ["path"],
        },
    },
]


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(req_id, result) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
    )


def _text(text: str) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }


def _workspace(args: dict) -> Path:
    raw = args.get("workspace") or os.environ.get("DEEPSEEK_WORKSPACE") or os.getcwd()
    return Path(raw).expanduser().resolve()


def _run_git(ws: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ws,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(git failed: {exc})"
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 and not out:
        err = (proc.stderr or "").strip()
        return f"(git exit {proc.returncode}: {err})"
    return out


def tool_repo_context(args: dict) -> dict:
    ws = _workspace(args)
    branch = _run_git(ws, "rev-parse", "--abbrev-ref", "HEAD")
    status = _run_git(ws, "status", "-sb")
    key_paths = [
        "src/deepseek_tui/integrations/plugins.py",
        "src/deepseek_tui/engine/orchestrator/core.py",
        "src/deepseek_tui/server/routes.py",
        "packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx",
        "docs/PLUGIN_SYSTEM.md",
        "plugins/deepseek-dev/",
        "tests/test_plugins.py",
    ]
    existing = [p for p in key_paths if (ws / p).exists() or p.endswith("/")]
    lines = [
        f"workspace: {ws}",
        f"branch: {branch}",
        "git status:",
        status or "(clean / unavailable)",
        "",
        "key paths:",
        *[f"  - {p}" for p in existing],
        "",
        "composer focus tips:",
        "  /deepseek-dev  /workbench-ui  /plugin-system  /python-runtime",
    ]
    return _text("\n".join(lines))


def tool_locate_files(args: dict) -> dict:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        return {
            "content": [{"type": "text", "text": "pattern is required"}],
            "isError": True,
        }
    ws = _workspace(args)
    matches: list[str] = []
    for path in sorted(ws.glob(pattern.strip())):
        if path.is_file():
            try:
                matches.append(str(path.relative_to(ws)))
            except ValueError:
                matches.append(str(path))
        if len(matches) >= 40:
            break
    if not matches:
        return _text(f"No files matched {pattern!r} under {ws}")
    return _text(f"Matched {len(matches)} file(s) under {ws}:\n" + "\n".join(matches))


def tool_suggest_tests(args: dict) -> dict:
    raw = args.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return {
            "content": [{"type": "text", "text": "path is required"}],
            "isError": True,
        }
    ws = _workspace(args)
    path = Path(raw.strip())
    if path.is_absolute():
        try:
            rel = path.relative_to(ws)
        except ValueError:
            rel = path
    else:
        rel = path

    suggestions: list[str] = []
    s = str(rel).replace("\\", "/")
    name = Path(s).stem

    candidates = [
        ws / "tests" / f"test_{name}.py",
        ws / "tests" / "contract" / f"test_{name}.py",
        ws / "tests" / "contract" / f"test_{name}_api.py",
    ]
    if "plugins" in s:
        candidates.insert(0, ws / "tests" / "test_plugins.py")
        candidates.insert(1, ws / "tests" / "contract" / "test_plugins_api.py")
    if "skills" in s:
        candidates.append(ws / "tests" / "test_skills.py")
    if "mcp" in s:
        candidates.append(ws / "tests" / "test_mcp.py")

    for c in candidates:
        if c.exists():
            try:
                suggestions.append(str(c.relative_to(ws)))
            except ValueError:
                suggestions.append(str(c))

    # de-dupe preserving order
    seen: set[str] = set()
    uniq = []
    for item in suggestions:
        if item not in seen:
            seen.add(item)
            uniq.append(item)

    if not uniq:
        guess = f"tests/test_{name}.py"
        return _text(
            f"No existing test file found for {s}.\n"
            f"Suggested new target: {guess}\n"
            f"Run: uv run pytest {guess} -q"
        )
    cmds = "\n".join(f"uv run pytest {p} -q" for p in uniq)
    return _text(f"Source: {s}\nSuggested tests:\n" + "\n".join(uniq) + f"\n\n{cmds}")


HANDLERS = {
    "repo_context": tool_repo_context,
    "locate_files": tool_locate_files,
    "suggest_tests": tool_suggest_tests,
}


def _handle(msg: dict) -> None:
    method = msg.get("method")
    req_id = msg.get("id")
    if req_id is None:
        return

    if method == "initialize":
        _result(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "deepseek-dev-repo", "version": "0.1.0"},
            },
        )
    elif method == "tools/list":
        _result(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            _error(req_id, -32601, f"unknown tool: {name}")
            return
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        _result(req_id, handler(args))
    else:
        _error(req_id, -32601, f"method not found: {method}")


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            _handle(msg)


if __name__ == "__main__":
    main()
