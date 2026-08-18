"""Prompt composition and tool profiles.

Consolidates engine/prompts.py, tool_profiles.py, and prompts/ package.
Engine-level system prompt builder.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path


import enum
from typing import Any
from importlib.resources import files as pkg_files

HANDOFF_RELATIVE_PATH = ".deepseek/handoff.md"
INSTRUCTIONS_FILE_MAX_BYTES = 100 * 1024


class Personality(enum.Enum):
    """Personality overlay selection."""
    CALM = "calm"

    def prompt(self) -> str:
        return CALM_PERSONALITY()

    @staticmethod
    def from_settings(calm_mode: bool) -> Personality:
        del calm_mode  # single personality; kept for call-site compat
        return Personality.CALM


class AppMode(enum.Enum):
    """Application mode."""
    AGENT = "agent"
    YOLO = "yolo"
    PLAN = "plan"

    def mode_prompt(self) -> str:
        if self is AppMode.AGENT:
            return AGENT_MODE()
        elif self is AppMode.YOLO:
            return YOLO_MODE()
        return PLAN_MODE()

    def approval_prompt(self) -> str:
        if self is AppMode.YOLO:
            return AUTO_APPROVAL()
        elif self is AppMode.PLAN:
            return NEVER_APPROVAL()
        return SUGGEST_APPROVAL()


def _deepseek_version() -> str:
    """Resolve the installed package version (best-effort)."""
    try:
        from importlib.metadata import version as _v

        return _v("deepseek-tui")
    except Exception:  # noqa: BLE001 — best-effort, no propagating ImportError
        return "unknown"


# Calendar date frozen at process start (first render). Survives the whole
# server lifetime so the Environment block stays KV-prefix-stable; refresh
# only happens on process restart. Year-month-day is enough for as-of /
# "latest" reasoning; finer precision is available via ``exec_shell date``.
_PROCESS_TODAY: str | None = None


def process_today() -> str:
    """Return ``YYYY-MM-DD`` for this process (local date at first call)."""
    global _PROCESS_TODAY
    if _PROCESS_TODAY is None:
        _PROCESS_TODAY = datetime.now().strftime("%Y-%m-%d")
    return _PROCESS_TODAY


def render_environment_block(
    workspace: Path,
    locale_tag: str = "zh",
) -> str:
    """Render the ``## Environment`` block.

    Lists today's date (process-lifetime), locale, runtime version, host
    platform, login shell, and current working directory. All values are
    process/session-stable so the block sits in the workspace-static prefix
    and benefits from KV prefix cache hits.

    The block anchors the LLM in *where and when it is* — without it, models
    hallucinate ``/home/user/...`` paths from the training distribution
    instead of using the actual ``pwd``, and invent stale "current" dates.
    """
    shell = os.environ.get("SHELL", "unknown")
    pwd = workspace.expanduser().resolve()
    return (
        "## Environment\n"
        "\n"
        f"- today: {process_today()}\n"
        f"- lang: {locale_tag}\n"
        f"- deepseek_version: {_deepseek_version()}\n"
        f"- platform: {sys.platform}\n"
        f"- shell: {shell}\n"
        f"- pwd: {pwd}"
    )


def collect_git_snapshot(workspace: Path) -> str | None:
    """Collect a one-shot git snapshot for session-start injection.

    Claude Code injects a ``gitStatus`` block at conversation start —
    branch, short status, recent commits — explicitly labelled as a
    snapshot that will not update. It lives in the message stream (not
    the system prompt) so the KV prefix stays cacheable. Returns None
    for non-git workspaces or on any git failure: the snapshot is an
    aid, never a turn blocker.
    """
    import subprocess

    def _git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception:  # noqa: BLE001 — missing git, timeout, etc.
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.rstrip()

    status = _git("status", "--short", "--branch")
    if status is None:
        return None
    lines = status.splitlines()
    branch_line = lines[0].removeprefix("## ") if lines else "(unknown)"
    dirty = "\n".join(lines[1:]) or "(clean)"
    parts = [
        "## Git status",
        "",
        "This is the git status at the start of the session. It is a "
        "snapshot in time and will not update as you work — use the git "
        "tool when you need the current state.",
        "",
        f"Branch: {branch_line}",
        "",
        "Status:",
        dirty,
    ]
    commits = _git("log", "--oneline", "-5")
    if commits:  # empty repo has no commits — omit the section
        parts.extend(["", "Recent commits:", commits])
    # Branch names and commit subjects are attacker-controllable repo data
    # (a cloned repo can carry them); the snapshot is wrapped in a real
    # reminder envelope downstream, so defuse forged tags at the source.
    from deepseek_tui.engine.context_pressure import (
        neutralize_fake_system_reminders,
    )

    return neutralize_fake_system_reminders("\n".join(parts))


def render_plugin_context(
    *,
    name: str,
    version: str,
    path: str,
    permissions: tuple[str, ...] | list[str],
    trusted: bool,
    mcp_active: bool,
    has_mcp: bool,
) -> str:
    """Render the ``## Active Plugin`` block for a mounted plugin.

    Tells the model two things as one bundle: (a) the plugin's directory
    path, and (b) that ``read_file`` / ``file_search`` / ``grep`` are
    permitted under it. The read grant is applied silently via
    ``ToolContext.extra_read_roots`` at runtime; without this block the model
    only sees base.md's path-escape rule ("paths outside the workspace are
    rejected") and would never attempt to read plugin files. The block
    overrides that rule for the plugin directory only, for read operations.

    Session-stable (path/permissions don't change mid-session), so it sits
    above the volatile-content boundary and is KV-prefix-cache friendly.
    """
    perms = ", ".join(permissions) if permissions else "none"
    lines = [
        "## Active Plugin",
        "",
        f'You are operating with the plugin "{name}" (v{version}) mounted for this session.',
        "",
        f"- Plugin directory: {path}",
        "- Read access: you MAY use read_file / file_search / grep under the plugin "
        "directory above. This OVERRIDES the path-escape rule (paths outside the "
        "workspace are normally rejected) for this directory only, for read operations.",
        "- Write operations remain confined to the workspace.",
        "- Scenario tools: the API tool list for this session is authoritative "
        "(explore, write, shell, agents, web/session helpers as "
        "offered). Do not invent or forge tool-call markup for tools that are "
        "not in that list. Names in the static Toolbox that are absent from the "
        "API tools are unavailable while this plugin is mounted.",
        f"- Declared permissions: {perms}",
    ]
    if has_mcp and not mcp_active:
        lines.append(
            "- MCP servers / hooks from this plugin are NOT active "
            "(plugin not trusted). Built-in tools above do not require trust."
        )
    elif has_mcp and mcp_active:
        lines.append("- MCP servers from this plugin are active (trusted).")
    elif not trusted:
        lines.append(
            "- Plugin hooks are inactive until trusted. Built-in scenario tools "
            "do not require trust."
        )
    return "\n".join(lines)


# When total commands+agents stay at or below this, keep a per-item listing
# (helpful for small installs). Above it, switch to the thin per-plugin
# catalog so large marketplaces don't balloon the session-stable prompt.
PLUGIN_DETAILED_LIST_LIMIT = 10

# Legacy alias used by older call sites / tests.
PLUGIN_COMPONENT_LIST_LIMIT = PLUGIN_DETAILED_LIST_LIMIT


def _group_by_plugin(items: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for item in items:
        grouped.setdefault(item.plugin, []).append(item)
    return grouped


def render_installed_plugins_catalog(entries: list[Any] | None) -> str:
    """Render the thin ``## Installed Plugins`` contribution catalog.

    One line per plugin (name, description, component counts) plus invocation
    hints. Prefer this over per-command/agent listings when many plugins are
    installed — bodies stay on disk until ``/<plugin>:<cmd>``, ``load_skill``,
    an ``agent`` spawn, or ``@plugin:`` scenario mount.
    """
    entries = entries or []
    if not entries:
        return ""
    lines = [
        "## Installed Plugins (contributing)",
        "",
        "Enabled plugins contribute skills, slash commands, and agent "
        "personas. Only the catalog below is loaded into this prompt; full "
        "bodies activate on use.",
        "",
    ]
    for e in entries:
        name = getattr(e, "name", "") or ""
        if not name:
            continue
        desc = (getattr(e, "description", "") or "").strip()
        desc = " ".join(desc.split())
        if len(desc) > 120:
            desc = desc[:119] + "…"
        parts: list[str] = []
        for key, label in (
            ("skills", "skills"),
            ("commands", "commands"),
            ("agents", "agents"),
            ("rules", "rules"),
            ("mcp", "mcp"),
            ("hooks", "hooks"),
        ):
            n = int(getattr(e, key, 0) or 0)
            if n:
                parts.append(f"{label}:{n}")
        counts = f" [{', '.join(parts)}]" if parts else ""
        if desc:
            lines.append(f"- {name}: {desc}{counts}")
        else:
            lines.append(f"- {name}{counts}")
    lines.append("")
    lines.append(
        "Invoke slash commands with `/<plugin>:<command> [args]`; spawn a "
        'plugin persona with the `agent` tool (action="spawn") using '
        '`agent_type="<plugin>:<persona>"` '
        "(bare persona name works when unique); "
        "load skill bodies with `load_skill`. Enter a scenario (full rules) "
        "with `@plugin:<name>`."
    )
    return "\n".join(lines).rstrip()


def render_plugin_components_context(
    commands: list[Any] | None,
    agents: list[Any] | None,
    *,
    list_limit: int = PLUGIN_DETAILED_LIST_LIMIT,
) -> str:
    """Render a detailed ``## Plugin Commands & Agents`` block (small installs).

    Prefer :func:`render_installed_plugins_catalog` when the total number of
    commands+agents exceeds ``list_limit`` — callers (Engine) choose based on
    that threshold. This function keeps the per-item listing for small
    surfaces where the extra detail helps the model pick a command.
    """
    commands = commands or []
    agents = agents or []
    if not commands and not agents:
        return ""
    lines: list[str] = ["## Plugin Commands & Agents", ""]
    if commands:
        lines.append(
            "Slash commands from installed plugins — a user message of "
            "`/<plugin>:<command> [args]` expands the command's prompt "
            "template. Available:"
        )
        for c in commands[: max(list_limit, 1) * 2]:
            hint = f" (args: {c.argument_hint})" if c.argument_hint else ""
            desc = f" — {c.description}" if c.description else ""
            lines.append(f"- /{c.qualified}{hint}{desc}")
        lines.append("")
    if agents:
        lines.append(
            "Agent personas from installed plugins — spawn one with the "
            '`agent` tool (action="spawn") using `agent_type="<plugin>:<name>"` '
            "(bare name "
            "works when unique; persona system prompt is applied "
            "automatically). Available:"
        )
        for a in agents[: max(list_limit, 1) * 2]:
            desc = f" — {a.description}" if a.description else ""
            plugin = getattr(a, "plugin", None) or ""
            label = f"{plugin}:{a.name}" if plugin else a.name
            lines.append(f"- {label}{desc}")
    return "\n".join(lines).rstrip()


_CURRENT_DATE_RE = re.compile(r"\{\{\s*\.CurrentDate\s*\}\}")


def substitute_builtin_template_vars(text: str) -> str:
    """Replace safe built-in Go-template vars used by CodeBuddy/Claude content.

    Only ``{{.CurrentDate}}`` is substituted (with the current local date);
    any other ``{{...}}`` tokens are left verbatim so unknown/unsafe variables
    are never silently resolved.
    """
    if "{{" not in text:
        return text
    today = datetime.now().strftime("%A, %B %d, %Y")
    return _CURRENT_DATE_RE.sub(today, text)


def render_plugin_rules_context(
    rules: list[Any] | None,
    *,
    active_plugin: str | None = None,
) -> str:
    """Render plugin ``rules`` into a system-prompt block.

    Two modes (context governance):

    - ``active_plugin`` set (plugin mounted via ``@plugin:name``): the mounted
      plugin's rule bodies are injected verbatim — they carry the plugin's
      core behavior (CodeBuddy scenario rules) and mounting is the user's
      explicit opt-in. Other plugins' rules are omitted entirely. A mounted
      plugin with no ``rules/`` injects nothing (README is not guidance).
    - No mount: rules collapse to one summary line each with a mount hint.
      Injecting every installed plugin's full rule bodies (tens of KB) both
      taxes every turn's input tokens and dilutes the directives until the
      model ignores them, so the bodies only ship when mounted.
    """
    rules = rules or []
    if active_plugin is not None:
        # Mounted: inject this plugin's rule bodies (including
        # always_apply=false scenario-only rules — mounting is the opt-in).
        own = [r for r in rules if r.plugin == active_plugin]
        if not own:
            return ""
        lines = ["## Plugin Rules", ""]
        lines.append(
            f'The following directives come from the mounted plugin '
            f'"{active_plugin}" and are active for this session. Treat them '
            "as authoritative instructions."
        )
        for r in own:
            body = getattr(r, "body", "") or ""
            if not body.strip():
                continue
            lines.append("")
            lines.append(f"### Rule: {r.plugin}/{r.name}")
            lines.append("")
            lines.append(substitute_builtin_template_vars(body))
        return "\n".join(lines).rstrip()
    if not rules:
        return ""
    # Unmounted: catalog only always_apply rules. always_apply=false rules
    # stay silent until `@plugin:<name>` mounts the scenario.
    catalog = [
        r for r in rules if getattr(r, "always_apply", True)
    ]
    if not catalog:
        return ""
    lines = ["## Plugin Rules (inactive)", ""]
    lines.append(
        "Installed plugins ship scenario rules that activate when the plugin "
        "is mounted. None is mounted now. If the user's request clearly "
        "matches one of these scenarios, suggest mounting it by starting a "
        "message with `@plugin:<name>`:"
    )
    for plugin, items in sorted(_group_by_plugin(catalog).items()):
        descs = "; ".join(
            (r.description or r.name).strip().splitlines()[0][:120]
            for r in items
        )
        lines.append(f"- {plugin}: {descs}")
    return "\n".join(lines).rstrip()


def build_system_prompt(
    override: str | None = None,
    *,
    mode: AppMode = AppMode.AGENT,
    personality: Personality = Personality.CALM,
    workspace: Path | None = None,
    working_set_summary: str | None = None,
    skills_context: str | None = None,
    plugin_context: str | None = None,
    plugin_components_context: str | None = None,
    plugin_rules_context: str | None = None,
    locale_tag: str = "zh",
    project_context_enabled: bool = True,
    automations_guidelines: bool = False,
) -> str:
    """Build the full system prompt for the engine.

    If *override* is provided and non-empty, it is used verbatim (for tests
    and AppRuntime callers that supply their own prompt).

    Otherwise, composes from layered templates in this order:
      1. mode prompt (base + personality + mode + approval)
      2. project_context block (AGENTS.md / CLAUDE.md / instructions.md)
      3. ## Environment block (today / lang / version / platform / shell / pwd)
      4. context management guidance (Agent/Yolo only)
      5. skills context (available skills list)
      6. plugin context (mounted plugin dir + read grant, when mounted)
      7. how to read post-compaction <archived_context> (consumer hint)

    Volatile session state does **not** belong here:
      - previous-session handoff → user-role ``<system-reminder>`` (Engine)
      - working-set paths → compaction bridge / cycle structured state

    ``working_set_summary`` is accepted for call-site compatibility but ignored.

    Setting ``project_context_enabled=False`` skips the project_context
    block - used by tests that don't want disk I/O. The auto-generate
    side effect is suppressed in that case.
    """
    del working_set_summary  # kept for API compat; never mutate system with it

    if override is not None and override.strip():
        return override

    full_prompt = compose_prompt(mode, personality)

    # Project instructions: ~/.deepseek/AGENTS.md (global) merged with
    # workspace AGENTS.md / CLAUDE.md / instructions (parents / auto-gen).
    # Goes above the Environment block (workspace-static KV prefix layer).
    if workspace is not None and project_context_enabled:
        from deepseek_tui.engine.context import (
            load_project_context_with_parents,
        )

        project_ctx = load_project_context_with_parents(workspace)
        block = project_ctx.as_system_block()
        if block:
            full_prompt += "\n\n" + block

    # ## Environment — session-stable. Insert above all per-turn content
    # so it lives in the KV prefix cache layer.
    if workspace is not None:
        full_prompt += "\n\n" + render_environment_block(workspace, locale_tag)


    # Context Management (Agent / Yolo only)
    if mode in (AppMode.AGENT, AppMode.YOLO):
        full_prompt += (
            "\n\n## Context Management\n\n"
            "When the conversation grows long, the system automatically "
            "compacts or archives older turns and carries the session "
            "forward — a structured summary plus the recent verbatim "
            "messages will be in your next context. Managing this is not "
            "your job: do not wrap up early, drop planned work, or suggest "
            "starting a new session because the conversation is long. Keep "
            "working until the task is complete or you are blocked on input "
            "only the user can provide."
        )

    # Skills context
    if skills_context and skills_context.strip():
        full_prompt += "\n\n" + skills_context

    # Plugin context - mounted plugin directory + read grant. Sits above the
    # volatile-content boundary (session-stable) so it benefits from KV prefix
    # cache hits. Only present while a plugin is mounted.
    if plugin_context and plugin_context.strip():
        full_prompt += "\n\n" + plugin_context

    # Plugin commands & agent personas from installed plugins (session-stable).
    if plugin_components_context and plugin_components_context.strip():
        full_prompt += "\n\n" + plugin_components_context

    # Always-on plugin rules (system-level directives, session-stable).
    if plugin_rules_context and plugin_rules_context.strip():
        full_prompt += "\n\n" + plugin_rules_context

    # Short lane hint only (peer style: details stay in cron_* tool
    # descriptions). Injected when cron tools are registered — never a
    # always-on base.md chapter.
    if automations_guidelines:
        full_prompt += "\n\n" + AUTOMATIONS_LANE_HINT

    # Consumer hint only — the structured handoff is authored by the
    # summarizer (_create_summary) using COMPACT_TEMPLATE / compact.md.
    full_prompt += "\n\n" + COMPACT_CONSUMER_HINT

    return full_prompt


# Injected as a user-role <system-reminder> when the session grows long
# (SessionMaintenanceMixin._maybe_inject_long_session_reminder). Long
# contexts decay attention to the distant system prefix; this short
# re-anchor of the load-bearing disciplines rides near the context tail
# where attention is strongest. Keep it under ~150 tokens.
LONG_SESSION_REMINDER = (
    "Long-session checkpoint — your system instructions still apply in "
    "full. The disciplines that decay most in long sessions:\n"
    "- Answer the user's LATEST request; don't drift back to an earlier ask.\n"
    "- Keep the checklist current: one item in_progress, mark items "
    "completed immediately.\n"
    "- Verify before reporting: run the relevant command or test and read "
    "its output; report failures faithfully.\n"
    "- Keep changes minimal and scoped; no drive-by refactors or cleanups.\n"
    "- Action Safety still applies: confirm destructive or shared-state "
    "actions; git mutations only when explicitly asked.\n"
    "Do not mention this reminder to the user."
)


# Injected as a user-role <system-reminder> when the model tries to end a
# turn while the checklist still has open items
# (SessionMaintenanceMixin / orchestrator turn-end gate). The harness does
# NOT judge whether the work is done — it only forces the model to face each
# open item before ending, so a "wrote the plan, did the work, forgot to
# track it" turn cannot slip through silently. Re-fires while each block
# moves the checklist forward and releases once one changes nothing; see
# Engine._next_checklist_gate_summary.
CHECKLIST_GATE_REMINDER = (
    "Before ending the turn — your checklist still has open items "
    "({open_summary}). Resolve each one now:\n"
    "- Finished: mark completed with "
    "`checklist(op=\"update\", id=<id>, status=\"completed\")` — flip one at a "
    "time, don't resend the whole list.\n"
    "- Not finished: keep working and finish it. An open item is planned "
    "work you committed to, not a note to leave behind.\n"
    "- Won't do, or blocked on something only the user can provide: mark it "
    "`cancelled` and say why in your reply.\n"
    "Never mark an item completed while its tests fail or its implementation "
    "is partial — cancel it with the reason instead. Items still open when "
    "the turn ends are closed as cancelled, so leaving one open without "
    "explanation reads to the user as work silently dropped. Do not mention "
    "this reminder to the user."
)


# Injected as a user-role reminder in plan mode when the request reads like
# "just give me a plan" — see should_force_update_plan_first.
PLAN_GROUNDING_REMINDER = (
    "[System] Before creating the plan, explore the repository structure and "
    "relevant code first to ground your plan in the actual codebase."
)


# Keep this tiny: routing only. Cron syntax / delivery / fire toolset live on
# CronCreateTool.description (and cron execution playbook).
AUTOMATIONS_LANE_HINT = (
    "- **Recurring or scheduled for later** (\"every morning\", \"in 2 hours\", "
    "\"daily digest\") → `cron_create` — never `task_create` for reminders. "
    "List/delete with `cron_list` / `cron_delete`. Tell the user jobs are "
    "managed in the Workbench sidebar Automations page."
)


def handoff_path(workspace: Path) -> Path:
    """Absolute path of the workspace-local handoff artifact."""
    return workspace / HANDOFF_RELATIVE_PATH


def load_handoff_reminder(workspace: Path) -> str | None:
    """Read workspace-local handoff for injection as a user-role reminder.

    Returns ``None`` when the file is missing or empty. Callers wrap with
    :func:`deepseek_tui.engine.context_pressure.wrap_system_reminder`.
    """
    path = handoff_path(workspace)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    # Same threat as the git snapshot: this is workspace file content, so a
    # cloned repo can ship a handoff carrying a forged reminder tag. The body
    # is inlined inside a real envelope downstream, so defuse at the source.
    from deepseek_tui.engine.context_pressure import (
        neutralize_fake_system_reminders,
    )

    return neutralize_fake_system_reminders(
        f"## Previous Session Handoff\n\n"
        f"The previous session in this workspace left a handoff at "
        f"`{HANDOFF_RELATIVE_PATH}`. Consider it the first artifact to read "
        f"on this turn — open blockers, in-flight changes, and recent decisions "
        f"live there. Update or rewrite it before exiting if state changes "
        f"materially.\n\n"
        f"It describes the workspace as the previous session left it and has "
        f"not been checked against the current state — anything it claims "
        f"about files, branches, or what is finished is a lead to verify, not "
        f"a fact to build on.\n\n{trimmed}"
    )


# Tool visibility profiles — slim catalogs for automation composer and cron runs.


AUTOMATION_COMPOSER_HEADING = "[Scheduled automation request]"
CRON_PROMPT_PREFIX = "[cron:"

TOOL_PROFILE_FULL = "full"
TOOL_PROFILE_AUTOMATION_COMPOSER = "automation_composer"
TOOL_PROFILE_CRON = "cron"

# Composer: schedule creation only — no MCP, no shell.
_AUTOMATION_COMPOSER_NATIVE = frozenset(
    {
        "cron_create",
        "cron_list",
        "cron_delete",
    }
)

# Cron execution: read/search/fetch + shell + skills.
# Installed MCP tools (mcp_*) are admitted separately in
# filter_tools_for_profile — they are whatever the shared McpManager
# already discovered. Write tools / request_user_input
# stay out (detached auto_approve turn).
_CRON_NATIVE = frozenset(
    {
        "web_search",
        "fetch_url",
        "read_file",
        "grep_files",
        "file_search",
        "exec_shell",
        "load_skill",
    }
)

# Mirror engine.dispatch.is_mcp_tool without importing dispatch (avoids
# prompts ↔ engine cycles). Covers installed server tools + resource helpers.
_CRON_MCP_META = frozenset(
    {
        "list_mcp_resources",
        "mcp_read_resource",
        "read_mcp_resource",
    }
)


def _is_cron_allowed_mcp_tool(name: str) -> bool:
    if name in _CRON_MCP_META:
        return True
    return name.startswith("mcp_") or name.startswith("mcp__")


def detect_tool_profile_from_prompt(prompt: str) -> str:
    """Infer profile from wrapped user / cron prompt text."""
    text = prompt.lstrip()
    if text.startswith(AUTOMATION_COMPOSER_HEADING):
        return TOOL_PROFILE_AUTOMATION_COMPOSER
    if text.startswith(CRON_PROMPT_PREFIX):
        return TOOL_PROFILE_CRON
    return TOOL_PROFILE_FULL


def _tool_name(entry: dict[str, Any]) -> str:
    fn = entry.get("function", entry)
    return str(fn.get("name", ""))


def filter_tools_for_profile(
    tools: list[dict[str, Any]], profile: str | None
) -> list[dict[str, Any]]:
    """Return a subset of API tool descriptors for the given profile."""
    if not profile or profile == TOOL_PROFILE_FULL:
        return tools

    if profile == TOOL_PROFILE_AUTOMATION_COMPOSER:
        allowed_native = _AUTOMATION_COMPOSER_NATIVE
        out: list[dict[str, Any]] = []
        for entry in tools:
            name = _tool_name(entry)
            if name in allowed_native:
                out.append(_copy_tool_entry(entry))
        return out

    if profile == TOOL_PROFILE_CRON:
        out = []
        for entry in tools:
            name = _tool_name(entry)
            if name in _CRON_NATIVE or _is_cron_allowed_mcp_tool(name):
                out.append(_copy_tool_entry(entry))
        return out

    return tools


def _copy_tool_entry(entry: dict[str, Any]) -> dict[str, Any]:
    fn = entry.get("function", entry)
    if not isinstance(fn, dict):
        return dict(entry)
    return {
        "type": entry.get("type", "function"),
        "function": dict(fn),
    }


# System prompt composition from layered template files.
# Composable layers loaded at runtime:
# base.md → personality overlay → mode delta → approval policy.
# Prompt files are copied verbatim (English, unmodified).


_PACKAGE = "deepseek_tui.prompts"


def _load(relative: str) -> str:
    """Load a prompt file from the package data directory."""
    return (pkg_files(_PACKAGE) / relative).read_text(encoding="utf-8")


# Lazy-loaded prompt constants
_cache: dict[str, str] = {}


def _get(key: str) -> str:
    if key not in _cache:
        _cache[key] = _load(key)
    return _cache[key]


def BASE_PROMPT() -> str:  # noqa: N802
    return _get("base.md")


def CALM_PERSONALITY() -> str:  # noqa: N802
    return _get("personalities/calm.md")


def AGENT_MODE() -> str:  # noqa: N802
    return _get("modes/agent.md")


def PLAN_MODE() -> str:  # noqa: N802
    return _get("modes/plan.md")


def YOLO_MODE() -> str:  # noqa: N802
    return _get("modes/yolo.md")


def AUTO_APPROVAL() -> str:  # noqa: N802
    return _get("approvals/auto.md")


def SUGGEST_APPROVAL() -> str:  # noqa: N802
    return _get("approvals/suggest.md")


def NEVER_APPROVAL() -> str:  # noqa: N802
    return _get("approvals/never.md")


def COMPACT_TEMPLATE() -> str:  # noqa: N802
    """Structured handoff contract for the compaction summarizer."""
    return _get("compact.md")


# Short note for the main agent after compaction. Do not paste the empty
# Goal/Constraints skeleton here — that belongs on the summarizer call.
COMPACT_CONSUMER_HINT = (
    "## After Compaction\n\n"
    "When earlier turns are compacted, a structured summary appears in "
    "`<archived_context>` with sections: Goal, Constraints, Progress "
    "(Done / In Progress / Blocked), Key Decisions, and Next step. "
    "Treat that block plus the recent verbatim messages as your "
    "continuation context — do not ask the user to restate work that is "
    "already covered there.\n\n"
    "A `<prior_user_requests>` block may accompany it, listing every request "
    "the user has made this session in their own words. It is quoted "
    "verbatim; the summary is a paraphrase. **Where the two disagree, the "
    "verbatim requests win.** A constraint listed there still binds you even "
    "if the summary omits it — the summary losing it is the expected failure, "
    "which is why the list exists. The last entry is the current request; "
    "earlier ones are context and standing constraints, not work to redo."
)


def CYCLE_HANDOFF() -> str:  # noqa: N802
    return _get("cycle.md")


def SUBAGENT_OUTPUT_FORMAT() -> str:  # noqa: N802
    return _get("sub_output.md")


# (Personality and AppMode moved to top of file)


# ── Composition ──────────────────────────────────────────────────────────


def compose_prompt(mode: AppMode, personality: Personality = Personality.CALM) -> str:
    """Compose the full system prompt in deterministic order.

    Order (most-static to most-volatile for KV prefix cache):
      1. base.md        — core identity, toolbox, execution contract
      2. personality    — voice and tone overlay
      3. mode delta     — mode-specific permissions and process
      4. approval policy — tool-approval behavior
    """
    parts = [
        BASE_PROMPT().strip(),
        personality.prompt().strip(),
        mode.mode_prompt().strip(),
        mode.approval_prompt().strip(),
    ]
    return "\n\n".join(parts)


def load_prompt(name: str) -> str:
    """Load a prompt by name (for backward compatibility).

    Maps prompt names to their corresponding loader functions.
    Used by SubAgentType.system_prompt() to load sub_output.
    """
    name_lower = name.lower().replace("-", "_")
    loaders = {
        "sub_output": SUBAGENT_OUTPUT_FORMAT,
        "base": BASE_PROMPT,
        "calm_personality": CALM_PERSONALITY,
        "agent_mode": AGENT_MODE,
        "plan_mode": PLAN_MODE,
        "yolo_mode": YOLO_MODE,
        "auto_approval": AUTO_APPROVAL,
        "suggest_approval": SUGGEST_APPROVAL,
        "never_approval": NEVER_APPROVAL,
        "compact_template": COMPACT_TEMPLATE,
        "cycle": CYCLE_HANDOFF,
    }
    loader = loaders.get(name_lower)
    if loader is None:
        raise ValueError(f"Unknown prompt name: {name}")
    return loader()
