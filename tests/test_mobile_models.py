from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI
from deepseek_tui.config.models import Config, ProviderConfig
from deepseek_tui.mobile.models import router


@pytest.mark.asyncio
async def test_catalog_returns_only_safe_metadata_and_no_network(monkeypatch):
    config = Config(provider='deepseek', api_key='never-return-key', model='configured-model', providers={
        'custom': ProviderConfig(model='custom-default', api_key='private-custom-key', base_url='https://private.example/v1', context_windows={'custom-other': 1024}),
    })
    app = FastAPI()
    app.state.thread_manager = SimpleNamespace(config=config)
    app.include_router(router)
    async def no_process(*a, **kw):
        pytest.fail('Catalog listing must not launch network/helper process')
    monkeypatch.setattr('asyncio.create_subprocess_exec', no_process)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/v1/model-catalog')
        assert response.status_code == 200
        assert all(secret not in response.text for secret in ('never-return-key', 'private-custom-key', 'private.example'))
        rows = {row['id']: row for row in response.json()['providers']}
        assert rows['custom']['models'] == ['custom-default', 'custom-other']
        assert rows['deepseek']['models'] == ['configured-model']
        assert (await client.post('/v1/model-catalog/unknown/refresh')).status_code == 404


@pytest.mark.asyncio
async def test_custom_missing_endpoint_never_falls_back_and_sends_secret_elsewhere(monkeypatch):
    app = FastAPI()
    app.state.thread_manager = SimpleNamespace(config=Config(provider='custom', providers={
        'custom': ProviderConfig(model='model', api_key='custom-key'),
    }))
    app.include_router(router)
    async def no_process(*a, **kw):
        pytest.fail('Incomplete custom config must not launch a helper')
    monkeypatch.setattr('asyncio.create_subprocess_exec', no_process)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/v1/model-catalog')).json()['providers'][0]['discoverable'] is False
        assert (await client.post('/v1/model-catalog/custom/refresh')).status_code == 409
