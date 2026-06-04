"""Procedural skill store for evolution writes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from deepseek_tui.evolution.safety import scan_memory_content

Scope = Literal["project", "user"]
Category = Literal["references", "templates", "scripts", "assets"]

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class SkillWriteResult:
    ok: bool
    message: str = ""
    path: str | None = None
    preview: str | None = None


class ProceduralSkillStore:
    def __init__(
        self,
        *,
        workspace: Path,
        default_scope: Scope = "project",
    ) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._default_scope = default_scope

    def skill_root(self, name: str, scope: Scope | None = None) -> Path:
        safe = self._safe_name(name)
        effective = scope or self._default_scope
        if effective == "user":
            from deepseek_tui.config.paths import user_skills_dir

            return user_skills_dir() / safe
        from deepseek_tui.config.paths import project_skills_dir

        return project_skills_dir(self._workspace) / safe

    def create(
        self,
        name: str,
        content: str,
        *,
        scope: Scope | None = None,
    ) -> SkillWriteResult:
        ok, reason = scan_memory_content(content)
        if not ok:
            return SkillWriteResult(ok=False, message=reason)
        root = self.skill_root(name, scope)
        if ".." in str(root):
            return SkillWriteResult(ok=False, message="invalid path")
        skill_md = root / "SKILL.md"
        if skill_md.exists():
            return SkillWriteResult(ok=False, message="skill already exists")
        self._validate_skill_md(content, name)
        root.mkdir(parents=True, exist_ok=True)
        self._atomic_write(skill_md, content)
        self._invalidate_cache()
        return SkillWriteResult(ok=True, message="created", path=str(skill_md))

    def patch(
        self,
        name: str,
        old_string: str,
        new_string: str,
        *,
        scope: Scope | None = None,
        replace_all: bool = False,
        file_path: str | None = None,
    ) -> SkillWriteResult:
        root = self.skill_root(name, scope)
        target = self._patch_target_path(root, file_path)
        if target is None:
            return SkillWriteResult(ok=False, message="invalid patch file path")
        if not target.exists():
            return SkillWriteResult(ok=False, message="file not found")
        text = target.read_text(encoding="utf-8")
        if old_string not in text:
            return SkillWriteResult(
                ok=False,
                message="old_string not found",
                preview=self._file_preview(text),
                path=str(target),
            )
        if replace_all:
            updated = text.replace(old_string, new_string)
        else:
            updated = text.replace(old_string, new_string, 1)
        ok, reason = scan_memory_content(updated)
        if not ok:
            return SkillWriteResult(ok=False, message=reason)
        self._atomic_write(target, updated)
        self._invalidate_cache()
        return SkillWriteResult(ok=True, message="patched", path=str(target))

    def edit(
        self,
        name: str,
        content: str,
        *,
        scope: Scope | None = None,
    ) -> SkillWriteResult:
        ok, reason = scan_memory_content(content)
        if not ok:
            return SkillWriteResult(ok=False, message=reason)
        skill_md = self.skill_root(name, scope) / "SKILL.md"
        if not skill_md.exists():
            return SkillWriteResult(ok=False, message="skill not found")
        self._validate_skill_md(content, name)
        self._atomic_write(skill_md, content)
        self._invalidate_cache()
        return SkillWriteResult(ok=True, message="edited", path=str(skill_md))

    def delete(self, name: str, *, scope: Scope | None = None) -> SkillWriteResult:
        root = self.skill_root(name, scope)
        if not root.exists():
            return SkillWriteResult(ok=False, message="skill not found")
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        if root.exists():
            root.rmdir()
        self._invalidate_cache()
        return SkillWriteResult(ok=True, message="deleted", path=str(root))

    def write_file(
        self,
        name: str,
        file_path: str,
        file_content: str,
        *,
        scope: Scope | None = None,
        category: Category | None = None,
    ) -> SkillWriteResult:
        root = self.skill_root(name, scope)
        target = self._resolve_skill_file_target(root, file_path, category=category)
        if target is None:
            return SkillWriteResult(ok=False, message="path traversal denied")
        ok, reason = scan_memory_content(file_content)
        if not ok:
            return SkillWriteResult(ok=False, message=reason)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, file_content)
        self._invalidate_cache()
        return SkillWriteResult(ok=True, message="wrote file", path=str(target))

    def remove_file(
        self,
        name: str,
        file_path: str,
        *,
        scope: Scope | None = None,
        category: Category | None = None,
    ) -> SkillWriteResult:
        root = self.skill_root(name, scope)
        target = self._resolve_skill_file_target(root, file_path, category=category)
        if target is None:
            return SkillWriteResult(ok=False, message="path traversal denied")
        if not target.is_file():
            return SkillWriteResult(ok=False, message="file not found")
        target.unlink()
        self._invalidate_cache()
        return SkillWriteResult(ok=True, message="removed file", path=str(target))

    def _resolve_skill_file_target(
        self,
        root: Path,
        file_path: str,
        *,
        category: Category | None = None,
    ) -> Path | None:
        rel = Path(file_path)
        if rel.is_absolute() or ".." in rel.parts:
            return None
        if category:
            target = root / category / rel.name
        else:
            target = root / rel
        try:
            resolved = target.resolve()
            root_resolved = root.resolve()
        except OSError:
            return None
        if not resolved.is_relative_to(root_resolved):
            return None
        return target

    def _safe_name(self, name: str) -> str:
        cleaned = name.strip().replace("..", "").replace("/", "-").replace("\\", "-")
        if not cleaned:
            raise ValueError("invalid skill name")
        return cleaned

    def _validate_skill_md(self, content: str, expected_name: str) -> None:
        match = _FRONTMATTER_RE.match(content)
        if not match:
            raise ValueError("SKILL.md requires YAML frontmatter")
        meta = yaml.safe_load(match.group(1)) or {}
        if not isinstance(meta, dict):
            raise ValueError("invalid frontmatter")
        if not meta.get("name") or not meta.get("description"):
            raise ValueError("frontmatter requires name and description")
        if str(meta["name"]).strip() != expected_name.strip():
            raise ValueError("frontmatter name must match skill name")

    def _patch_target_path(self, root: Path, file_path: str | None) -> Path | None:
        if not file_path or file_path.strip() in ("", "SKILL.md"):
            return root / "SKILL.md"
        resolved = self._resolve_skill_file_target(root, file_path.strip())
        return resolved

    @staticmethod
    def _file_preview(text: str, *, max_lines: int = 12) -> str:
        lines = text.splitlines()[:max_lines]
        preview = "\n".join(lines)
        if len(text.splitlines()) > max_lines:
            preview += "\n…"
        return preview

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        import os

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def _invalidate_cache(self) -> None:
        from deepseek_tui.skills import invalidate_skills_prompt_cache

        invalidate_skills_prompt_cache()
