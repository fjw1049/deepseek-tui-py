"""Approval presentation builder (design §11.2 PR-*)."""

from __future__ import annotations

from deepseek_tui.policy.approval import (
    ApprovalRequest,
    RiskLevel,
    ToolCategory,
)
from deepseek_tui.tools.approval import (
    approval_request_to_sse_payload,
    build_impacts,
    build_primary_preview,
    classify_presentation_risk,
    classify_tool_category,
    enrich_approval_request,
)


def _req(tool_name: str = "write_file") -> ApprovalRequest:
    return ApprovalRequest(
        tool_name=tool_name,
        risk_level=RiskLevel.MEDIUM,
        category=ToolCategory.FILE_WRITE,
        reason="tool has medium risk level",
    )


def test_pr01_write_file_impacts_and_preview() -> None:
    req = _req()
    enrich_approval_request(
        req,
        "write_file",
        {"path": "src/foo.py", "content": "hello"},
    )
    assert classify_tool_category("write_file") == "file_write"
    assert req.presentation_risk == "destructive"
    assert any("Writes:" in line for line in req.impacts)
    assert "src/foo.py" in req.primary_preview
    assert req.title
    assert "medium risk" not in req.title


def test_pr02_apply_patch_diff_preview() -> None:
    patch = "--- a/x\n+++ b/x\n@@\n+line\n"
    preview = build_primary_preview(
        "apply_patch",
        "file_write",
        {"patch": patch},
    )
    assert "---" in preview or "patch" in preview.lower()
    impacts = build_impacts("apply_patch", "file_write", {"patch": patch})
    assert any("diff" in line.lower() or "patch" in line.lower() for line in impacts)


def test_pr03_exec_shell_command_and_cwd() -> None:
    req = _req("exec_shell")
    req.category = ToolCategory.CODE_EXEC
    enrich_approval_request(
        req,
        "exec_shell",
        {"command": "npm test", "cwd": "/tmp/project"},
    )
    joined = " ".join(req.impacts)
    assert "npm test" in joined
    assert "/tmp/project" in joined or "cwd" in req.primary_preview.lower()


def test_pr04_fetch_url_shows_url() -> None:
    req = _req("fetch_url")
    enrich_approval_request(
        req,
        "fetch_url",
        {"url": "https://example.com/api"},
    )
    assert "example.com" in " ".join(req.impacts) or "example.com" in req.primary_preview
    assert classify_presentation_risk(
        "fetch_url", "network", {"url": "https://example.com"}
    ) == "benign"


def test_pr05_agent_spawn_prompt() -> None:
    req = _req("agent_spawn")
    enrich_approval_request(
        req,
        "agent_spawn",
        {
            "prompt": "Review auth module",
            "allow_shell": True,
            "type": "review",
        },
    )
    joined = " ".join(req.impacts)
    assert "auth" in joined.lower() or "auth" in req.primary_preview.lower()


def test_pr07_approval_key_matches_cache() -> None:
    from deepseek_tui.policy.approval import build_approval_key

    args = {"command": "echo hi"}
    req = _req("exec_shell")
    enrich_approval_request(req, "exec_shell", args)
    assert req.approval_key == str(build_approval_key("exec_shell", args))


def test_pr08_dangerous_shell_impact() -> None:
    req = _req("exec_shell")
    enrich_approval_request(
        req,
        "exec_shell",
        {"command": "rm -rf /"},
    )
    assert any("Warning" in line or "dangerous" in line.lower() for line in req.impacts)


def test_sse_payload_backward_compatible() -> None:
    req = _req()
    enrich_approval_request(req, "write_file", {"path": "a.py", "content": "x"})
    payload = approval_request_to_sse_payload("appr-1", req)
    assert payload["approval_id"] == "appr-1"
    assert payload["tool_name"] == "write_file"
    assert isinstance(payload["impacts"], list)
    assert payload["title"]
    assert payload["description"] == payload["title"]
    assert payload["input_summary"]
