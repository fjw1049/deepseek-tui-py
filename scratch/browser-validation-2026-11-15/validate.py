"""Ten local real-browser scenarios; no model/API calls or personal website data.
Before policy is emulated by restoring only the old unknown-fill exemption.
"""
import asyncio
import importlib.util
import json
import tempfile
from pathlib import Path
import deepseek_tui.browser.service as module
from deepseek_tui.browser.service import BrowserService, BrowserAction
from deepseek_tui.browser.observation import evaluate

spec = importlib.util.spec_from_file_location('bench', 'scripts/browser_benchmark.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
OUTPUT = Path(__file__).parent / 'results.json'

async def scenario(name, kind='date', value='2026-11-15', mode='retry', old=False):
    service = BrowserService(Path(tempfile.mkdtemp(prefix='browser-validation-')))
    service.configure('t', persistent=False)
    body = (f'<label for="draft">Draft</label><input id="draft" type="{kind}">'
            '<p id="saved"></p><script>window.saves=0;'
            'document.querySelector("input").onchange=()=>{window.saves++;'
            'document.querySelector("p").textContent="Saved "+window.saves}</script>').encode()
    server, url = await b.serve_fixture(body)
    try:
        await service.action('t', BrowserAction(action='open', url=url))
        if old:
            remember = service._remember_response
            def legacy(run, response, **kwargs):
                result = remember(run, response, **kwargs)
                if response['receipt']['action'] == 'fill':
                    run.unresolved.pop(response['receipt']['action_id'], None)
                return result
            service._remember_response = legacy
        original = module.target_state
        injected = False
        async def lost(*args, **kwargs):
            nonlocal injected
            result = await original(*args, **kwargs)
            if any(isinstance(x, str) and 'dispatchEvent' in x for x in args):
                injected = True
                raise TimeoutError('Injected lost response after real browser change event')
            return result
        module.target_state = lost
        try:
            await service.action('t', BrowserAction(action='fill', selector='#draft', text=value))
        except Exception as exc:
            if "Injected lost response" not in str(exc):
                raise
        finally:
            module.target_state = original
        assert injected, 'Fault did not reach intended boundary'
        await service.action('t', BrowserAction(action='observe'))
        run = service.runs['t']
        truth = await evaluate(run.session._internal.client, '({saves:window.saves,value:document.querySelector("input").value})')
        assert truth['saves'] == 1 and truth['value'] == value, truth
        pending = list(run.unresolved)
        if mode == 'persist':
            await service.close('t')
            passed = bool(service.state('t')['unresolved'])
            return dict(name=name, policy='before' if old else 'after', passed=passed, truth=truth)
        if mode == 'check':
            check = await service.action('t', BrowserAction(action='check_text', selector='#saved', text='Saved 1'))
            passed = check['success'] and bool(run.unresolved)
        elif mode == 'review':
            if pending:
                await service.action('t', BrowserAction(action='resolve_operation', operation_id=pending[0], outcome='executed', reason='Synthetic reviewer checked saved value'), actor='user')
            result = await service.action('t', BrowserAction(action='fill', selector='#draft', text='2026-11-16'))
            truth = await evaluate(run.session._internal.client, '({saves:window.saves,value:document.querySelector("input").value})')
            passed = result['success'] and truth == {'saves': 2, 'value': '2026-11-16'} and not run.unresolved
        else:
            result = await service.action('t', BrowserAction(action='fill', selector='#draft', text=value))
            truth = await evaluate(run.session._internal.client, '({saves:window.saves,value:document.querySelector("input").value})')
            passed = not result['success'] and truth['saves'] == 1
        return dict(name=name, policy='before' if old else 'after', passed=bool(passed), truth=truth)
    finally:
        await service.close_all()
        server.close()
        await server.wait_closed()

async def main():
    results = []
    cases = [('日程日期自动保存', 'date', '2026-11-15', 'retry'),
             ('提醒时间自动保存', 'time', '09:30', 'retry'),
             ('主题颜色自动保存', 'color', '#123456', 'retry'),
             ('音量范围自动保存', 'range', '75', 'retry'),
             ('异常后读取保存状态仍保留未决', 'date', '2026-11-15', 'check'),
             ('关闭会话后仍保留未决', 'date', '2026-11-15', 'persist'),
             ('核对后继续下一次合法编辑', 'date', '2026-11-15', 'review')]
    for name, kind, value, mode in cases:
        for old in (True, False):
            try:
                result = await scenario(name, kind, value, mode, old)
            except Exception as exc:
                result = dict(name=name, policy='before' if old else 'after', passed=False, error=str(exc))
            results.append(result)
            OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
            print(json.dumps(result, ensure_ascii=False), flush=True)
    for language, variant in [('en', 0), ('zh', 1), ('en', 2)]:
        service = BrowserService(Path(tempfile.mkdtemp(prefix='browser-normal-')))
        server, url = await b.serve_fixture(b.fixture(language, variant))
        try:
            result = await b.deterministic_case(service, 't', url)
            results.append(dict(name=f'正常草稿保存-{language}-{variant}', policy='after', passed=result['completed'], truth=result['truth']))
        finally:
            await service.close_all();server.close();await server.wait_closed()
        OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({'after_passed':sum(r['passed'] for r in results if r['policy']=='after'), 'after_total':10}))

asyncio.run(main())
