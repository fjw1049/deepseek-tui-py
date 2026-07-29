"""Minimal live hook smoke: tool_call_before shell hook reads a policy doc.

No API / MCP required — only exercises HookExecutor + the fixture shell script.

Run:

    .venv/bin/python -m pytest tests/test_live_hook_smoke.py -m live -v -s
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.models import HooksConfig, LifecycleHookEntry
from deepseek_tui.integrations.hooks import HookContext, HookExecutor

PRE_TOOL_DOC_HOOK = Path(__file__).resolve().parent / "fixtures" / "pre_tool_check_doc.sh"


@pytest.mark.live
class TestLiveHookSmoke:
    async def test_pre_tool_document_check_hook(self, tmp_path: Path) -> None:
        policy_doc = tmp_path / "TOOL_POLICY.md"
        policy_doc.write_text(
            "# Agent Tool Policy\nReview this document before any tool executes.\n",
            encoding="utf-8",
        )
        audit_log = tmp_path / "pre_tool_audit.log"
        hook_cmd = f"sh {PRE_TOOL_DOC_HOOK} {policy_doc} {audit_log}"

        executor = HookExecutor.from_config(
            HooksConfig(
                enabled=True,
                hooks=[
                    LifecycleHookEntry(
                        event="tool_call_before",
                        name="review-tool-policy",
                        command=hook_cmd,
                        timeout_secs=5.0,
                    )
                ],
            ),
            tmp_path,
        )

        results = await executor.execute(
            "tool_call_before",
            HookContext(tool_name="read_file", tool_args='{"path":"x"}'),
        )
        assert results, "hook did not run"
        assert all(r.success for r in results), [(r.stderr, r.error) for r in results]
        assert audit_log.is_file(), "pre-tool audit log was not created"
        line = audit_log.read_text(encoding="utf-8").strip()
        assert "tool=read_file" in line
        assert "policy=# Agent Tool Policy" in line
