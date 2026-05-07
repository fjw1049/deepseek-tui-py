from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.patch_engine import (
    MAX_FUZZ,
    ApplyPatchError,
    FilePatch,
    FileSummary,
    HunkApplyStats,
    apply_hunks_to_lines,
    parse_unified_diff,
    parse_unified_diff_files,
)


class ApplyPatchTool(ToolSpec):
    def name(self) -> str:
        return "apply_patch"

    def description(self) -> str:
        return (
            "Apply a unified diff patch to files. Supports multi-hunk patches "
            "with fuzzy matching and cumulative offset tracking."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "patch": {"type": "string"},
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
                "fuzz": {"type": "integer"},
                "create_if_missing": {"type": "boolean"},
            },
            "oneOf": [
                {"required": ["patch"]},
                {"required": ["changes"]},
            ],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [
            ToolCapability.WRITES_FILES,
            ToolCapability.SANDBOXABLE,
            ToolCapability.REQUIRES_APPROVAL,
        ]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.SUGGEST

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        fuzz_raw = input_data.get("fuzz", MAX_FUZZ)
        if not isinstance(fuzz_raw, int) or fuzz_raw < 0:
            raise ToolError("fuzz must be a non-negative integer")
        fuzz = min(fuzz_raw, MAX_FUZZ)
        create_if_missing = bool(input_data.get("create_if_missing", False))

        # Full-file replacements path.
        if "changes" in input_data and input_data["changes"] is not None:
            return _apply_changes(input_data["changes"], context)

        patch_text = input_data.get("patch")
        if not isinstance(patch_text, str) or not patch_text.strip():
            raise ToolError("patch must be a non-empty string")

        path_override = input_data.get("path")
        if path_override is not None and not isinstance(path_override, str):
            raise ToolError("path must be a string")

        try:
            if path_override:
                hunks = parse_unified_diff(patch_text)
                if not hunks:
                    raise ToolError("Patch did not contain any hunks (`@@ ... @@`).")
                file_patches = [
                    FilePatch(
                        path=path_override,
                        hunks=hunks,
                        delete_after=False,
                        create_if_missing=create_if_missing,
                    )
                ]
            else:
                file_patches = parse_unified_diff_files(
                    patch_text, create_if_missing=create_if_missing
                )
                if not file_patches:
                    raise ToolError(
                        "No valid file patches found. Add `---`/`+++` headers or"
                        " provide `path`."
                    )
        except ApplyPatchError as exc:
            raise ToolError(str(exc)) from exc

        return _apply_file_patches(file_patches, context, fuzz=fuzz)


def _apply_changes(raw: Any, context: ToolContext) -> ToolResult:
    if not isinstance(raw, list):
        raise ToolError("changes must be a list")

    touched: list[str] = []
    summaries: list[FileSummary] = []
    for idx, change in enumerate(raw):
        if not isinstance(change, dict):
            raise ToolError(f"changes[{idx}] must be an object")
        path = change.get("path")
        content = change.get("content")
        if not isinstance(path, str) or not path.strip():
            raise ToolError(f"changes[{idx}].path must be a non-empty string")
        if not isinstance(content, str):
            raise ToolError(f"changes[{idx}].content must be a string")
        target = context.resolve_path(path)
        created = not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        touched.append(path)
        summaries.append(
            FileSummary(
                path=path,
                hunks=0,
                hunks_applied=0,
                fuzz_used=0,
                hunks_with_fuzz=0,
                created=created,
                deleted=False,
            )
        )

    return _build_result(
        files_applied=len(touched),
        files_total=len(touched),
        agg=HunkApplyStats(),
        touched=touched,
        summaries=summaries,
    )


def _apply_file_patches(
    file_patches: list[FilePatch], context: ToolContext, fuzz: int
) -> ToolResult:
    agg = HunkApplyStats()
    touched: list[str] = []
    summaries: list[FileSummary] = []
    files_applied = 0

    for patch in file_patches:
        target = context.resolve_path(patch.path)
        file_stats = HunkApplyStats()

        if patch.delete_after:
            if target.exists():
                target.unlink()
                summaries.append(
                    FileSummary(
                        path=patch.path,
                        hunks=len(patch.hunks),
                        hunks_applied=0,
                        fuzz_used=0,
                        hunks_with_fuzz=0,
                        created=False,
                        deleted=True,
                    )
                )
                files_applied += 1
                touched.append(patch.path)
            continue

        created = False
        if not target.exists():
            if not patch.create_if_missing:
                raise ToolError(
                    f"File not found: {patch.path}. Set create_if_missing=true"
                    " to create new files."
                )
            created = True
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")

        original = target.read_text(encoding="utf-8")
        trailing_newline = original.endswith("\n")
        lines = original.splitlines()
        try:
            file_stats = apply_hunks_to_lines(lines, patch.hunks, fuzz=fuzz)
        except ApplyPatchError as exc:
            raise ToolError(f"{patch.path}: {exc}") from exc

        out = "\n".join(lines)
        if trailing_newline or (out and not out.endswith("\n")):
            out += "\n"
        target.write_text(out, encoding="utf-8")

        agg.hunks_applied += file_stats.hunks_applied
        agg.fuzz_used += file_stats.fuzz_used
        agg.hunks_with_fuzz += file_stats.hunks_with_fuzz
        summaries.append(
            FileSummary(
                path=patch.path,
                hunks=len(patch.hunks),
                hunks_applied=file_stats.hunks_applied,
                fuzz_used=file_stats.fuzz_used,
                hunks_with_fuzz=file_stats.hunks_with_fuzz,
                created=created,
                deleted=False,
            )
        )
        files_applied += 1
        touched.append(patch.path)

    return _build_result(
        files_applied=files_applied,
        files_total=len(file_patches),
        agg=agg,
        touched=touched,
        summaries=summaries,
    )


def _build_result(
    *,
    files_applied: int,
    files_total: int,
    agg: HunkApplyStats,
    touched: list[str],
    summaries: list[FileSummary],
) -> ToolResult:
    hunks_total = sum(s.hunks for s in summaries)
    message = _format_summary(
        files_applied=files_applied,
        files_total=files_total,
        agg=agg,
        hunks_total=hunks_total,
    )
    return ToolResult(
        success=True,
        content=message,
        metadata={
            "files_applied": files_applied,
            "files_total": files_total,
            "hunks_applied": agg.hunks_applied,
            "hunks_total": hunks_total,
            "fuzz_used": agg.fuzz_used,
            "hunks_with_fuzz": agg.hunks_with_fuzz,
            "touched_files": touched,
            "file_summaries": [asdict(s) for s in summaries],
            "message": message,
        },
    )


def _format_summary(
    *, files_applied: int, files_total: int, agg: HunkApplyStats, hunks_total: int
) -> str:
    fuzz_note = (
        f" (fuzz used on {agg.hunks_with_fuzz} hunk(s), total {agg.fuzz_used})"
        if agg.hunks_with_fuzz
        else ""
    )
    return (
        f"Applied {files_applied}/{files_total} file(s), "
        f"{agg.hunks_applied}/{hunks_total} hunk(s){fuzz_note}"
    )


class DiagnosticsTool(ToolSpec):
    def name(self) -> str:
        return "diagnostics"

    def description(self) -> str:
        return "Collect environment diagnostics for debugging."

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        import platform
        import sys

        info = {
            "python": sys.version,
            "platform": platform.platform(),
            "cwd": str(context.working_directory),
        }
        lines = [f"{k}: {v}" for k, v in info.items()]
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata=info,
        )


class ProjectMapTool(ToolSpec):
    def name(self) -> str:
        return "project_map"

    def description(self) -> str:
        return "Generate a directory tree of the project."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY]

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        rel_raw = input_data.get("path") or "."
        if not isinstance(rel_raw, str):
            raise ToolError("path must be a string")
        root = context.resolve_path(rel_raw)
        if not root.is_dir():
            raise ToolError(f"Not a directory: {rel_raw}")
        max_depth = input_data.get("max_depth", 3)
        if not isinstance(max_depth, int):
            raise ToolError("max_depth must be an integer")
        lines: list[str] = []
        _walk(root, root, lines, max_depth, 0)
        return ToolResult(
            success=True,
            content="\n".join(lines),
            metadata={"root": str(root), "entries": len(lines)},
        )


def _walk(base: Path, current: Path, lines: list[str], max_depth: int, depth: int) -> None:
    if depth > max_depth:
        return
    indent = "  " * depth
    entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            lines.append(f"{indent}{entry.name}/")
            _walk(base, entry, lines, max_depth, depth + 1)
        else:
            lines.append(f"{indent}{entry.name}")
