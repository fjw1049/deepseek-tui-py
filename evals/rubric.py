"""Deterministic checks on what a session left behind.

These run on a copy of the trial workspace, against facts a reader could verify by
hand. Anything needing judgement belongs in the case's rubric for the reviewer.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from evals.schema import EvalCase

_COMMAND_TIMEOUT_SECONDS = 30
_PAGE_TIMEOUT_SECONDS = 60
_XML_TEXT = re.compile(r"<(?:w:t|a:t|t|v)(?:\s[^>]*)?>([^<]*)</")


def task_boundary(case: EvalCase) -> str:
    rules = ["本任务的输入资料和产物均在当前工作目录。"
             "只修改当前目录及其子目录，不要修改用户已有资料。"]
    rules.append("允许在当前工作目录的隔离环境中安装任务所需依赖；禁止全局安装。"
                 if "install_dependencies" in case.allowed_actions else "不要安装软件。")
    rules.append("允许在当前工作目录的测试仓库中提交 Git；禁止推送及破坏已有改动。"
                 if "git_commit" in case.allowed_actions else "不要提交 Git。")
    rules.append("不要对外发布、发消息、付款或创建长期定时任务。网页可读取公开资料。"
                 "若缺少权限或能力如实说明，不要伪造成功。\n")
    return "".join(rules)


def validate_criteria(case: EvalCase, verdict: dict[str, Any]) -> None:
    expected = set(range(1, len(case.expect.get("rubric", [])) + 1))
    if not expected:
        return
    criteria = verdict.get("criteria", [])
    if (len(criteria) != len(expected) or {c.get("id") for c in criteria} != expected
            or any(not isinstance(c.get("met"), bool) or not c.get("evidence", "").strip()
                   for c in criteria)):
        raise ValueError("judge criteria must cover every requirement once with evidence")
    if verdict["verdict"] == "pass" and any(not c["met"] for c in criteria):
        raise ValueError("judge pass contradicts unmet criteria")


def read_text(path: Path) -> str:
    """Text of a file, including what Office formats hold in their XML parts."""
    if path.suffix.lower() in {".docx", ".pptx", ".xlsx"}:
        try:
            with zipfile.ZipFile(path) as archive:
                parts = [
                    archive.read(name).decode("utf-8", "replace")
                    for name in sorted(archive.namelist())
                    if name.endswith(".xml") and "/theme/" not in name
                ]
        except (OSError, zipfile.BadZipFile):
            return ""
        return "\n".join(match for part in parts for match in _XML_TEXT.findall(part))
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _files(workspace: Path, pattern: str) -> list[Path]:
    # AGENTS.md is the harness's own boundary note, never something the agent produced.
    return sorted(
        path for path in workspace.glob(pattern) if path.is_file() and path.name != "AGENTS.md"
    )


def _contains(text: str, spec: dict[str, Any]) -> tuple[bool, list[str]]:
    missing = [term for term in spec.get("all_of", []) if term not in text]
    missing += [pattern for pattern in spec.get("patterns", []) if not re.search(pattern, text)]
    any_of = spec.get("any_of", [])
    if any_of and not any(term in text for term in any_of):
        missing.append(" | ".join(any_of))
    present = [term for term in spec.get("none_of", []) if term in text]
    return not missing and not present, missing + [f"不应出现：{term}" for term in present]


def _run_command(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="deepseek-eval-check-") as scratch:
        root = Path(scratch) / "workspace"
        shutil.copytree(workspace, root, symlinks=True)
        try:
            done = subprocess.run(
                spec["argv"],
                cwd=root,
                input=spec.get("stdin"),
                capture_output=True,
                text=True,
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"{type(exc).__name__}: {exc}"
    output = done.stdout + done.stderr
    expected = spec.get("expect_exit", 0)
    allowed = expected if isinstance(expected, list) else [expected]
    passed = done.returncode in allowed and all(
        term in done.stdout for term in spec.get("stdout_contains", [])
    )
    return passed, f"exit={done.returncode}\n{output[-800:]}"


def _page_loads(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """The largest page opens in a real browser with controls and no script errors."""
    pages = _files(workspace, spec["glob"])
    if not pages:
        return False, "没有页面文件"
    page = max(pages, key=lambda path: path.stat().st_size)
    try:
        done = subprocess.run(
            [sys.executable, "-m", "evals.page_probe", str(page), str(workspace)],
            capture_output=True, text=True, timeout=_PAGE_TIMEOUT_SECONDS,
        )
        if done.returncode:
            diagnostic = done.stderr.strip().splitlines()
            reason = diagnostic[-1][:400] if diagnostic else "无诊断输出"
            raise RuntimeError(f"页面验收器异常退出（{done.returncode}）：{reason}")
        report = json.loads(done.stdout.splitlines()[-1])
    except subprocess.TimeoutExpired:
        # A plain page opens in about a second; one that never settles is the page's fault.
        return False, f"{page.name}：{_PAGE_TIMEOUT_SECONDS} 秒内未完成加载"
    except (OSError, ValueError, IndexError) as exc:
        raise RuntimeError(f"页面验收器没有返回有效证据：{type(exc).__name__}") from exc
    controls, errors = report["controls"], report["errors"]
    detail = f"{page.name}：{controls} 个控件，{len(errors)} 个错误"
    if errors:
        detail += "\n" + str(errors[0].get("text", ""))[:300]
    return controls >= spec.get("min_controls", 1) and not errors, detail


def _check(
    spec: dict[str, Any], case: EvalCase, workspace: Path, answers: list[str]
) -> tuple[bool, str]:
    kind = spec["type"]
    if kind == "file_exists":
        found = _files(workspace, spec["glob"])
        return len(found) >= spec.get("min_count", 1), f"{len(found)} 个文件"
    if kind == "file_absent":
        found = _files(workspace, spec["glob"])
        return not found, ", ".join(p.name for p in found[:5])
    if kind == "file_contains":
        files = _files(workspace, spec["glob"])
        if spec.get("exclude_seeded"):
            seeded = set(case.setup.get("files", {}))
            for released in case.setup.get("release_before_turn", {}).values():
                seeded.update(released)
            files = [
                p for p in files
                if p.relative_to(workspace).as_posix() not in seeded
            ]
        passed, missing = _contains("\n".join(read_text(p) for p in files), spec)
        return bool(files) and passed, f"缺少：{missing}" if missing else f"{len(files)} 个文件"
    if kind == "unchanged":
        seeded = case.setup["files"]
        changed = [
            name for name in spec["paths"]
            if not (workspace / name).is_file() or read_text(workspace / name) != seeded[name]
        ]
        return not changed, f"已改动：{changed}" if changed else ""
    if kind == "answer_contains":
        passed, missing = _contains(answers[-1] if answers else "", spec)
        return passed, f"未满足：{missing}" if missing else ""
    if kind == "command":
        return _run_command(workspace, spec)
    if kind == "page_loads":
        return _page_loads(workspace, spec)
    raise ValueError(f"unknown check type: {kind}")


CHECK_TYPES = {
    "file_exists", "file_absent", "file_contains", "unchanged", "answer_contains", "command",
    "page_loads",
}


def run_checks(case: EvalCase, workspace: Path, answers: list[str]) -> list[dict[str, Any]]:
    results = []
    for spec in case.expect.get("checks", []):
        passed, detail = _check(spec, case, workspace, answers)
        results.append(
            {
                "name": spec["name"],
                "passed": passed,
                "critical": spec.get("critical", True),
                "release_blocker": spec.get("release_blocker", spec["type"] == "unchanged"),
                "detail": detail,
            }
        )
    return results
