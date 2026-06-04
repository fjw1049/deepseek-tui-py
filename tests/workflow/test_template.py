"""Workflow template rendering tests."""

from __future__ import annotations

from deepseek_tui.workflow.template import make_step_output, render_template


def test_item_and_previous_substitution() -> None:
    prev = make_step_output("full body text here")
    out = render_template(
        "item={{item}} prev={{previous}}",
        item="engine",
        previous=prev,
    )
    assert "item=engine" in out
    assert "prev=" in out


def test_outputs_preview_and_full() -> None:
    outputs = {
        "s1": make_step_output("x" * 5000, structured={"ok": True}),
    }
    preview = render_template("p={{outputs.s1}}", outputs=outputs)
    assert len(preview) < 3000
    full = render_template("f={{outputs.s1.full}}", outputs=outputs)
    assert "xxx" in full
