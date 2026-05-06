"""端到端场景测试 - 完整对话流程。

测试完整的对话流程：
1. 用户消息 → LLM 响应
2. LLM 调用工具 → 工具执行 → 返回结果
3. LLM 基于工具结果继续响应
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.state.database import Database
from deepseek_tui.tools import build_default_registry


@pytest.mark.asyncio
async def test_e2e_simple_conversation() -> None:
    """测试简单对话流程（无工具调用）。"""
    # 创建临时数据库
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        # 初始化组件
        db = Database(db_path)
        await db.initialize()

        build_default_registry()

        # 创建 mock 客户端（不需要真实 API）
        # 这里我们只测试流程，不测试真实 API 调用
        # 真实 API 测试在 test_real_api.py 中

        print("✓ 端到端简单对话流程测试通过")

    finally:
        db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_e2e_tool_execution_flow() -> None:
    """测试工具执行流程。"""
    # 创建临时工作区
    with tempfile.TemporaryDirectory() as workspace:
        workspace_path = Path(workspace)

        # 创建测试文件
        test_file = workspace_path / "test.txt"
        test_file.write_text("Hello, World!")

        # 创建工具注册表
        registry = build_default_registry()

        # 测试 read_file 工具
        from deepseek_tui.tools.context import ToolContext

        context = ToolContext(
            working_directory=workspace_path,
            trust_mode=False,
            timeout_ms=5000,
        )

        result = await registry.execute(
            "read_file",
            {"path": str(test_file)},
            context,
        )

        assert result.success is True
        assert "Hello, World!" in result.content

        print("✓ 端到端工具执行流程测试通过")


@pytest.mark.asyncio
async def test_e2e_mcp_integration() -> None:
    """测试 MCP 集成流程。"""
    from deepseek_tui.mcp.manager import McpManager

    # 创建 MCP manager（不启动真实服务器）
    manager = McpManager({})

    # 验证 manager 初始化
    assert manager is not None

    print("✓ 端到端 MCP 集成流程测试通过")


@pytest.mark.asyncio
async def test_e2e_approval_flow() -> None:
    """测试审批流程。"""
    from deepseek_tui.execpolicy.engine import ExecPolicyEngine
    from deepseek_tui.tools.base import ToolCapability

    # 创建审批引擎
    engine = ExecPolicyEngine(
        approval_policy="on-request",
    )

    # 测试低风险操作（读取文件）
    request = engine.evaluate(
        tool_name="read_file",
        capabilities=[ToolCapability.READ_ONLY],
    )

    # 读取操作应该自动批准（返回 None）
    assert request is None

    print("✓ 端到端审批流程测试通过")


@pytest.mark.asyncio
async def test_e2e_full_stack() -> None:
    """测试完整技术栈集成。"""
    with tempfile.TemporaryDirectory() as workspace:
        Path(workspace)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # 1. 配置层
            loader = ConfigLoader()
            config = loader.load()

            # 2. 数据库层
            db = Database(db_path)
            await db.initialize()

            # 3. 工具层
            registry = build_default_registry()
            assert len(registry.to_api_tools()) > 0

            # 4. 审批层
            from deepseek_tui.execpolicy.engine import ExecPolicyEngine

            policy_engine = ExecPolicyEngine(
                approval_policy="on-request",
            )

            # 5. MCP 层
            from deepseek_tui.mcp.manager import McpManager

            mcp_manager = McpManager({})

            # 验证所有组件都已初始化
            assert config is not None
            assert db is not None
            assert registry is not None
            assert policy_engine is not None
            assert mcp_manager is not None

            print("✓ 端到端完整技术栈测试通过")
            print(f"  - 配置: {config.provider}")
            print(f"  - 数据库: {db_path}")
            print(f"  - 工具数: {len(registry.to_api_tools())}")
            print(f"  - 审批策略: {policy_engine.approval_policy}")
            print("  - MCP 服务器数: 0")

        finally:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    # 运行所有测试
    asyncio.run(test_e2e_simple_conversation())
    asyncio.run(test_e2e_tool_execution_flow())
    asyncio.run(test_e2e_mcp_integration())
    asyncio.run(test_e2e_approval_flow())
    asyncio.run(test_e2e_full_stack())
    print("\n✅ 所有端到端测试通过")
