"""Tests for capability-aware exec_shell timeout fallback hints.

Pins step 2 of the robustness fix: the hint after an exec_shell timeout
must be driven by what the command was doing and what the runtime has
wired, not a hardcoded "use task_shell_start". The previous behavior
recommended task_shell_start unconditionally, which is wrong on the main
agent path (no active durable task) and useless for a ``curl`` that
should have used fetch_url in the first place.
"""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.utils.network_escalation import record_host_timeout
from deepseek_tui.tools.shell import _timeout_fallback_hint, _timeout_job_hint


def _ctx(**overrides) -> ToolContext:
    base = dict(
        working_directory=Path("/tmp"),
        task_manager=None,
        active_task_id=None,
    )
    base.update(overrides)
    return ToolContext(**base)


# --- curl URL → fetch_url (+ jsdelivr mirror for raw.githubusercontent) ---

def test_curl_url_suggests_fetch_url():
    cmd = "curl -sL https://example.com/file.txt"
    hint = _timeout_fallback_hint(cmd, _ctx())
    assert "fetch_url" in hint
    assert "task_shell_start" not in hint


_RAW_URL = (
    "https://raw.githubusercontent.com/owner/repo/main/README.md"
)
_RAW_CMD = f"curl -sL {_RAW_URL}"


def test_curl_url_single_timeout_no_escalation_yet():
    """A single timeout stays a quiet 'prefer fetch_url' hint — the
    escalation only appears after the host has crossed the threshold,
    so we don't spam suggestions on every transient blip."""
    hint = _timeout_fallback_hint(_RAW_CMD, _ctx())
    assert "fetch_url" in hint
    assert "mirror/CDN" not in hint


def test_curl_url_escalates_to_generic_hint_after_repeated_timeouts():
    """Once the same host has timed out >= threshold this turn, the hint
    escalates to a generic mirror/CDN/web_search suggestion. The hint
    is host-agnostic — no host-specific mirror URL is hardcoded here
    (domain knowledge like jsDelivr-for-raw-GitHub lives in the skill/
    prompt layer, not the generic network fallback)."""
    ctx = _ctx()
    record_host_timeout(ctx, _RAW_URL)  # 1st
    record_host_timeout(ctx, _RAW_URL)  # 2nd → at threshold
    hint = _timeout_fallback_hint(_RAW_CMD, ctx)
    assert "fetch_url" in hint
    assert "mirror/CDN" in hint or "web_search" in hint
    # No host-specific mirror URL is emitted by the generic layer.
    assert "cdn.jsdelivr.net" not in hint


def test_curl_non_github_host_escalates_same_as_any_host():
    """The generic escalation is identical for any host — YouTube, X,
    raw GitHub all get the same capability-aware behaviour."""
    ctx = _ctx()
    url = "https://example.com/file.txt"
    record_host_timeout(ctx, url)
    record_host_timeout(ctx, url)
    hint = _timeout_fallback_hint(f"curl -sL {url}", ctx)
    assert "fetch_url" in hint
    assert "mirror/CDN" in hint or "web_search" in hint


def test_curl_job_hint_is_fetch_url():
    cmd = "curl -sL https://example.com/x"
    assert _timeout_job_hint(cmd, _ctx()) == "fetch_url"


# --- durable task path → task_shell_start only when actually wired ---

def test_long_command_with_durable_task_suggests_task_shell_start():
    cmd = "pytest -n auto"
    # A TaskManager-like object is enough; resolver only checks truthiness.
    ctx = _ctx(task_manager=object(), active_task_id="task_abc")
    hint = _timeout_fallback_hint(cmd, ctx)
    assert "task_shell_start" in hint
    assert _timeout_job_hint(cmd, ctx) == "task_shell_start"


def test_task_manager_without_active_task_id_suggests_create_task_first():
    """task_shell_start needs an active task id; if a manager is wired but
    no task is active, guide the model to create one first."""
    cmd = "pytest -n auto"
    ctx = _ctx(task_manager=object(), active_task_id=None)
    hint = _timeout_fallback_hint(cmd, ctx)
    assert "task_create" in hint
    assert "task_shell_start" in hint
    assert _timeout_job_hint(cmd, ctx) == "task_create"


# --- default: long non-curl command, no durable task → background path ---

def test_default_long_command_suggests_background_shell():
    cmd = "npm run build"
    hint = _timeout_fallback_hint(cmd, _ctx())
    assert "exec_shell(background=true)" in hint
    assert "agent_result" in hint
    assert _timeout_job_hint(cmd, _ctx()) == "exec_shell_background"


# --- curl present but no URL → default path (don't misfire) ---

def test_curl_without_url_falls_through_to_default():
    cmd = "curl --version"
    hint = _timeout_fallback_hint(cmd, _ctx())
    assert "exec_shell(background=true)" in hint
