import json
from types import SimpleNamespace

import httpx
import pytest

from deepseek_tui.tools import web
from deepseek_tui.tools.registry import ToolError


@pytest.fixture
def mock_api(monkeypatch):
    def install(handler):
        factory = httpx.AsyncClient
        monkeypatch.setattr(web.httpx, "AsyncClient", lambda **kw: factory(
            transport=httpx.MockTransport(handler), **kw
        ))
    return install


@pytest.mark.asyncio
async def test_search_request_and_result(mock_api):
    def handler(request):
        assert str(request.url) == 'https://api.deepseek.com/v1/tools/search'
        assert request.headers['authorization'] == 'Bearer test-key'
        assert json.loads(request.content) == {
            'query': 'test', 'count': 50, 'need_content': False
        }
        return httpx.Response(200, json={'results': [{
            'title': 'Title', 'url': 'https://example.com',
            'summary': 'Long summary', 'snippet': 'Short'
        }]})
    mock_api(handler)
    result = await web.WebSearchTool(deepseek_api_key='test-key', providers=['deepseek']).execute(
        {'query': 'test', 'max_results': 100}, object()
    )
    assert result.metadata['provider'] == 'deepseek'
    assert 'Long summary' in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    httpx.Response(401), httpx.Response(429), httpx.Response(504),
    httpx.Response(200, json={'results': []}),
    httpx.Response(200, json={'results': None}),
    httpx.Response(200, text='invalid'),
])
async def test_search_fallback(mock_api, monkeypatch, response):
    mock_api(lambda request: response)
    async def fallback(*args, **kwargs):
        return [web._SearchHit('Fallback', 'https://example.com', 'ok', 'anysearch')]
    monkeypatch.setattr(web, '_search_anysearch', fallback)
    result = await web.WebSearchTool(deepseek_api_key='test-key', providers=['deepseek', 'anysearch']).execute(
        {'query': 'test'}, object()
    )
    assert result.metadata['provider'] == 'anysearch'


@pytest.mark.asyncio
async def test_search_long_query_and_missing_key(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    with pytest.raises(ToolError, match='128 characters'):
        await web.WebSearchTool(providers=['deepseek']).execute({'query': '字' * 129}, object())
    with pytest.raises(ToolError, match='key is missing'):
        await web.WebSearchTool(providers=['deepseek']).execute({'query': 'test'}, object())


@pytest.mark.asyncio
@pytest.mark.parametrize('content', ['# Markdown', '', None])
async def test_fetch_selected_provider_and_fallback(mock_api, monkeypatch, content):
    def handler(request):
        assert str(request.url) == 'https://api.deepseek.com/v1/tools/fetch'
        assert json.loads(request.content) == {'url': 'https://8.8.8.8/page'}
        return httpx.Response(200, json={'title': 'Page', 'content': content})
    mock_api(handler)
    async def fallback(*args, **kwargs):
        return 'AnySearch fallback'
    monkeypatch.setattr(web, '_anysearch_extract', fallback)
    result = await web.FetchUrlTool(deepseek_api_key='test-key', providers=['deepseek', 'anysearch']).execute(
        {'url': 'https://8.8.8.8/page'}, SimpleNamespace(timeout_ms=None)
    )
    assert result.content == (content or 'AnySearch fallback')
    assert result.metadata['backend'] == ('deepseek' if content else 'anysearch_extract')


@pytest.mark.asyncio
async def test_fetch_direct_resource_stays_direct(mock_api):
    def handler(request):
        assert request.method == 'GET'
        assert request.url.host == '8.8.8.8'
        return httpx.Response(200, text='raw text')
    mock_api(handler)
    result = await web.FetchUrlTool(providers=['deepseek', 'anysearch']).execute(
        {'url': 'https://8.8.8.8/doc.txt'}, SimpleNamespace(timeout_ms=None)
    )
    assert result.metadata['backend'] == 'direct'


@pytest.mark.asyncio
@pytest.mark.parametrize('providers,empty_anysearch,expected', [
    (['anysearch', 'deepseek'], False, ['anysearch']),
    (['anysearch', 'deepseek'], True, ['anysearch', 'deepseek']),
    (['deepseek', 'anysearch'], False, ['deepseek']),
    (['tavily', 'deepseek'], False, ['deepseek']),
    (['DeepSeek', 'deepseek'], True, ['deepseek']),
    # Search settings never take away AnySearch extraction.
    (['tavily'], False, ['anysearch']),
    ([], False, ['anysearch']),
    ([], True, ['anysearch', 'direct']),
    (None, False, ['anysearch']),
])
async def test_fetch_follows_enabled_order(monkeypatch, providers, empty_anysearch, expected):
    called = []

    async def anysearch(*args, **kwargs):
        called.append('anysearch')
        return '' if empty_anysearch else 'AnySearch content'

    async def deepseek(*args, **kwargs):
        called.append('deepseek')
        return {'content': 'DeepSeek content'}

    async def direct(*args, **kwargs):
        called.append('direct')
        return httpx.Response(200, text='Direct content', request=httpx.Request('GET', args[1]))

    monkeypatch.setattr(web, '_anysearch_extract', anysearch)
    monkeypatch.setattr(web, '_deepseek_request', deepseek)
    monkeypatch.setattr(web, '_http_get', direct)
    await web.FetchUrlTool(providers=providers).execute(
        {'url': 'https://8.8.8.8/page'}, SimpleNamespace(timeout_ms=None)
    )
    assert called == expected
