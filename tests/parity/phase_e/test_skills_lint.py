"""Structural lint over every installed SKILL.md.

Per HANDOVER §四 / testing-development skill: this is a pure-local-IO
audit, no API calls. It walks the user-level skills directory, runs
five independent parametrized checks per skill, and writes a markdown
roll-up to ``tests/_skills_lint_report.md``.

**Severity model**:
- **error** — code-level guarantee. Failing here means the project
  parser is broken or the registry contract was violated. These
  ``pytest.fail`` so CI catches regressions.
- **warn**  — SKILL.md content-quality issue (frontmatter convention,
  truncation-prone block scalars, empty bodies). These do NOT fail
  the test — they're recorded in the report so the user can clean
  up the skill files on their own cadence. Failing on content would
  conflate "the engine is broken" with "a user-installed skill is
  shaped funny".

The five checks (each independent so failures localise):
  1. ``test_frontmatter_present`` (error) — file opens, has ``---``.
  2. ``test_required_fields``      (error) — ``name`` field present.
  3. ``test_name_matches_directory`` (warn) — drift is a content
                                       convention issue. ``load_skill``
                                       now uses the registry, not the
                                       directory name, so a mismatch no
                                       longer breaks lookup; it just
                                       confuses humans reading ``ls``.
  4. ``test_description_single_line`` (warn) — the parser is line-based
                                       (Rust parity), so block scalars
                                       silently drop continuation lines.
  5. ``test_body_nonempty``         (warn) — body after frontmatter ≥
                                       50 chars; empty bodies waste a
                                       slot in the system prompt.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from deepseek_tui.config.paths import user_skills_dir
from deepseek_tui.skills import _parse_skill_file

# ---------------------------------------------------------------------------
# Skill discovery — parametrize once at import time so each skill becomes its
# own test id (e.g. ``test_required_fields[Humanizer]``).
# ---------------------------------------------------------------------------

_SKILLS_ROOT: Path = user_skills_dir()


def _all_skill_dirs() -> list[Path]:
    if not _SKILLS_ROOT.is_dir():
        return []
    return sorted(
        d for d in _SKILLS_ROOT.iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    )


_SKILL_DIRS = _all_skill_dirs()
_SKILL_IDS = [d.name for d in _SKILL_DIRS]

if not _SKILL_DIRS:
    pytest.skip(
        f"no skills installed under {_SKILLS_ROOT} — nothing to lint",
        allow_module_level=True,
    )


_FENCE_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _split_raw(path: Path) -> tuple[str | None, str]:
    text = path.read_text(encoding="utf-8")
    m = _FENCE_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


# ---------------------------------------------------------------------------
# Roll-up reporter — single markdown table with severity column.
# ---------------------------------------------------------------------------

_REPORT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "_skills_lint_report.md"
)
_findings: list[tuple[str, str, str, str]] = []  # (severity, skill, check, reason)


def _record(severity: str, skill: str, check: str, reason: str) -> None:
    _findings.append((severity, skill, check, reason))


@pytest.fixture(scope="module", autouse=True)
def _write_report():
    yield
    errors = [f for f in _findings if f[0] == "error"]
    warns = [f for f in _findings if f[0] == "warn"]
    lines = [
        "# Skills Lint Report",
        "",
        f"- Skills root: `{_SKILLS_ROOT}`",
        f"- Skills found: {len(_SKILL_DIRS)}",
        f"- Errors (code/parity bugs): {len(errors)}",
        f"- Warnings (content quality): {len(warns)}",
        "",
    ]
    if _findings:
        lines.append("| Severity | Skill | Check | Reason |")
        lines.append("|---|---|---|---|")
        for sev, skill, check, reason in _findings:
            safe = reason.replace("|", r"\|").replace("\n", " ")
            lines.append(f"| {sev} | {skill} | {check} | {safe} |")
    else:
        lines.append("All checks passed.")
    _REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Errors — these MUST fail. Indicate a code / parity bug, not a content one.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=_SKILL_IDS)
def test_frontmatter_present(skill_dir: Path) -> None:
    raw, _ = _split_raw(skill_dir / "SKILL.md")
    if raw is None:
        _record("error", skill_dir.name, "frontmatter_present", "no `---` block")
        pytest.fail(f"{skill_dir.name}: SKILL.md has no frontmatter `---` block")


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=_SKILL_IDS)
def test_required_fields(skill_dir: Path) -> None:
    """``name`` is mandatory; the registry refuses to index without it."""
    raw, _ = _split_raw(skill_dir / "SKILL.md")
    if raw is None:
        pytest.skip("no frontmatter — covered by test_frontmatter_present")
    keys = {
        line.split(":", 1)[0].strip().lower()
        for line in raw.splitlines()
        if ":" in line and not line.startswith(" ")
    }
    if "name" not in keys:
        _record("error", skill_dir.name, "required_fields", "missing: ['name']")
        pytest.fail(f"{skill_dir.name}: missing frontmatter field 'name'")


# ---------------------------------------------------------------------------
# Warnings — content-quality. Recorded in report, never block CI.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=_SKILL_IDS)
def test_name_matches_directory(skill_dir: Path) -> None:
    """Directory-vs-frontmatter name drift is a *convention* issue.

    With the registry-first ``load_skill`` resolver, mismatch no longer
    breaks lookup. We still flag it because grep/ls/CLI tools resolve
    by directory name and humans assume the two agree.
    """
    skill = _parse_skill_file(skill_dir / "SKILL.md")
    if skill.name != skill_dir.name:
        _record(
            "warn",
            skill_dir.name,
            "name_matches_directory",
            f"frontmatter name='{skill.name}' != dir='{skill_dir.name}'",
        )


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=_SKILL_IDS)
def test_description_single_line(skill_dir: Path) -> None:
    """The parser is line-based (Rust parity, mod.rs:251).

    Block scalars (``description: |`` / ``description: >``) silently
    drop continuation lines. Authors should keep ``description`` on a
    single line. This is a content-convention warn, not a code bug.
    """
    raw, _ = _split_raw(skill_dir / "SKILL.md")
    if raw is None:
        pytest.skip("no frontmatter")

    lines = raw.splitlines()
    desc_idx = next(
        (i for i, ln in enumerate(lines)
         if ln.lstrip().lower().startswith("description:")),
        None,
    )
    if desc_idx is None:
        pytest.skip("no description field")

    head = lines[desc_idx].split(":", 1)[1].strip()
    is_block = head in ("|", ">", "|-", ">-", "|+", ">+")
    if is_block:
        _record(
            "warn",
            skill_dir.name,
            "description_single_line",
            "uses block scalar (| or >) — parser drops continuation lines; "
            "rewrite description as a single line",
        )


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=_SKILL_IDS)
def test_body_nonempty(skill_dir: Path) -> None:
    skill = _parse_skill_file(skill_dir / "SKILL.md")
    if len(skill.body.strip()) < 50:
        _record(
            "warn",
            skill_dir.name,
            "body_nonempty",
            f"body is {len(skill.body.strip())} chars (<50)",
        )
