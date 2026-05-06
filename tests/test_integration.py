"""端到端集成测试 - 验证模块衔接。"""

import tempfile
from pathlib import Path

import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.protocol.messages import Message, Role
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.secrets.manager import SecretsManager
from deepseek_tui.state.database import Database
from deepseek_tui.tools import build_default_registry


@pytest.mark.asyncio
async def test_config_to_secrets_integration() -> None:
    """测试配置系统到密钥管理的集成。"""
    loader = ConfigLoader()
    config = loader.load()
    secrets = SecretsManager()

    # 应该能够解析 API key（即使为 None）
    api_key = secrets.resolve_api_key(config, "deepseek")
    assert api_key is None or isinstance(api_key, str)

    # 应该能够列出 providers
    providers = secrets.list_providers(config)
    assert isinstance(providers, list)
    assert "deepseek" in providers


@pytest.mark.asyncio
async def test_database_initialization() -> None:
    """测试数据库初始化和基本操作。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        db = Database(db_path)
        await db.initialize()

        # 验证数据库文件存在
        assert db_path.exists()

        # 验证可以连接
        conn = await db.connect()
        assert conn is not None
    finally:
        db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_tool_registry_integration() -> None:
    """测试工具注册表和工具执行。"""
    registry = build_default_registry()

    # 验证工具已注册
    api_tools = registry.to_api_tools()
    assert len(api_tools) > 0

    # 验证可以获取工具
    tool = registry.get("read_file")
    assert tool is not None
    assert tool.name() == "read_file"


def test_client_initialization() -> None:
    """测试 LLM 客户端初始化。"""
    client = DeepSeekClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
    )

    assert client.api_key == "test-key"
    assert client.base_url == "https://api.deepseek.com"
    assert client.timeout_seconds == 90.0


@pytest.mark.asyncio
async def test_message_request_building() -> None:
    """测试消息请求构建。"""
    request = MessageRequest(
        model="deepseek-v4-pro",
        messages=[
            Message.user("Hello"),
        ],
        max_tokens=1000,
        temperature=0.7,
    )

    assert request.model == "deepseek-v4-pro"
    assert len(request.messages) == 1
    assert request.messages[0].role == Role.USER
    assert request.max_tokens == 1000
    assert request.temperature == 0.7


@pytest.mark.asyncio
async def test_config_to_client_flow() -> None:
    """测试从配置到客户端的完整流程。"""
    # 1. 加载配置
    loader = ConfigLoader()
    config = loader.load()

    # 2. 解析密钥
    secrets = SecretsManager()
    api_key = secrets.resolve_api_key(config, config.provider)

    # 3. 获取 provider 配置
    provider_config = config.effective_provider_config()

    # 4. 创建客户端（使用测试 key）
    client = DeepSeekClient(
        api_key=api_key or "test-key",
        base_url=provider_config.base_url or "https://api.deepseek.com",
        timeout_seconds=float(provider_config.timeout),
    )

    assert client is not None
    assert client.base_url.startswith("https://")


@pytest.mark.asyncio
async def test_full_stack_initialization() -> None:
    """测试完整技术栈的初始化。"""
    # 1. 配置层
    loader = ConfigLoader()
    config = loader.load()
    assert config is not None

    # 2. 密钥层
    secrets = SecretsManager()
    api_key = secrets.resolve_api_key(config, config.provider)

    # 3. 持久化层
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        db = Database(db_path)
        await db.initialize()

        # 4. 工具层
        registry = build_default_registry()
        assert len(registry.to_api_tools()) > 0

        # 5. 客户端层
        provider_config = config.effective_provider_config()
        client = DeepSeekClient(
            api_key=api_key or "test-key",
            base_url=provider_config.base_url or "https://api.deepseek.com",
        )
        assert client is not None

        print("✓ 完整技术栈初始化成功")
        print(f"  - 配置: {config.provider}")
        print(f"  - 数据库: {db_path}")
        print(f"  - 工具数: {len(registry.to_api_tools())}")
        print(f"  - 客户端: {client.base_url}")

    finally:
        db_path.unlink(missing_ok=True)
