"""One image, one explicitly selected real-model request; no retries or vision helper."""
import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

from deepseek_tui.client import RetryConfig, build_llm_client
from deepseek_tui.client.network import read_network_settings
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.media import import_image
from deepseek_tui.protocol.messages import Message, MessageRequest
from deepseek_tui.protocol.responses import StreamDone, StreamError, StreamRetry, StreamTextDelta


async def main(args):
    cfg = ConfigLoader().load()
    cfg.provider, cfg.model = args.provider, args.model
    # Use only the explicitly named provider's credentials/endpoint.
    cfg.base_url = cfg.api_key = None
    cfg.vision.model = None
    client = build_llm_client(cfg)
    client.retry_config = RetryConfig(max_transparent_retries=0, max_error_retries=0)
    network = read_network_settings()
    # Do not write test media into the user's conversation data.
    with tempfile.TemporaryDirectory(prefix="viewport-model-") as root:
        await asyncio.to_thread(Path(root, "network.json").write_text, network.model_dump_json())
        os.environ["DEEPSEEK_HOME"] = root
        image = import_image(args.image.read_bytes())
        request = MessageRequest(
            model=args.model, max_tokens=1024,
            messages=[Message.user(
                f"这是本地开发机管理页面的截图，原始尺寸 {image.width}×{image.height}。"
                "请找出配置名为 data-analysis-demo 的那一行的绿色 Open IDE 按钮，"
                "返回它的中心点坐标。不要选择 Delete。坐标必须基于整张截图左上角，"
                '只输出 JSON，例如 {"x":123,"y":456}，不要解释。', images=[image])],
        )
        result = {"provider": args.provider, "model": args.model, "request_limit": 1,
                  "output_token_limit": 1024, "image": str(args.image), "answer": ""}
        try:
            async with asyncio.timeout(90):
                async for event in client.stream_chat_completion(request):
                    if isinstance(event, StreamTextDelta):
                        result["answer"] += event.text
                    elif isinstance(event, StreamDone):
                        result["usage"] = event.usage.model_dump() if event.usage else None
                        result["truncated"] = event.truncated
                    elif isinstance(event, (StreamError, StreamRetry)):
                        raise RuntimeError("Model request failed; no automatic retry")
            answer = result["answer"].strip()
            answer = answer.removeprefix("```json").removeprefix("```").removesuffix("```")
            point = json.loads(answer)
            if not all(isinstance(point.get(k), (int, float)) for k in ("x", "y")):
                raise ValueError("Model did not return coordinates")
            if not (0 <= point["x"] < image.width and 0 <= point["y"] < image.height):
                raise ValueError("Model coordinates are outside the screenshot")
            result["point"] = {k: point[k] for k in ("x", "y")}
        except Exception as exc:
            result["error"] = type(exc).__name__
            response = getattr(exc, "response", None)
            if response is not None:
                result["http_status"] = response.status_code
        finally:
            await client.close()
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if "point" not in result:
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
