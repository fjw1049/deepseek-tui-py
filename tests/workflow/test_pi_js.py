"""Pi JS workflow script meta parser tests."""

from __future__ import annotations

import pytest

from deepseek_tui.workflow.adapters import PiJsParseError, parse_workflow_script


def test_parse_meta_literal() -> None:
    script = """export const meta = {
  name: 'demo_workflow',
  description: 'A useful workflow',
}
phase('Scan')
"""
    meta, body = parse_workflow_script(script)
    assert meta["name"] == "demo_workflow"
    assert "phase" in body


def test_parse_requires_meta_first() -> None:
    with pytest.raises(PiJsParseError, match="first"):
        parse_workflow_script("const x = 1\nexport const meta = { name: 'a', description: 'b' }")


def test_parse_rejects_executable_meta_expressions() -> None:
    with pytest.raises(PiJsParseError, match="could not parse meta literal"):
        parse_workflow_script(
            "export const meta = { name: String(1 + 1), description: 'd' }\nphase('x')"
        )
