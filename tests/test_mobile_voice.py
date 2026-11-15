"""Offline checks; these never contact a transcription provider."""
import base64
import io
import wave

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from deepseek_tui.mobile import voice as mobile_voice


def wav_bytes(seconds=0.1, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\x00\x00' * int(seconds * 16000) * channels)
    return buf.getvalue()


@pytest.mark.parametrize('audio', [b'', b'not-wav', wav_bytes(channels=2), wav_bytes(32)])
def test_invalid_recordings_rejected(audio):
    with pytest.raises(HTTPException):
        mobile_voice.validate_recording(base64.b64encode(audio).decode())


def test_recording_length_checked_against_real_frames():
    audio = wav_bytes()
    assert mobile_voice.validate_recording(base64.b64encode(audio).decode()) == audio
    with pytest.raises(HTTPException):
        mobile_voice.validate_recording(base64.b64encode(audio[:-8]).decode())


@pytest.mark.asyncio
async def test_status_and_upload_forward_only_fixed_audio_fields(monkeypatch):
    calls = []
    async def bridge(payload):
        calls.append(payload)
        return {'configured': False} if payload['action'] == 'status' else {'ok': True, 'text': '测试录音'}
    monkeypatch.setattr(mobile_voice, '_bridge', bridge)
    app = FastAPI()
    app.include_router(mobile_voice.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/v1/voice/status')).json() == {'configured': False}
        invalid = await client.post('/v1/voice/transcribe', json={'audio': 'no'})
        assert invalid.status_code == 400
        encoded = base64.b64encode(wav_bytes()).decode()
        response = await client.post('/v1/voice/transcribe', json={'audio': encoded, 'apiKey': 'ignored', 'endpoint': 'ignored'})
        assert response.json() == {'text': '测试录音'}
        assert calls == [{'action': 'status'}, {'action': 'transcribe', 'audio': encoded}]


@pytest.mark.asyncio
async def test_unconfigured_asr_and_oversize_do_not_report_success(monkeypatch):
    async def bridge(payload):
        return {'ok': False, 'code': 'not_configured', 'message': 'ASR 未配置'}
    monkeypatch.setattr(mobile_voice, '_bridge', bridge)
    app = FastAPI()
    app.include_router(mobile_voice.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/v1/voice/transcribe', json={'audio': base64.b64encode(wav_bytes()).decode()})
        assert response.status_code == 503
        oversized = await client.post('/v1/voice/transcribe', content=b'x' * 1400001)
        assert oversized.status_code == 413
