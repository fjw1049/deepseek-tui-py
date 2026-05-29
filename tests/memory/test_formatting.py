from deepseek_tui.memory.formatting import (
    strip_relevant_memories,
    wrap_relevant_memories,
)


def test_wrap_and_strip_roundtrip() -> None:
    user = "What is the pool size?"
    l1 = "- (instruction) DB pool is 50"
    wrapped = wrap_relevant_memories(user, l1)
    assert "<relevant-memories>" in wrapped
    assert user in wrapped
    stripped = strip_relevant_memories(wrapped)
    assert "<relevant-memories>" not in stripped
    assert stripped == user
