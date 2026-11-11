"""Freeze evaluated sources without checking out or modifying the user's worktree."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

PRODUCT_PATHS = ("src", "contracts", "pyproject.toml", "uv.lock")
EVALUATOR_PATHS = ("evals",)


def _included(name: str) -> bool:
    parts = Path(name).parts
    if any(p in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"} for p in parts):
        return False
    if name.endswith((".pyc", ".pyo")):
        return False
    if parts[0] == "evals":
        return name.endswith(".py") and len(parts) == 2 or (
            len(parts) > 2 and parts[1] in {"harness", "graders", "suites", "baselines"}
            and name.endswith((".py", ".yaml", ".json"))
        )
    return parts[0] in PRODUCT_PATHS


def _digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True,
    ).stdout


def _working_files(root: Path, paths: tuple[str, ...]) -> dict[str, bytes]:
    names = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                 "--", *paths).decode().split("\0")
    files = {}
    for name in sorted(set(names)):
        if not name or not _included(name):
            continue
        path = root / name
        if path.is_symlink():
            raise ValueError(f"source snapshots do not follow symlinks: {name}")
        if path.is_file():
            files[name] = path.read_bytes()
    return files


def tree_hash(root: Path) -> str:
    files = {}
    for prefix in (*PRODUCT_PATHS, *EVALUATOR_PATHS):
        path = root / prefix
        for entry in sorted(path.rglob("*") if path.is_dir() else [path]):
            name = entry.relative_to(root).as_posix()
            if not _included(name):
                continue
            if entry.is_symlink():
                raise ValueError(f"source snapshots do not follow symlinks: {name}")
            if entry.is_file():
                files[name] = entry.read_bytes()
    return _digest(files)


def freeze_source(root: Path, revision: str, destination: Path) -> dict[str, str]:
    """Use one revision's product and the current evaluator; never copy credentials."""
    evaluator = _working_files(root, EVALUATOR_PATHS)
    if revision == "working-tree":
        product = _working_files(root, PRODUCT_PATHS)
        commit = _git(root, "rev-parse", "HEAD").decode().strip()
    else:
        commit = _git(root, "rev-parse", "--verify", "--end-of-options",
                      f"{revision}^{{commit}}").decode().strip()
        archive = _git(root, "archive", commit, "--", *PRODUCT_PATHS)
        product = {}
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar:
                if not _included(member.name) or member.isdir():
                    continue
                if not member.isfile() or ".." in Path(member.name).parts:
                    raise ValueError(f"unsupported archive entry: {member.name}")
                stream = tar.extractfile(member)
                assert stream is not None
                product[member.name] = stream.read()
    if evaluator != _working_files(root, EVALUATOR_PATHS) or (
        revision == "working-tree" and product != _working_files(root, PRODUCT_PATHS)
    ):
        raise ValueError("source changed while freezing; retry with a stable working tree")
    files = {**product, **evaluator}
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    metadata = {
        "revision": revision, "git_commit": commit, "source_hash": _digest(files),
        "product_hash": _digest(product), "evaluator_hash": _digest(evaluator),
        "dependencies_hash": _digest({k: v for k, v in product.items()
                                      if k in {"pyproject.toml", "uv.lock"}}),
    }
    (destination / ".eval-snapshot.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata
