"""L4 — End-to-end skills with a real DeepSeek model.

Per HANDOVER §四 / line 247: any feature that touches the LLM main path
MUST have a real-API test. Skills inject content into the system prompt
and ride on a tool call (``skill_load``), so they qualify.

Two scenarios:

1. **Skills appear in the system prompt** — wire a SkillRegistry into
   Engine, send a probe, assert the rendered system prompt actually
   contains the ``## Available Skills`` block. This is the
   pre-condition for the LLM ever calling ``skill_load``.

2. **Skill round-trip** — install a tiny skill whose body says
   "respond with PONG_SKILL_42". Ask the LLM "use the
   pingpong-skill skill". Assert that:
     - the model calls ``skill_load`` (or that we can verify the
       hook fires by another observable means), and
     - the final assistant text contains the secret token.

Real-API guarantee: ``has_deepseek_api_key()`` skips when no key is
reachable, so CI without secrets stays green; local dev with
``config.toml`` runs both tests automatically.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.config.models import Config, HooksConfig
from deepseek_tui.skills import SKILL_FILENAME
from tests._real_api import (
    get_deepseek_api_key,
    get_deepseek_base_url,
    has_deepseek_api_key,
)

REAL_API_REASON = (
    "Needs DEEPSEEK_API_KEY env var or api_key in project config.toml"
)


def _install_skill(skills_dir: Path, name: str, *, description: str,
                   body: str) -> None:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / SKILL_FILENAME).write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n",
        encoding="utf-8",
    )


@pytest.mark.skipif(not has_deepseek_api_key(), reason=REAL_API_REASON)
class TestSkillsRealApi:
    async def test_skills_block_renders_into_system_prompt(
        self, tmp_path: Path
    ) -> None:
        """The renderer must inject ``## Available Skills`` when skills
        live under the workspace's ``.deepseek/skills``.

        This is the cheapest end-to-end check — no LLM call needed,
        but it's grouped with the real-API class because it shares
        the Engine wiring and gates the next test.
        """
        from deepseek_tui.app_server.runtime import AppRuntime
        from deepseek_tui.client.deepseek import DeepSeekClient

        ws = tmp_path / "ws"
        ws.mkdir()
        skills_dir = ws / ".deepseek" / "skills"
        _install_skill(
            skills_dir,
            "probe-skill",
            description="A unique probe skill marker_alpha789.",
            body="If asked, respond with the literal string MARKER_ALPHA789.",
        )

        api_key = get_deepseek_api_key()
        assert api_key is not None
        client = DeepSeekClient(
            api_key=api_key,
            base_url=get_deepseek_base_url(),
            timeout_seconds=60.0,
        )

        cfg = Config()
        cfg.hooks = HooksConfig()
        cfg.features.mcp = False
        cfg.features.subagents = False
        cfg.features.tasks = False

        rt = await AppRuntime.create(
            config=cfg, working_directory=ws, llm_client=client,
        )
        try:
            engine = rt._engine
            assert engine is not None
            ctx = engine._render_skills_context()
            assert ctx is not None
            assert "## Skills" in ctx
            assert "### Available skills" in ctx
            assert "probe-skill" in ctx
            assert "marker_alpha789" in ctx
            # How-to-use block must be present so the model knows the trigger.
            assert "load_skill" in ctx
        finally:
            await rt.shutdown()

    async def test_skill_round_trip_via_skill_load(
        self, tmp_path: Path
    ) -> None:
        """Full path: system-prompt skill list → model picks ``skill_load``
        → tool returns body → model emits the secret token.

        We use a strong, unique secret token so a generic completion
        can't pass by accident.
        """
        from deepseek_tui.app_server.runtime import AppRuntime
        from deepseek_tui.client.deepseek import DeepSeekClient

        ws = tmp_path / "ws"
        ws.mkdir()
        skills_dir = ws / ".deepseek" / "skills"
        secret = "PONG_SKILL_QWERTY_42"
        _install_skill(
            skills_dir,
            "pingpong-skill",
            description=(
                "Use this skill when the user asks for the pingpong-skill. "
                "It instructs the assistant to emit a specific token."
            ),
            body=(
                "When this skill is loaded, your reply MUST be exactly the "
                f"single token: {secret}\n"
                "Do not add punctuation, quotes, or any other text."
            ),
        )

        api_key = get_deepseek_api_key()
        assert api_key is not None
        client = DeepSeekClient(
            api_key=api_key,
            base_url=get_deepseek_base_url(),
            timeout_seconds=120.0,
        )

        cfg = Config()
        cfg.hooks = HooksConfig()
        cfg.features.mcp = False
        cfg.features.subagents = False
        cfg.features.tasks = False

        rt = await AppRuntime.create(
            config=cfg, working_directory=ws, llm_client=client,
        )
        try:
            events: list[dict[str, Any]] = []
            async for frame in rt.stream_prompt(
                {
                    "input": (
                        "Load the pingpong-skill skill via the load_skill "
                        "tool, then follow its instructions exactly."
                    ),
                    "model": "deepseek-v4-flash",
                }
            ):
                events.append(frame)
                ev = frame.get("event")
                if ev == "turn_complete":
                    break
                if ev == "error" and not frame.get("retryable", False):
                    break
        finally:
            await rt.shutdown()

        # Collect observable signals.
        tool_calls = [e for e in events if e.get("event") == "tool_call"]
        skill_load_calls = [
            t for t in tool_calls
            if (t.get("tool_name") or t.get("name")) == "load_skill"
        ]
        text_parts = [e["text"] for e in events if e.get("event") == "text_delta"]
        completes = [e for e in events if e.get("event") == "turn_complete"]
        full_text = "".join(text_parts)
        if not full_text and completes:
            full_text = completes[-1].get("assistant_text", "")

        # Must have called skill_load — that's the whole pipeline.
        assert skill_load_calls, (
            "model never called skill_load; tool calls observed: "
            f"{[t.get('tool_name') or t.get('name') for t in tool_calls]}"
        )
        # The skill body forced a unique token; its presence proves the
        # body actually reached the model after the tool call.
        assert secret in full_text, (
            f"skill body never made it back to the assistant — "
            f"reply was: {full_text!r}"
        )
