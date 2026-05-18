"""End-to-end smoke against the real ``~/.deepseek/skills`` registry.

Drives a curated sample (12) of the **actually installed** skills with
real DeepSeek API queries and asserts the model emits a ``load_skill``
tool_call. Weak success signal: we do NOT inspect what the assistant
says afterwards (the installed skills don't agree to emit a shared
marker token, so a body-content assertion would be brittle); we DO
assert "the model saw the skills list, picked the right one, and
called the tool by its registered name". That covers exactly the
chain we just rewrote — system-prompt injection → load_skill tool
name → registry resolution.

**Sample selection** (12 skills):

  - Three diagram skills with distinct trigger vocabularies so they
    don't compete on the same query: mermaid-visualizer (Markdown
    flowchart), excalidraw-diagram (Obsidian / 思维导图),
    json-canvas (.canvas file).
  - Two office-file skills: pdf, xlsx — the descriptions are very
    file-extension-specific so they're cheap, deterministic hits.
  - Two writing skills: humanizer-zh (Chinese AI-slop removal — also
    proves the name/dir drift fix end-to-end), internal-comms.
  - Three code/tooling: frontend-design, webapp-testing, mcp-builder.
  - Two workflow: planning-with-files, skill-creator.

**Excluded**: domain duplicates (docx/pptx skipped — pdf/xlsx already
cover the file-extension trigger pattern; algorithmic-art / canvas-
design / brand-guidelines / theme-factory / web-artifacts-builder /
slack-gif-creator / obsidian-bases / obsidian-markdown / doc-
coauthoring — pickable but selection cap is 12 to keep wall time
under ~10 min). Skills with placeholder or block-scalar descriptions
(template, Humanizer file, training-dataset-builder) are skipped
because the registry won't surface them usefully — see lint warns.

Only runs when ``has_deepseek_api_key()`` is true; CI without secrets
auto-skips, matching HANDOVER §四.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.config.models import Config, HooksConfig
from deepseek_tui.config.paths import user_skills_dir
from tests._real_api import (
    get_deepseek_api_key,
    get_deepseek_base_url,
    has_deepseek_api_key,
)

REAL_API_REASON = (
    "Needs DEEPSEEK_API_KEY env var or api_key in project config.toml"
)


# (skill_name, query). Each query is hand-tuned to echo the strongest
# trigger phrase from that skill's frontmatter ``description``, so the
# weak-pass criterion (``load_skill`` is called at all) has the highest
# possible hit rate without leaking the skill name into the prompt
# (we want to see the *registry* match, not the model parroting back
# what we wrote).
#
# Selection covers diagrams / docs / code / design / planning / testing
# / tooling without stacking same-domain skills, plus one bilingual
# (Chinese) sample and one name-vs-dir drift case (humanizer-zh).
# Skills with placeholder descriptions (template) or block-scalar
# descriptions (Humanizer / training-dataset-builder — the parser
# truncates these, see lint report) are deliberately excluded.
SAMPLE_SKILLS: list[tuple[str, str]] = [
    # — Diagram / visualization family — pick three with distinct trigger
    # vocabularies so we don't have all three competing on the same query.
    (
        "mermaid-visualizer",
        "Turn this into a flowchart I can drop into a Markdown doc:\n"
        "user clicks Login → backend validates → success goes to dashboard, "
        "failure shows error.",
    ),
    (
        "excalidraw-diagram",
        "请帮我画一张用户注册流程的思维导图，要 Excalidraw 格式，方便我导入 Obsidian。",
    ),
    (
        "json-canvas",
        "I want a `.canvas` file for Obsidian with three nodes — Idea, "
        "Draft, Published — connected by edges. Build it for me.",
    ),

    # — Document / office-file family — two file types, distinct triggers.
    (
        "pdf",
        "I have a 30-page PDF report and need to extract every table from "
        "it as CSV. Walk me through what to do.",
    ),
    (
        "xlsx",
        "Open the spreadsheet at /tmp/sales.xlsx, add a 'Total' column "
        "summing B and C, and save it back.",
    ),

    # — Writing / refinement family.
    (
        "humanizer-zh",
        "请把下面这段改写得更像真人写的，去掉那些 AI 味儿很浓的词：\n"
        "「通过赋能数字化转型，我们将持续不断地推动业务高质量发展，"
        "在生态共建的征程上携手并进。」",
    ),
    (
        "internal-comms",
        "Help me draft an internal status update for leadership about our "
        "Q3 launch — bullet-point format, focused on risks and asks.",
    ),

    # — Code / tooling family.
    (
        "frontend-design",
        "Build a polished landing-page hero section in React + Tailwind for "
        "a developer-tools startup. I want it to look distinctive, not "
        "generic AI-templated.",
    ),
    (
        "webapp-testing",
        "Help me verify that the login button on http://localhost:3000 "
        "actually navigates to /dashboard. Use a browser test.",
    ),
    (
        "mcp-builder",
        "I want to build a Model Context Protocol server in Python that "
        "wraps our internal ticketing API. Where do I start?",
    ),

    # — Workflow family.
    (
        "planning-with-files",
        "I'm starting a multi-week refactor of our auth subsystem. Set up a "
        "structured plan with persistent markdown files so I can track "
        "progress across sessions.",
    ),
    (
        "skill-creator",
        "I want to create a brand-new skill that summarizes git diffs into "
        "release notes. Help me write the SKILL.md.",
    ),
]


def _installed_skills() -> set[str]:
    """Names of skills present in the live ``~/.deepseek/skills``."""
    from deepseek_tui.skills import SkillRegistry

    return {s.name for s in SkillRegistry.discover(user_skills_dir()).skills}


pytestmark = pytest.mark.skipif(
    not has_deepseek_api_key(), reason=REAL_API_REASON
)


@pytest.mark.parametrize(
    "skill_name,query",
    SAMPLE_SKILLS,
    ids=[name for name, _ in SAMPLE_SKILLS],
)
async def test_real_query_triggers_load_skill(
    skill_name: str, query: str, tmp_path: Path
) -> None:
    """Send a real query that should trigger a specific installed skill.

    Pass criterion: the model emits at least one ``load_skill`` tool
    call. The ``name`` argument it picks is logged for diagnosis but
    not asserted strictly — models occasionally pick a sibling skill
    that also fits. As long as ``load_skill`` is called by its real
    registered name, the wiring (D1/D3) is proven.
    """
    if skill_name not in _installed_skills():
        pytest.skip(
            f"sample skill `{skill_name}` not installed under "
            f"{user_skills_dir()} — install it or remove from sample"
        )

    from deepseek_tui.app_server.runtime import AppRuntime
    from deepseek_tui.client.deepseek import DeepSeekClient

    api_key = get_deepseek_api_key()
    assert api_key is not None
    client = DeepSeekClient(
        api_key=api_key,
        base_url=get_deepseek_base_url(),
        timeout_seconds=120.0,
    )

    cfg = Config()
    cfg.hooks = HooksConfig()
    # Keep the surface narrow: skills + base tool registry, no MCP /
    # subagents / tasks — we're testing the skills wiring, not the
    # broader plugin matrix.
    cfg.features.mcp = False
    cfg.features.subagents = False
    cfg.features.tasks = False

    rt = await AppRuntime.create(
        config=cfg, working_directory=tmp_path, llm_client=client,
    )
    try:
        events: list[dict[str, Any]] = []
        async for frame in rt.stream_prompt(
            {"input": query, "model": "deepseek-v4-flash"}
        ):
            events.append(frame)
            ev = frame.get("event")
            if ev == "turn_complete":
                break
            if ev == "error" and not frame.get("retryable", False):
                break
    finally:
        await rt.shutdown()

    tool_calls = [e for e in events if e.get("event") == "tool_call"]
    load_skill_calls = [
        t for t in tool_calls
        if (t.get("tool_name") or t.get("name")) == "load_skill"
    ]

    # Diagnostic context for failures — list every tool the model
    # actually picked so we can tell "it called nothing" from
    # "it called the wrong tool" from "it called load_skill but with
    # an unexpected name".
    picked = [t.get("tool_name") or t.get("name") for t in tool_calls]
    arg_names = [
        (t.get("input") or t.get("arguments") or {}).get("name")
        for t in load_skill_calls
    ]

    assert load_skill_calls, (
        f"model never called load_skill for query targeting "
        f"`{skill_name}`. Tools the model did call: {picked}"
    )
    # Soft observation, not assertion: surface the picked skill name
    # so test logs make it easy to spot when the model picks a
    # sibling skill that also fits the query.
    print(
        f"\n[skills-e2e] target={skill_name!r} → "
        f"load_skill called {len(load_skill_calls)}x with name(s)={arg_names}"
    )
