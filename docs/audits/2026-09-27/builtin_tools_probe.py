"""Audit 16 observations, not desired-behavior regressions. No network or secrets.

Run with the repository Python environment; all I/O uses a temporary directory.
Assertions deliberately describe the audited defects and must change after fixes.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools import file as file_tools
from deepseek_tui.tools.encoding import from_api_tool_name, to_api_tool_name
from deepseek_tui.tools.plan_mode import APPROVED_PLAN_MARKER, sync_approved_plan_reminder
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.search import GrepFilesTool
from deepseek_tui.tools.shell import PtyProcess
from deepseek_tui.tools.user_input import validate_user_input_request
from deepseek_tui.tools.utils.gitignore import GitIgnoreMatcher
from deepseek_tui.tools.web import _merge_hits, _SearchHit


async def probe(root):
    results = {}
    workspace = root / "workspace"
    workspace.mkdir()
    outside = root / "outside.txt"
    outside.write_text("AUDIT16_OUTSIDE_FIXTURE\n")
    secret = workspace / ".env"
    secret.write_text("AUDIT16_SENSITIVE_FIXTURE\n")
    (workspace / "public.txt").symlink_to(outside)
    (workspace / "alias.txt").symlink_to(secret)
    context = ToolContext(working_directory=workspace)
    found = await GrepFilesTool().execute(
        {"path": ".", "pattern": "AUDIT16_", "output_mode": "content"}, context
    )
    assert "OUTSIDE_FIXTURE" in found.content and "SENSITIVE_FIXTURE" in found.content
    results["search_symlink"] = {"outside_read": True, "sensitive_alias_read": True}

    target = workspace / "edit.txt"
    target.write_text("old\n")
    original = file_tools._read_text_page

    def change_after_read(*args, **kwargs):
        page = original(*args, **kwargs)
        target.write_text("concurrent newer content\n")
        return page

    with patch.object(file_tools, "_read_text_page", change_after_read):
        read = await file_tools.ReadFileTool().execute({"path": "edit.txt"}, context)
    stale_detected = context.changed_since_last_seen(target)
    await file_tools.WriteFileTool().execute(
        {"path": "edit.txt", "content": "replacement based on old read"}, context
    )
    assert "old" in read.content and not stale_detected
    assert target.read_text() == "replacement based on old read"
    results["read_stamp_race"] = {"stale_detected": False, "concurrent_edit_overwritten": True}

    large = workspace / "large.txt"
    large.write_bytes(b"first line\n" + b"x\n" * 1_048_576)
    page = original(large, 0, 1)
    with large.open("rb") as stream:
        prefix = stream.read(65536)
    assert page.lines[0][1] == prefix.split(b"\n", 1)[0].decode()
    assert page.bytes_scanned == large.stat().st_size
    results["read_page_comparison"] = {
        "same_first_line": True,
        "current_bytes_read": page.bytes_scanned,
        "bounded_prefix_prototype_bytes_read": len(prefix),
        "prototype_omits_exact_total_lines": True,
    }

    name = "toolx00002E"
    decoded = from_api_tool_name(to_api_tool_name(name))
    assert decoded != name
    results["codec"] = {"input": name, "roundtrip": decoded}

    ignored = root / "bad-ignore"
    ignored.mkdir()
    (ignored / ".gitignore").write_text("[z-a]\n")
    try:
        GitIgnoreMatcher(ignored)
    except Exception as exc:
        results["invalid_ignore"] = {"exception": type(exc).__name__, "message": str(exc)}
    else:
        raise AssertionError("invalid range did not raise")

    options = [{"label": 1, "description": {"x": 1}}] * 2
    malformed = {"header": 1, "id": {"x": 1}, "question": 2, "options": options}
    accepted = validate_user_input_request({"questions": [malformed, malformed]})
    assert len(accepted) == 2
    normal = {
        "header": "H",
        "id": "duplicate",
        "question": "Q",
        "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}],
    }
    duplicate = validate_user_input_request({"questions": [normal, normal]})
    assert duplicate[0].id == duplicate[1].id
    results["question_validation"] = {"wrong_types_accepted": True, "duplicate_ids_accepted": True}

    urls = [
        "https://example.test/Page?id=1",
        "https://example.test/Page?id=2",
        "https://example.test/page?id=1",
    ]
    hits = [
        _SearchHit(title=str(i), url=url, snippet="fixture", source="test", score=1)
        for i, url in enumerate(urls)
    ]
    merged = _merge_hits(hits, 8)
    assert len(merged) == 1
    results["url_identity"] = {"distinct_urls": 3, "returned_urls": len(merged)}

    message = Message.user(f"Explain the phrase: {APPROVED_PLAN_MARKER}")
    history = [message]
    sync_approved_plan_reminder(
        history,
        mode="agent",
        working_directory=workspace,
        metadata={"runtime_thread_id": "audit16-fixture"},
    )
    assert history == []
    results["plan_reminder_identity"] = {"real_user_message_removed": True}

    # Exercise the actual PTY reader with synthetic reads, without spawning a process.
    proc = PtyProcess(pid=-1, master_fd=-1)
    chunks = [b"x" * 4096] * 256 + [b""]
    with (
        patch("deepseek_tui.tools.shell._safe_read", side_effect=chunks),
        patch("deepseek_tui.tools.shell.os.close"),
        patch("deepseek_tui.tools.shell.os.waitpid", return_value=(-1, 0)),
    ):
        await proc._reader_loop()
    assert len(proc.output) == 1_048_576
    results["pty_capture"] = {
        "synthetic_input_bytes": 1_048_576,
        "retained_bytes": len(proc._output),
        "all_bytes_retained": True,
    }
    return results


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="audit16-") as directory:
        output = asyncio.run(probe(Path(directory)))
    print(json.dumps(output, ensure_ascii=False, indent=2))
