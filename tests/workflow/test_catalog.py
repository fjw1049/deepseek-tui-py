"""Named workflow catalog discovery tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.workflow.catalog import (
    WorkflowCatalogError,
    list_workflows,
    resolve_workflow,
    resolve_workflow_path,
)
from deepseek_tui.workflow.models import parse_workflow_spec


def _write_spec(path: Path, name: str, description: str = "d") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "meta": {"name": name, "description": description},
                "policy": {},
                "phases": [
                    {
                        "id": "p1",
                        "title": "P",
                        "steps": [
                            {
                                "id": "a1",
                                "type": "agent",
                                "label": "worker",
                                "prompt": "do {{task}}",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_resolve_bundled_repo_review() -> None:
    spec = resolve_workflow("repo_review")
    assert spec.meta.name == "repo_review"
    fanout = next(
        s for p in spec.phases for s in p.steps if s.type == "fanout"
    )
    assert fanout.items_from is not None
    assert fanout.items_from.path == "$.targets"


def test_cwd_overrides_preset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_spec(tmp_path / "workflows" / "repo_review.json", "repo_review", "override")
    path = resolve_workflow_path("repo_review", cwd=tmp_path)
    assert path == tmp_path / "workflows" / "repo_review.json"
    spec = resolve_workflow("repo_review", cwd=tmp_path)
    assert spec.meta.description == "override"


def test_list_workflows_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_spec(tmp_path / "workflows" / "alpha.json", "alpha", "from cwd")
    records = list_workflows(cwd=tmp_path)
    names = {r.name: r for r in records}
    assert "alpha" in names
    assert names["alpha"].source == "cwd"
    assert "repo_review" in names
    assert names["repo_review"].source == "preset"


def test_resolve_missing_raises() -> None:
    with pytest.raises(WorkflowCatalogError, match="not found"):
        resolve_workflow("no_such_workflow_zzz")


def test_preset_parses_via_parse_workflow_spec() -> None:
    from deepseek_tui.workflow.catalog import resolve_workflow_path

    path = resolve_workflow_path("repo_review")
    raw = json.loads(path.read_text(encoding="utf-8"))
    spec = parse_workflow_spec(raw)
    assert len(spec.phases) == 3


def test_bundled_presets_resolve() -> None:
    for name in ("repo_review", "diff_review", "spec_check"):
        spec = resolve_workflow(name)
        assert spec.meta.name == name


def test_list_workflows_skips_non_utf8_file_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single non-UTF-8 *.json in a workflows dir must not sink list_workflows()."""
    monkeypatch.chdir(tmp_path)
    _write_spec(tmp_path / "workflows" / "good.json", "good")
    bad_path = tmp_path / "workflows" / "bad.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_bytes(b"\xff\xfe\x00\x01not-utf8")

    records = list_workflows(cwd=tmp_path)
    names = {r.name for r in records}
    assert "good" in names
    assert "bad" not in names
