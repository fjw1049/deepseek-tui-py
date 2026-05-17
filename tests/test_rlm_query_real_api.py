"""Real API integration test for rlm_query and review tools.

Tests that RlmQueryTool and ReviewTool can successfully load config
and create a working DeepSeekClient when called with real API credentials.

This test validates the fix for the bug where these tools were creating
empty Config() objects instead of loading the actual configuration file.
"""

import pytest

from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.knowledge_tools import RlmQueryTool, ReviewTool
from tests._real_api import has_deepseek_api_key


@pytest.mark.skipif(
    not has_deepseek_api_key(),
    reason="需要 DEEPSEEK_API_KEY 环境变量或项目 config.toml 里的 api_key",
)
@pytest.mark.asyncio
async def test_rlm_query_with_real_config(tmp_path):
    """Test that RlmQueryTool loads config correctly and can make real API calls."""
    # Load real config (this should pick up API key from env or config.toml)
    config = ConfigLoader().load()

    # Create tool with config
    tool = RlmQueryTool(config=config)

    # Create minimal context
    context = ToolContext(working_directory=tmp_path)

    # Execute a simple query
    result = await tool.execute(
        {"query": "What is 2+2? Reply with just the number."},
        context,
    )

    # Verify success
    assert result.success, f"Tool failed: {result.content}"
    assert result.content is not None
    assert len(result.content) > 0
    print(f"✓ rlm_query returned: {result.content[:100]}")


@pytest.mark.skipif(
    not has_deepseek_api_key(),
    reason="需要 DEEPSEEK_API_KEY 环境变量或项目 config.toml 里的 api_key",
)
@pytest.mark.asyncio
async def test_rlm_query_without_explicit_config(tmp_path):
    """Test that RlmQueryTool can auto-load config when none is provided."""
    # Create tool without explicit config (should auto-load)
    tool = RlmQueryTool(config=None)

    # Create minimal context
    context = ToolContext(working_directory=tmp_path)

    # Execute a simple query
    result = await tool.execute(
        {"query": "Say 'hello' in one word."},
        context,
    )

    # Verify success
    assert result.success, f"Tool failed: {result.content}"
    assert result.content is not None
    assert len(result.content) > 0
    print(f"✓ rlm_query (auto-config) returned: {result.content[:100]}")


@pytest.mark.skipif(
    not has_deepseek_api_key(),
    reason="需要 DEEPSEEK_API_KEY 环境变量或项目 config.toml 里的 api_key",
)
@pytest.mark.asyncio
async def test_review_tool_with_real_config(tmp_path):
    """Test that ReviewTool loads config correctly and can make real API calls."""
    # Create a simple test file
    test_file = tmp_path / "test.py"
    test_file.write_text("def add(a, b):\n    return a + b\n")

    # Load real config
    config = ConfigLoader().load()

    # Create tool with config
    tool = ReviewTool(config=config)

    # Create context
    context = ToolContext(working_directory=tmp_path)

    # Execute review
    result = await tool.execute(
        {"target": str(test_file)},
        context,
    )

    # Verify success
    assert result.success, f"Tool failed: {result.content}"
    assert result.content is not None
    assert len(result.content) > 0
    print(f"✓ review returned: {result.content[:200]}")


if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path

    # Run tests manually
    tmp = Path("/tmp/test_rlm_query")
    tmp.mkdir(exist_ok=True)

    print("Testing rlm_query with real config...")
    asyncio.run(test_rlm_query_with_real_config(tmp))

    print("\nTesting rlm_query without explicit config...")
    asyncio.run(test_rlm_query_without_explicit_config(tmp))

    print("\nTesting review tool with real config...")
    asyncio.run(test_review_tool_with_real_config(tmp))

    print("\n✓ All tests passed!")
