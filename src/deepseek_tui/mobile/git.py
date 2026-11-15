"""Thread-scoped bridge to the existing desktop Git service bundle."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from deepseek_tui.mobile.files import _parts, _root
from deepseek_tui.workspace.project_lease import ProjectLease, ThreadLease

router = APIRouter(prefix="/v1/threads/{thread_id}/git", tags=["mobile-git"])
_WRITES = {"stage", "unstage", "commit", "switch", "createBranch", "pull", "push"}
_SCOPES = {"working-tree", "staged", "unstaged"}
_locks: dict[str, asyncio.Lock] = {}
_RUNTIME_ROOT = str(Path(__file__).resolve().parents[3])


def _safe(root: Path, raw: str, thread_id: str) -> None:
    parts = _parts(raw, thread_id)
    if not parts:
        raise HTTPException(400, "Select individual files")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise HTTPException(403, "Symbolic links are unavailable through mobile Git")
    if not path.resolve().is_relative_to(root):
        raise HTTPException(403, "File is outside the conversation workspace")
    if path.is_dir():
        raise HTTPException(400, "Select individual files, not directories")


async def _invoke(root: Path, action: str, **args) -> dict:
    helper = os.environ.get("DEEPSEEK_MOBILE_GIT_HELPER", "").strip()
    if not helper or not await asyncio.to_thread(Path(helper).is_file):
        raise HTTPException(
            503, "Build and configure the desktop Git helper on this computer first"
        )
    proc = await asyncio.create_subprocess_exec(
        os.environ.get("DEEPSEEK_NODE", "node"),
        helper,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        # Retain the desktop development-checkout branch-switch protection.
        env={
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "ELECTRON_RENDERER_URL": "mobile-runtime",
            "DEEPSEEK_REPO_ROOT": _RUNTIME_ROOT,
        },
    )
    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(
                json.dumps({"workspace": str(root), "action": action, **args}).encode()
            ),
            timeout=100,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    if len(stdout) > 4 * 1024 * 1024:
        raise HTTPException(413, "Git result is too large for mobile preview")
    try:
        result = json.loads(stdout)
    except ValueError as exc:
        raise HTTPException(502, "Git helper returned an invalid response") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        raise HTTPException(
            409,
            result.get("message", "Git operation failed")
            if isinstance(result, dict)
            else "Git operation failed",
        )
    return result


def _filter(result: dict, root: Path, thread_id: str) -> dict:
    hidden = 0
    for key in ("files", "stagedFiles", "unstagedFiles"):
        if key not in result:
            continue
        visible = []
        for file in result[key]:
            try:
                _safe(root, file["path"], thread_id)
            except HTTPException:
                hidden += 1
                continue
            # The existing service already provides a separate selected-file diff.
            visible.append({**file, "patch": ""})
        result[key] = visible
    result["has_hidden_files"] = hidden > 0
    return result


def _session_paths(request: Request, thread_id: str) -> set[str]:
    """Use the same persisted turn deltas as the conversation change viewer."""
    paths: set[str] = set()
    for turn in request.app.state.thread_manager.store.list_turns_for_thread(thread_id):
        snapshot = turn.diff_snapshot or {}
        for file in snapshot.get("files", []):
            for key in ("path", "old_path"):
                path = file.get(key)
                if isinstance(path, str) and path:
                    paths.add(path)
    return paths


@router.get("/{action}")
async def read_git(
    request: Request,
    thread_id: str,
    action: str,
    path: str = "",
    scope: str = "working-tree",
    untracked: bool = False,
    session_only: bool = False,
) -> dict:
    if action not in {"branches", "changes", "diff"} or scope not in _SCOPES:
        raise HTTPException(400, "Unsupported Git query")
    root = _root(request, thread_id)
    session_paths = _session_paths(request, thread_id) if session_only else None
    if action == "diff":
        _safe(root, path, thread_id)
        if session_paths is not None and path not in session_paths:
            raise HTTPException(403, "File is not recorded in this conversation")
    try:
        result = await _invoke(root, action, path=path, scope=scope, untracked=untracked)
    except asyncio.TimeoutError as exc:
        raise HTTPException(504, "Git query timed out") from exc
    if action == "changes":
        result = _filter(result, root, thread_id)
        if session_paths is not None:
            for key in ("files", "stagedFiles", "unstagedFiles"):
                if key in result:
                    result[key] = [file for file in result[key] if file["path"] in session_paths]
        result["session_only"] = session_only
    return result


@router.post("/{action}")
async def write_git(request: Request, thread_id: str, action: str) -> dict:
    if action not in _WRITES:
        raise HTTPException(400, "Unsupported Git action")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 24000:
            raise HTTPException(413, "Git action request is too large")
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, "Invalid Git request") from exc
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise HTTPException(409, "Review and explicitly confirm the Git operation")
    root = _root(request, thread_id)
    args = {}
    session_only = body.get("session_only") is True
    if session_only and action not in {"stage", "unstage", "commit"}:
        raise HTTPException(400, "Branch and remote actions apply to the repository")
    if action in {"stage", "unstage"} or (action == "commit" and ("paths" in body or session_only)):
        paths = body.get("paths")
        if not isinstance(paths, list) or not paths or len(paths) > 100:
            raise HTTPException(400, "Select between 1 and 100 files")
        for path in paths:
            if not isinstance(path, str):
                raise HTTPException(400, "Invalid file path")
            _safe(root, path, thread_id)
        args["paths"] = paths
    if action == "commit":
        message = body.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 4000:
            raise HTTPException(400, "Enter a commit message (maximum 4000 characters)")
        args["message"] = message
    if action in {"switch", "createBranch"}:
        branch = body.get("branch")
        if (
            not isinstance(branch, str)
            or not branch.strip()
            or branch.startswith("-")
            or len(branch) > 200
        ):
            raise HTTPException(400, "Enter a valid branch name")
        args["branch"] = branch
    async with _locks.setdefault(str(root), asyncio.Lock()):
        manager = request.app.state.thread_manager
        if await manager.is_thread_turn_active(thread_id):
            raise HTTPException(409, "Stop the active conversation turn before changing Git state")
        thread_lease, project_lease = ThreadLease(thread_id), ProjectLease(root)
        if not await thread_lease.acquire(nonblocking=True):
            raise HTTPException(409, "Conversation has an active operation")
        try:
            if not await project_lease.acquire(nonblocking=True):
                raise HTTPException(409, "Project is being updated; retry after it finishes")
            try:
                if session_only:
                    allowed = _session_paths(request, thread_id)
                    if any(path not in allowed for path in args["paths"]):
                        raise HTTPException(403, "Selected files are not recorded in this conversation")
                if action == "commit" and "paths" not in args:
                    staged = await _invoke(root, "changes", scope="staged")
                    for file in staged.get("files", []):
                        _safe(root, file["path"], thread_id)
                return await _invoke(root, action, **args)
            finally:
                project_lease.release()
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                504, "Git action timed out; refresh state before deciding what to do"
            ) from exc
        finally:
            thread_lease.release()
