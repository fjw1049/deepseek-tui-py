"""Offline payload comparison: bypass only the new request-local cache decorator."""

import io
import json
import os
import random
import statistics
import tempfile
import time
from unittest.mock import patch

from PIL import Image

from deepseek_tui import media
from deepseek_tui.client.anthropic import AnthropicCompatClient
from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.protocol.messages import Message, MessageRequest


def compare():
    data = io.BytesIO()
    Image.frombytes("RGB", (512, 512), random.Random(0).randbytes(512 * 512 * 3)).save(
        data, format="PNG"
    )
    request = MessageRequest(
        model="fixture",
        messages=[Message.user("fixture", images=[media.import_image(data.getvalue())])],
    )
    result = {}
    for client_type in [DeepSeekClient, AnthropicCompatClient]:
        client = client_type(api_key="fake", base_url="https://example.invalid")
        samples = {"uncached": [], "request_cache": []}
        counts = {key: [] for key in samples}
        for _ in range(5):
            outputs = []
            for variant in samples:
                with patch(
                    "deepseek_tui.media._encode_image_data_url", wraps=media._encode_image_data_url
                ) as encode:
                    started = time.perf_counter()
                    output = (
                        client._build_payload.__wrapped__(client, request)
                        if variant == "uncached"
                        else client._build_payload(request)
                    )
                    samples[variant].append((time.perf_counter() - started) * 1000)
                    counts[variant].append(encode.call_count)
                    outputs.append(output)
            assert outputs[0] == outputs[1]
        result[client_type.__name__] = {
            key: {"median_ms": round(statistics.median(values), 3), "encode_counts": counts[key]}
            for key, values in samples.items()
        }
    return result


if __name__ == "__main__":
    with (
        tempfile.TemporaryDirectory(prefix="audit08-compare-") as home,
        patch.dict(os.environ, {"DEEPSEEK_HOME": home}),
    ):
        print(json.dumps(compare(), indent=2))
