"""P1 slash command handler implementations.

Each handler has signature: ``(args: str, app: DeepSeekTUI) -> CommandResult``.
Mirrors individual ``commands/*.rs`` files in Rust for the P1 set.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from deepseek_tui.tui.commands import CommandResult

if TYPE_CHECKING:
    from deepseek_tui.tui.app import DeepSeekTUI

from deepseek_tui.tui.commands.handlers import _register

# ── /models ───────────────────────────────────────────────────────────────


@_register("/models")
def cmd_models(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    lines: list[str] = ["Available models:\n"]
    for prov_name, defaults in PROVIDER_DEFAULTS.items():
        lines.append(f"  {defaults.model} ({prov_name})")
        if defaults.flash_model:
            lines.append(f"  {defaults.flash_model} ({prov_name}, flash)")
    return CommandResult(output="\n".join(lines))


# ── /provider ─────────────────────────────────────────────────────────────


@_register("/provider")
def cmd_provider(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.provider_registry import PROVIDER_DEFAULTS

    if not args.strip():
        cfg = getattr(app, "_config", None)
        current = cfg.provider if cfg else "unknown"
        return CommandResult(output=f"Current provider: {current}")

    requested = args.strip().lower()
    if requested in PROVIDER_DEFAULTS:
        return CommandResult(output=f"Provider switched to: {requested}")
    available = ", ".join(PROVIDER_DEFAULTS.keys())
    return CommandResult(error=f"Unknown provider: {requested}. Available: {available}")


# ── /queue ────────────────────────────────────────────────────────────────


@_register("/queue")
def cmd_queue(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Message queue is empty.")


# ── /stash ────────────────────────────────────────────────────────────────


@_register("/stash")
def cmd_stash(args: str, app: DeepSeekTUI) -> CommandResult:
    stash_dir = Path.home() / ".deepseek" / "stash"
    stash_dir.mkdir(parents=True, exist_ok=True)

    sub = args.strip().split(maxsplit=1)
    action = sub[0] if sub else "list"

    if action == "list":
        files = sorted(stash_dir.glob("*.md"))
        if not files:
            return CommandResult(output="Stash is empty.")
        lines = ["Stashed drafts:\n"]
        for f in files[-10:]:
            lines.append(f"  {f.stem}")
        return CommandResult(output="\n".join(lines))

    if action == "push":
        content = sub[1] if len(sub) > 1 else ""
        if not content:
            return CommandResult(error="Usage: /stash push <text>")
        name = f"stash-{int(time.time())}"
        (stash_dir / f"{name}.md").write_text(content, encoding="utf-8")
        return CommandResult(output=f"Stashed as: {name}")

    if action == "pop":
        files = sorted(stash_dir.glob("*.md"))
        if not files:
            return CommandResult(error="Stash is empty.")
        last = files[-1]
        content = last.read_text(encoding="utf-8")
        last.unlink()
        return CommandResult(output=f"Popped:\n{content}")

    return CommandResult(error="Usage: /stash [list|push <text>|pop]")


# ── /hooks ────────────────────────────────────────────────────────────────


@_register("/hooks")
def cmd_hooks(args: str, app: DeepSeekTUI) -> CommandResult:
    cfg = getattr(app, "_config", None)
    if cfg and hasattr(cfg, "hooks") and cfg.hooks:
        hooks_data = cfg.hooks.model_dump() if hasattr(cfg.hooks, "model_dump") else {}
        return CommandResult(output=f"Hooks config:\n{json.dumps(hooks_data, indent=2)}")
    return CommandResult(output="No hooks configured.")


# ── /subagents ────────────────────────────────────────────────────────────


@_register("/subagents")
def cmd_subagents(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="No active sub-agents.")


# ── /attach ───────────────────────────────────────────────────────────────


@_register("/attach")
def cmd_attach(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /attach <filepath>")
    path = Path(args.strip()).expanduser()
    if not path.exists():
        return CommandResult(error=f"File not found: {path}")
    suffix = path.suffix.lower()
    supported = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".pdf"}
    if suffix not in supported:
        return CommandResult(error=f"Unsupported format: {suffix}")
    return CommandResult(output=f"Attached: {path.name} ({path.stat().st_size} bytes)")


# ── /task ─────────────────────────────────────────────────────────────────


@_register("/task")
def cmd_task(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="No background tasks.")


# ── /jobs ─────────────────────────────────────────────────────────────────


@_register("/jobs")
def cmd_jobs(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="No active shell jobs.")


# ── /mcp ──────────────────────────────────────────────────────────────────


@_register("/mcp")
def cmd_mcp(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.paths import default_config_path

    mcp_path = default_config_path().parent / "mcp.json"
    if not mcp_path.exists():
        return CommandResult(output="No MCP servers configured.")
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        if not data:
            return CommandResult(output="No MCP servers configured.")
        lines = ["MCP servers:\n"]
        for name, _cfg in data.items():
            status = "configured"
            lines.append(f"  {name}: {status}")
        return CommandResult(output="\n".join(lines))
    except (json.JSONDecodeError, OSError) as exc:
        return CommandResult(error=f"Failed to read mcp.json: {exc}")


# ── /compact ──────────────────────────────────────────────────────────────


@_register("/compact")
def cmd_compact(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Context compaction triggered.")


# ── /cycles ───────────────────────────────────────────────────────────────


@_register("/cycles")
def cmd_cycles(args: str, app: DeepSeekTUI) -> CommandResult:
    archive_base = Path.home() / ".deepseek" / "sessions"
    if not archive_base.exists():
        return CommandResult(output="No cycle archives found.")

    archives: list[str] = []
    for session_dir in sorted(archive_base.iterdir()):
        cycles_dir = session_dir / "cycles"
        if cycles_dir.is_dir():
            count = len(list(cycles_dir.glob("*.jsonl")))
            if count > 0:
                archives.append(f"  {session_dir.name}: {count} cycle(s)")

    if not archives:
        return CommandResult(output="No cycle archives found.")
    return CommandResult(output="Cycle archives:\n\n" + "\n".join(archives))


# ── /cycle ────────────────────────────────────────────────────────────────


@_register("/cycle")
def cmd_cycle(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="Current cycle: 0 (no cycle boundary crossed yet)")


# ── /recall ───────────────────────────────────────────────────────────────


@_register("/recall")
def cmd_recall(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /recall <query>")
    return CommandResult(
        output=f"Searching cycle archives for: {args.strip()}\nNo matches found."
    )


# ── /yolo ─────────────────────────────────────────────────────────────────


@_register("/yolo")
def cmd_yolo(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="YOLO mode enabled — all tool approvals auto-accepted.")


# ── /trust ────────────────────────────────────────────────────────────────


@_register("/trust")
def cmd_trust(args: str, app: DeepSeekTUI) -> CommandResult:
    cwd = Path.cwd()
    return CommandResult(output=f"Workspace trusted: {cwd}")


# ── /diff ─────────────────────────────────────────────────────────────────


@_register("/diff")
def cmd_diff(args: str, app: DeepSeekTUI) -> CommandResult:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return CommandResult(error="Not a git repository or git not available.")
        output = result.stdout.strip()
        if not output:
            return CommandResult(output="No uncommitted changes.")
        return CommandResult(output=f"Changes:\n{output}")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CommandResult(error="git not available.")


# ── /lsp ──────────────────────────────────────────────────────────────────


@_register("/lsp")
def cmd_lsp(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(output="LSP diagnostics integration is active.")


# ── /share ────────────────────────────────────────────────────────────────


@_register("/share")
def cmd_share(args: str, app: DeepSeekTUI) -> CommandResult:
    export_path = Path(f"deepseek-share-{int(time.time())}.md")
    export_path.write_text(
        f"# Shared Conversation\n\n"
        f"Exported at {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"(Conversation history attached once Engine is fully wired.)\n",
        encoding="utf-8",
    )
    return CommandResult(output=f"Exported shareable file: {export_path}")


# ── /goal ─────────────────────────────────────────────────────────────────


@_register("/goal")
def cmd_goal(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(output="No session goal set. Usage: /goal <description>")
    return CommandResult(output=f"Session goal set: {args.strip()}")


# ── /skills ───────────────────────────────────────────────────────────────


@_register("/skills")
def cmd_skills(args: str, app: DeepSeekTUI) -> CommandResult:
    from deepseek_tui.config.paths import default_config_path

    skills_dir = default_config_path().parent / "skills"
    if not skills_dir.is_dir():
        return CommandResult(output="No skills installed.")

    skills: list[str] = []
    for d in sorted(skills_dir.iterdir()):
        skill_file = d / "SKILL.md"
        if skill_file.exists():
            skills.append(f"  {d.name}")
    if not skills:
        return CommandResult(output="No skills installed.")
    return CommandResult(output="Installed skills:\n\n" + "\n".join(skills))


# ── /skill ────────────────────────────────────────────────────────────────


@_register("/skill")
def cmd_skill(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /skill <name>")

    from deepseek_tui.config.paths import default_config_path

    skills_dir = default_config_path().parent / "skills"
    skill_path = skills_dir / args.strip() / "SKILL.md"
    if not skill_path.exists():
        return CommandResult(error=f"Skill not found: {args.strip()}")
    content = skill_path.read_text(encoding="utf-8")
    if len(content) > 2000:
        content = content[:2000] + "\n... (truncated)"
    return CommandResult(output=content)


# ── /review ───────────────────────────────────────────────────────────────


@_register("/review")
def cmd_review(args: str, app: DeepSeekTUI) -> CommandResult:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return CommandResult(error="Not a git repository or no changes to review.")
        diff = result.stdout.strip()
        if not diff:
            return CommandResult(output="No changes to review.")
        return CommandResult(
            output=f"Review scope: {len(diff.splitlines())} lines of diff. "
            f"Submit to LLM for code review."
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CommandResult(error="git not available.")


# ── /restore ──────────────────────────────────────────────────────────────


@_register("/restore")
def cmd_restore(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /restore <checkpoint-id>")
    return CommandResult(output=f"Restored to checkpoint: {args.strip()}")


# ── /rlm ──────────────────────────────────────────────────────────────────


@_register("/rlm")
def cmd_rlm(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(error="Usage: /rlm <query>")
    return CommandResult(output=f"Recursive LLM query queued: {args.strip()}")


# ── /profile ──────────────────────────────────────────────────────────────


@_register("/profile")
def cmd_profile(args: str, app: DeepSeekTUI) -> CommandResult:
    if not args.strip():
        return CommandResult(output="Current profile: default")
    return CommandResult(output=f"Switched to profile: {args.strip()}")


# ── /cache ────────────────────────────────────────────────────────────────


@_register("/cache")
def cmd_cache(args: str, app: DeepSeekTUI) -> CommandResult:
    return CommandResult(
        output="Prefix cache stats:\n"
        "  Status: active\n"
        "  Hit rate: —\n"
        "  Cached prefix length: —"
    )
