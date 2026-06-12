from deepseek_tui.memory.coordinator import should_capture_turn


def test_capture_skips_short_confirmation_without_tools() -> None:
    assert not should_capture_turn(
        "好的",
        had_tool_calls=False,
        success=True,
        min_chars=20,
    )


def test_capture_allows_short_text_with_tools() -> None:
    assert should_capture_turn(
        "好",
        had_tool_calls=True,
        success=True,
        min_chars=20,
    )


def test_capture_allows_substantive_short_instruction_with_tools() -> None:
    assert should_capture_turn(
        "帮改成 async",
        had_tool_calls=True,
        success=True,
    )


def test_capture_skips_slash_commands() -> None:
    assert not should_capture_turn(
        "/compact",
        had_tool_calls=False,
        success=True,
    )


def test_capture_skips_failed_turn() -> None:
    assert not should_capture_turn(
        "long enough user message here",
        had_tool_calls=False,
        success=False,
    )
