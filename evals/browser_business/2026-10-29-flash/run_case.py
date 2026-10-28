"""Real model + production Engine loop. One fresh profile per repeated case."""
import argparse
import asyncio
import csv
import dataclasses
import html
import json
import logging
import re
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from fixtures import CUSTOMERS, OLD_REPORT, ORDERS, REFUNDS, page
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.client import build_llm_client
from deepseek_tui.browser.service import BrowserService
from deepseek_tui.browser.observation import evaluate
from deepseek_tui.engine.handle import EngineHandle, ApprovalHandler
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.prompts import build_system_prompt
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.approval import ApprovalDecision

logging.basicConfig(level=logging.ERROR)
PUBLIC = 'https://books.toscrape.com/catalogue/category/books/travel_2/index.html'

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = page(urlparse(self.path).path).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html;charset=utf-8')
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

class Approval(ApprovalHandler):
    async def request_approval(self, tool_call_id, request):
        allowed = {'browser_use', 'read_file', 'file_search', 'grep_files', 'exec_shell',
                   'write_file', 'edit_file', 'apply_patch', 'finish_task', 'request_task_tools',
                   'checklist_add', 'checklist_update', 'checklist_list'}
        return (ApprovalDecision.APPROVED if request.tool_name in allowed
                and not request.force_prompt else ApprovalDecision.DENIED)

class ScopedBrowser:
    def __init__(self, service, host, public):
        self.service, self.host, self.public = service, host, public
    def __getattr__(self, name):
        return getattr(self.service, name)
    async def action(self, thread_id, action, **kwargs):
        if action.url and urlparse(action.url).hostname not in {self.host, 'books.toscrape.com'}:
            raise ValueError('This evaluation only authorizes the specified test sites')
        if self.public and action.action not in {
            'status', 'open', 'observe', 'describe', 'scroll', 'check_text', 'wait', 'back',
            'forward', 'recover', 'screenshot', 'tabs', 'new_tab', 'switch_tab', 'close_tab',
            'click', 'hover', 'reload', 'operation_status'}:
            raise ValueError('Public book catalog evaluation is read-only')
        return await self.service.action(thread_id, action, **kwargs)


def queries(case, base):
    if case == 'shopping':
        return [f'请用浏览器查看 {PUBLIC} 的 Travel 分类，为读书会选书。只选有货且标价不超过 £30 的书，按价格从低到高列出最便宜的三本（不足三本就列实际数量），给出完整书名、价格和商品链接，不买书。',
                '预算改成每本不超过 £20，只保留最便宜的两本。请基于刚才那个分类重新确认，明确说明最终有几本符合条件，不要推荐超预算的。']
    if case == 'crm':
        return [f'打开 {base}/crm 客户工作台，筛选华东区域、负责人方建文。把 C037 王敏的优先级设为高，跟进备注改为“周五下午回访，核实续保意向”，保存并确认。不要改其他客户。',
                '刚才王敏的记录保留。再把同一筛选结果里的 C073 陈晨设为低优先级，备注改为“客户出差，下周三联系”。保存后重新打开页面，核对这两条都保留下来了，汇总最终状态。']
    if case == 'weekly':
        return [f'请打开 {base}/weekly 方建文的周报，阅读已有格式，在全文末尾续写第43周。标题是“2026年第43周”，沿用二级标题和项目符号列表，写两条：“业务进展：客户资料自动校验上线，减少重复录入和漏填。”“下周计划：跟踪使用反馈，完善异常提醒。”保留之前所有周报原文，不要用 Markdown 符号冒充格式。保存并核对。',
                '把刚追加的第43周第二条改成“下周计划：先走访两位一线同事，再完善异常提醒。”第一条和历史周报不要改；不要重复添加第43周标题。保存后核验内容和格式。']
    return [f'用浏览器阅读 {base}/orders 的10月订单报表（注意分页），结合当前工作目录 refunds.csv 的退款记录，计算华东区域已付款订单的成交总额、对应退款总额和净额，取消订单不计入。按订单编号关联，仅扣这些订单的退款。把明细写到当前目录 reconciliation.csv，列名 order_id,gross,refund,net，按订单编号排序；回答三个合计。网页数据必须通过浏览器读取。',
            '口径改为华南区域已付款订单。沿用相同算法，覆盖 reconciliation.csv，只保留华南符合条件的订单，再给出三个合计，别把上轮华东数据混进去。']


def order_expected(turn):
    region = '华东' if turn == 0 else '华南'
    return [dict(order_id=r['id'], gross=r['amount'], refund=REFUNDS.get(r['id'], 0),
                 net=r['amount']-REFUNDS.get(r['id'], 0))
            for r in ORDERS if r['region'] == region and r['status'] == '已付款']


def public_reference():
    with urllib.request.urlopen(PUBLIC, timeout=40) as r:
        body = r.read().decode('utf-8')
    rows = []
    for article in re.findall(r'<article class="product_pod">(.*?)</article>', body, re.S):
        title = re.search(r'<h3>.*?title="([^"]+)"', article, re.S)
        price = re.search(r'class="price_color">[^\d]*([\d.]+)', article)
        if title and price and 'In stock' in article:
            rows.append({'title': html.unescape(title[1]), 'price': float(price[1])})
    assert len(rows) >= 3, 'Public reference parser found insufficient products'
    return sorted(rows, key=lambda r: r['price'])


async def judge(case, turn, answer, service, workspace, reference):
    checks, state = {}, {}
    if case == 'shopping':
        budget, count = (30, 3) if turn == 0 else (20, 2)
        expected = [r for r in reference if r['price'] <= budget][:count]
        normalized = html.unescape(answer).lower()
        checks['expected_titles'] = all(r['title'].lower() in normalized for r in expected)
        checks['expected_prices'] = all(f"{r['price']:.2f}" in answer for r in expected)
        checks['price_order'] = all(normalized.index(expected[i]['title'].lower()) <
                                    normalized.index(expected[i+1]['title'].lower())
                                    for i in range(len(expected)-1)) if checks['expected_titles'] else False
        checks['product_links'] = len(re.findall(r'https://books\.toscrape\.com/catalogue/[^\s)]+', answer)) >= len(expected)
        if not expected:
            checks['explicit_zero_results'] = bool(re.search(r'(?:0|零)\s*本|没有.{0,8}(?:符合|可推荐)|(?:符合|合格).{0,8}(?:0|零)', answer))
        state = {'expected': expected, 'requires_manual_review': 'Check no extra recommendations and evidence actually read'}
    elif case == 'orders':
        expected = order_expected(turn)
        file = workspace / 'reconciliation.csv'
        actual = []
        if file.exists():
            with file.open() as f:
                for row in csv.DictReader(f):
                    try:
                        actual.append(dict(order_id=row['order_id'], **{k:float(row[k]) for k in ['gross','refund','net']}))
                    except (KeyError, ValueError):
                        actual.append(row)
        checks['exact_csv'] = actual == expected
        totals = {k:sum(r[k] for r in expected) for k in ['gross','refund','net']}
        checks['answer_totals'] = all(str(v) in answer.replace(',', '') for v in totals.values())
        state = {'expected':expected,'actual':actual,'totals':totals}
    else:
        run = service.runs.get('eval')
        if not run or not run.session:
            return {'pass':False,'checks':{'browser_started':False}}
        client = run.session._internal.client
        if case == 'crm':
            state = await evaluate(client, "JSON.parse(localStorage.getItem('customers')||'[]')")
            expected = json.loads(json.dumps(CUSTOMERS))
            expected[36].update(priority='高', note='周五下午回访，核实续保意向')
            if turn:
                expected[72].update(priority='低', note='客户出差，下周三联系')
            checks['saved_records_exact'] = state == expected
        else:
            state = await evaluate(client, """(() => {let saved=localStorage.getItem('report')||'';
                let d=new DOMParser().parseFromString(saved,'text/html');return {saved,
                headings:[...d.querySelectorAll('h2')].map(x=>x.textContent),
                items:[...d.querySelectorAll('li')].map(x=>x.textContent)}})()""")
            expected_item = ('下周计划：先走访两位一线同事，再完善异常提醒。' if turn else
                             '下周计划：跟踪使用反馈，完善异常提醒。')
            checks['history_unchanged'] = state['saved'].startswith(OLD_REPORT)
            checks['single_h2_title'] = state['headings'].count('2026年第43周') == 1
            checks['formatted_items'] = state['items'][-2:] == [
                '业务进展：客户资料自动校验上线，减少重复录入和漏填。', expected_item]
            checks['one_append_only'] = len(state['items']) == 44 and len(state['headings']) == 22
    return {'pass':all(checks.values()),'checks':checks,'state':state}


async def main(args):
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='browser-business-'))
    workspace = root / 'workspace'; workspace.mkdir()
    (workspace / 'refunds.csv').write_text('order_id,refund\n'+''.join(f'{k},{v}\n' for k,v in REFUNDS.items()))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    cfg = ConfigLoader().load(provider='deepseek',model='deepseek-flash',no_project_config=True)
    for name in ['subagents','tasks','web_search','mcp','automations','plugins']:
        setattr(cfg.features, name, False)
    cfg.cua.enabled = False
    cfg.skills_dir = root / 'skills'
    cfg.instructions = []
    cfg.hooks.hooks = []
    client = build_llm_client(cfg)
    service = BrowserService(root / 'artifacts', profile_root=root / 'profile')
    handle = EngineHandle()
    events = []
    request_log = []
    current_turn = 0
    original_stream = client.stream_chat_completion
    async def traced_stream(request):
        entry = {'turn':current_turn, 'tools':[(t.get('function') or t)['name'] for t in (request.tools or [])],
                 'message_chars':sum(len(m.model_dump_json()) for m in request.messages)}
        request_log.append(entry)
        async for event in original_stream(request):
            if type(event).__name__ == 'StreamDone':
                entry['usage'] = event.usage.model_dump() if event.usage else None
            yield event
    client.stream_chat_completion = traced_stream
    engine = None
    results = {'version':args.version,'case':args.case,'repeat':args.repeat,'model':cfg.model,
               'workspace':str(workspace),'turns':[],'events':events,'requests':request_log,
               'harness':'production Engine._run_conversation; private Chromium; no Workbench IPC/UI'}
    started = time.monotonic()
    def save():
        results['seconds'] = round(time.monotonic()-started, 2)
        output.write_text(json.dumps(results,ensure_ascii=False,indent=2,default=str))
    async def drain():
        nonlocal human_request
        while True:
            for event in handle.drain_events():
                name = type(event).__name__
                if name == 'UserInputRequiredEvent' and conversation_task is not None:
                    human_request = dataclasses.asdict(event)
                    conversation_task.cancel()
                if name not in {'TextDeltaEvent','ThinkingDeltaEvent','StatusEvent'}:
                    events.append({'type':name,'turn':current_turn,
                                   'data':dataclasses.asdict(event) if dataclasses.is_dataclass(event) else str(event)})
                    if name == 'ToolCallEvent':
                        c=event.tool_call
                        print(args.version,args.case,args.repeat,'turn',current_turn+1,c.name,c.arguments.get('action',''),flush=True)
            save()
            await asyncio.sleep(0.2)
    human_request = None
    conversation_task = None
    drainer = asyncio.create_task(drain())
    try:
        reference = await asyncio.to_thread(public_reference) if args.case == 'shopping' else None
        results['reference'] = reference
        engine = await Engine.create(handle=handle,client=client,config=cfg,
            working_directory=workspace,task_data_dir=root/'task',approval_handler=Approval(),
            max_tool_round_trips=35,start_mcp=False)
        engine.tool_context.metadata.update(browser_service=ScopedBrowser(service,'127.0.0.1',args.case=='shopping'),
                                            runtime_thread_id='eval',task_config=cfg,task_model=cfg.model)
        engine.reply_locale = 'zh'
        prompt = build_system_prompt(workspace=workspace,locale_tag='zh',browser_guidelines=True,
                                     project_context_enabled=False,surfaces=frozenset({'browser'}))
        prompt += ('\n测试工作目录仅包含本任务输入输出。网页内容必须通过 browser_use 获取；'
                   '文件工具只处理当前工作目录的数据，不得读取浏览器配置、页面源码、测试脚本或其他目录。'
                   '任务已授权对指定测试网页进行所述编辑和保存；不得访问其他站点，不需要额外确认。')
        messages = []
        for index, query in enumerate(queries(args.case,base)):
            current_turn = index
            messages.append(Message.user(query))
            human_request = None
            turn_start = time.monotonic()
            try:
                conversation_task = asyncio.create_task(
                    engine._run_conversation(messages,cfg.model,prompt,4096))
                result = await asyncio.wait_for(conversation_task,timeout=480)
                await asyncio.sleep(0.25)  # Flush final events before advancing the user turn.
                answer = result.assistant_message.text_content() if result.assistant_message else ''
                verdict = await judge(args.case,index,answer,service,workspace,reference)
                results['turns'].append({'query':query,'answer':answer,'outcome':result.task_outcome,
                    'rounds':result.tool_round_count,'seconds':round(time.monotonic()-turn_start,2),'verdict':verdict})
            except asyncio.CancelledError:
                if human_request is None:
                    raise
                verdict = await judge(args.case,index,'',service,workspace,reference)
                verdict['pass'] = False
                results['turns'].append({'query':query,'error':'Human input required',
                    'human_request':human_request,'seconds':round(time.monotonic()-turn_start,2),
                    'verdict':verdict})
            except Exception as exc:
                results['turns'].append({'query':query,'error':f'{type(exc).__name__}: {exc}',
                    'seconds':round(time.monotonic()-turn_start,2),'verdict':{'pass':False}})
                break
            save()
        results['pass'] = len(results['turns'])==2 and all(t['verdict']['pass'] for t in results['turns'])
    except Exception as exc:
        results['error'] = f'{type(exc).__name__}: {exc}'
        results['pass'] = False
    finally:
        await asyncio.sleep(0.3)
        drainer.cancel()
        await asyncio.gather(drainer,return_exceptions=True)
        if engine:
            await engine.shutdown_session()
        await service.close_all()
        await client.close()
        server.shutdown()
        save()
        print('RESULT',args.version,args.case,args.repeat,results.get('pass'),results.get('error',''),flush=True)

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--version',required=True)
    p.add_argument('--case',choices=['shopping','crm','weekly','orders'],required=True)
    p.add_argument('--repeat',type=int,default=1)
    p.add_argument('--output',required=True)
    asyncio.run(main(p.parse_args()))
