"""真实 API 端到端测试（需要真实 API key）。

Key 解析顺序：

1. ``DEEPSEEK_API_KEY`` 环境变量
2. 项目根目录 ``config.toml`` 的 ``[providers.deepseek] api_key``
3. 都没有则跳过

实现细节见 :mod:`tests._real_api`。
"""

import asyncio

import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest
from tests._real_api import (
    get_deepseek_api_key,
    get_deepseek_base_url,
    has_deepseek_api_key,
)


@pytest.mark.skipif(
    not has_deepseek_api_key(),
    reason="需要 DEEPSEEK_API_KEY 环境变量或项目 config.toml 里的 api_key",
)
@pytest.mark.asyncio
async def test_real_api_call_flash() -> None:
    """测试真实的 DeepSeek API 调用（flash 模型）。"""
    api_key = get_deepseek_api_key()
    assert api_key is not None

    client = DeepSeekClient(
        api_key=api_key,
        base_url=get_deepseek_base_url(),
    )

    request = MessageRequest(
        model="deepseek-v4-flash",
        messages=[
            Message.user("你好，请回复：收到"),
        ],
        max_tokens=50,
        stream=True,
    )

    # 收集流式响应
    events = []
    async for event in client.stream_chat_completion(request):
        events.append(event)

    # 验证收到了响应
    assert len(events) > 0
    print(f"✓ 收到 {len(events)} 个事件")

    # 验证有文本或 thinking 事件
    event_types = {e.type for e in events}
    assert len(event_types) > 0
    print(f"✓ 事件类型: {event_types}")


@pytest.mark.skipif(
    not has_deepseek_api_key(),
    reason="需要 DEEPSEEK_API_KEY 环境变量或项目 config.toml 里的 api_key",
)
@pytest.mark.asyncio
async def test_real_api_call_pro() -> None:
    """测试真实的 DeepSeek API 调用（pro 模型）。"""
    api_key = get_deepseek_api_key()
    assert api_key is not None

    client = DeepSeekClient(
        api_key=api_key,
        base_url=get_deepseek_base_url(),
    )

    request = MessageRequest(
        model="deepseek-v4-pro",
        messages=[
            Message.user("计算 123 + 456 = ?"),
        ],
        max_tokens=100,
        stream=True,
    )

    # 收集流式响应
    chunks = []
    async for event in client.stream_chat_completion(request):
        chunks.append(event)

    # 验证收到了响应
    assert len(chunks) > 0
    print(f"✓ Pro 模型收到 {len(chunks)} 个事件")


if __name__ == "__main__":
    # 直接运行测试
    if has_deepseek_api_key():
        print("运行真实 API 测试...")
        asyncio.run(test_real_api_call_flash())
        print("\n" + "=" * 50 + "\n")
        asyncio.run(test_real_api_call_pro())
    else:
        print("跳过：未找到 DEEPSEEK_API_KEY 或项目 config.toml")
