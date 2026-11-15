"""Authenticated mobile audio transport to the existing Workbench ASR service.

No provider credentials or provider implementation live in this router. Deployment
sets DEEPSEEK_MOBILE_ASR_HELPER to the App's scripts/asr-bridge.mjs and RUNTIME_SOURCE.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import os
from pathlib import Path
import wave

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/v1/voice", tags=["voice"])
_MAX_BYTES = 1_000_044
_MAX_BODY = 1_400_000
_gate = asyncio.Lock()


def validate_recording(encoded: object) -> bytes:
    if not isinstance(encoded, str) or len(encoded) > _MAX_BODY:
        raise HTTPException(413, "录音超过大小限制")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(400, "录音编码无效") from exc
    if not audio or len(audio) > _MAX_BYTES:
        raise HTTPException(413, "录音为空或超过大小限制")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            # The shared recorder produces mono PCM16 at 16 kHz. Allow the
            # 200 ms stop timer one second of scheduling tolerance at 30 s.
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("format")
            frames = wav.getnframes()
            if not 0 < frames <= 31 * 16000 or len(wav.readframes(frames)) != frames * 2:
                raise ValueError("duration")
    except (wave.Error, EOFError, ValueError) as exc:
        raise HTTPException(400, "需要不超过 30 秒的单声道 PCM16/16kHz WAV 录音") from exc
    return audio


async def _bridge(payload: dict) -> dict:
    helper = Path(os.environ.get("DEEPSEEK_MOBILE_ASR_HELPER", ""))
    if not helper.is_file():
        raise HTTPException(503, "电脑尚未安装语音适配服务")
    process = await asyncio.create_subprocess_exec(
        os.environ.get("MOBILE_NODE_BINARY", "node"), str(helper),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), 60)
        data = json.loads(stdout)
        if process.returncode or not isinstance(data, dict):
            raise HTTPException(503, "电脑语音服务暂不可用")
        return data
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(504, "语音服务超时或返回无效响应") from exc
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@router.get("/status")
async def voice_status() -> dict:
    return await _bridge({"action": "status"})


@router.post("/transcribe")
async def transcribe(request: Request) -> dict:
    # Bound before JSON parsing, including chunked requests without Content-Length.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BODY:
            raise HTTPException(413, "录音超过大小限制")
    try:
        payload = json.loads(body)
        encoded = payload.get("audio") if isinstance(payload, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "录音请求无效") from exc
    validate_recording(encoded)
    if _gate.locked():
        raise HTTPException(409, "已有录音正在转写，请稍后重试")
    async with _gate:
        result = await _bridge({"action": "transcribe", "audio": encoded})
    if not result.get("ok"):
        raise HTTPException(503 if result.get("code") == "not_configured" else 502,
                            result.get("message", "语音识别失败"))
    return {"text": result.get("text", "")}
