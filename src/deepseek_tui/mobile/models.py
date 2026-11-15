"""Safe model metadata and explicit discovery via the existing Workbench client."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/v1/model-catalog", tags=["models"])


def _provider(request: Request, provider: str):
    config = request.app.state.thread_manager.config
    if provider not in {config.provider, *config.providers}:
        raise HTTPException(404, "电脑没有配置此提供商")
    selected = config if provider == config.provider else config.model_copy(update={
        "provider": provider, "api_key": None, "base_url": None, "model": None,
    })
    try:
        return selected.effective_provider_config()
    except ValueError as exc:
        raise HTTPException(409, "提供商配置不完整，请在电脑上完成设置") from exc


@router.get("")
async def model_catalog(request: Request):
    config = request.app.state.thread_manager.config
    providers = []
    for name in sorted({config.provider, *config.providers}):
        try:
            settings = _provider(request, name)
        except HTTPException:
            providers.append({"id": name, "configured": False, "models": [], "discoverable": False})
            continue
        models = sorted({settings.model, *settings.context_windows, *settings.image_models} - {None, ""})
        providers.append({"id": name, "configured": bool(settings.api_key), "models": models,
                          "discoverable": settings.protocol == "openai" and bool(settings.base_url), "default_model": settings.model})
    return {"providers": providers, "active_provider": config.provider}


@router.post("/{provider}/refresh")
async def refresh_models(request: Request, provider: str):
    settings = _provider(request, provider)
    if settings.protocol != "openai":
        raise HTTPException(400, "此协议暂不提供模型发现，请使用电脑已配置模型或手动填写模型 ID")
    if not settings.base_url:
        raise HTTPException(409, "电脑尚未配置此提供商的 API 地址")
    if not settings.api_key:
        raise HTTPException(409, "电脑尚未配置此提供商的 API 密钥")
    helper = Path(os.environ.get("DEEPSEEK_MOBILE_MODELS_HELPER", ""))
    if not helper.is_file():
        raise HTTPException(503, "电脑尚未安装模型目录适配服务")
    process = await asyncio.create_subprocess_exec(
        os.environ.get("MOBILE_NODE_BINARY", "node"), str(helper),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(json.dumps({
            "baseUrl": settings.base_url, "apiKey": settings.api_key,
        }).encode()), 12)
        result = json.loads(output)
        if process.returncode or not result.get("ok"):
            raise HTTPException(502, "模型列表获取失败，请检查电脑配置或手动填写模型 ID")
        return {"provider": provider, "models": result["modelIds"], "source": "upstream"}
    except (TimeoutError, ValueError, KeyError) as exc:
        raise HTTPException(502, "模型目录服务超时或响应无效") from exc
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
