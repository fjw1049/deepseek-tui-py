from deepseek_tui.engine.prompts import BASE_PROMPT


def test_base_prompt_has_no_deepseek_v4_assumptions() -> None:
    prompt = BASE_PROMPT()

    for stale_assumption in (
        "DeepSeek V4",
        "V4 architecture",
        "1\u202fM-token context window",
        "V4 caches shared prefixes",
        "$0.14/M input",
    ):
        assert stale_assumption not in prompt
