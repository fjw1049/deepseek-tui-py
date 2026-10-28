"""Resettable business UI fixtures; evaluator reads persisted state independently."""
import json

STYLE = '''<meta charset="utf-8"><style>body{font:16px system-ui;margin:24px;max-width:1050px}button,input,select,textarea{font:inherit;margin:6px;padding:6px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:10px}#list{height:390px;overflow:auto;border:1px solid #999}#editor{border:1px solid #888;padding:20px;min-height:350px}header{position:sticky;top:0;background:white;padding:8px;z-index:2}.notice{color:#666}</style>'''
CUSTOMERS = [dict(id=f'C{i:03}', name=('王敏' if i == 37 else '陈晨' if i == 73 else f'客户{i:03}'), region='华东' if i % 2 else '华南', owner='方建文' if i % 3 else '李芳', priority='普通', note='待联系') for i in range(1, 81)]
OLD_REPORT = ''.join(f'<h2>2026年第{i}周</h2><ul><li>业务进展：完成客户资料核对{i}批，降低资料遗漏。</li><li>下周计划：继续跟进待处理事项。</li></ul>' for i in range(22, 43))
ORDERS = [dict(id=f'O{i:03}',region='华东' if i%3 else '华南',status='取消' if i%5==0 else '已付款',amount=100+i*10) for i in range(1,21)]
REFUNDS = {f'O{i:03}': (20+i) for i in [2,4,5,7,9,11,13,16,18,20]}


def page(path):
    if path == '/crm':
        return STYLE + '''<title>客户工作台</title><h1>客户跟进工作台</h1>
<label>区域<select id="region"><option>全部</option><option>华东</option><option>华南</option></select></label>
<label>负责人<select id="owner"><option>全部</option><option>方建文</option><option>李芳</option></select></label>
<button onclick="render()">筛选</button><div id="count"></div><div id="list"></div>
<section id="detail" hidden><h2 id="customer"></h2><label>优先级<select id="priority"><option>普通</option><option>高</option><option>低</option></select></label><label>跟进备注<textarea id="note"></textarea></label><button onclick="save()">保存客户</button></section><p id="status" role="status"></p>
<script>let data=JSON.parse(localStorage.getItem('customers')||''' + json.dumps(json.dumps(CUSTOMERS,ensure_ascii=False)) + ''');let selected;
function render(){let rows=data.filter(r=>(region.value==='全部'||r.region===region.value)&&(owner.value==='全部'||r.owner===owner.value));count.textContent='共 '+rows.length+' 条';list.innerHTML='<table><tr><th>客户编号</th><th>姓名</th><th>区域</th><th>负责人</th><th>优先级</th><th>备注</th><th>操作</th></tr>'+rows.map(r=>`<tr><td>${r.id}</td><td>${r.name}</td><td>${r.region}</td><td>${r.owner}</td><td>${r.priority}</td><td>${r.note}</td><td><button onclick="edit('${r.id}')" aria-label="编辑 ${r.id} ${r.name}">编辑</button></td></tr>`).join('')+'</table>'}
function edit(id){selected=data.find(r=>r.id===id);detail.hidden=false;customer.textContent=selected.id+' '+selected.name;priority.value=selected.priority;note.value=selected.note;detail.scrollIntoView({block:'nearest'})}
function save(){selected.priority=priority.value;selected.note=note.value;localStorage.setItem('customers',JSON.stringify(data));document.getElementById('status').textContent='已保存 '+selected.id+' '+selected.priority+' '+selected.note;render()}
render();</script>'''
    if path == '/weekly':
        return STYLE + '''<title>团队周报</title><header><h1>方建文的周报</h1><button onmousedown="event.preventDefault()" onclick="document.execCommand('formatBlock',false,'h2')">二级标题</button><button onmousedown="event.preventDefault()" onclick="document.execCommand('insertUnorderedList')">项目符号</button><button onclick="save()">保存周报</button><button onclick="preview.hidden=!preview.hidden;preview.innerHTML=localStorage.getItem('report')||initial">查看已保存版本</button><span id="status">尚未修改</span></header>
<p class="notice">正文可编辑。标题和列表请用工具栏设置；保存后可查看已保存版本核对。</p><article id="editor" role="textbox" aria-label="周报正文" contenteditable="true"></article><section id="preview" hidden></section><script>const initial=''' + json.dumps(OLD_REPORT,ensure_ascii=False) + ''';editor.innerHTML=localStorage.getItem('report')||initial;function save(){localStorage.setItem('report',editor.innerHTML);document.getElementById('status').textContent='已保存 '+new Date().toLocaleTimeString()}</script>'''
    if path == '/orders':
        return STYLE + '''<title>订单报表</title><h1>2026年10月订单核对</h1><p>金额单位：元；已付款为成交金额，取消订单不计入成交。退款另见本地退款表，按订单编号匹配，不要把别的区域退款扣进来。</p><table><thead><tr><th>订单编号</th><th>区域</th><th>状态</th><th>成交金额</th></tr></thead><tbody id="rows"></tbody></table><button onclick="n=0;render()">上一页</button><button onclick="n=1;render()">下一页</button><span id="pageNo"></span><script>const orders=''' + json.dumps(ORDERS,ensure_ascii=False) + ''';let n=0;function render(){rows.innerHTML=orders.slice(n*10,n*10+10).map(r=>`<tr><td>${r.id}</td><td>${r.region}</td><td>${r.status}</td><td>${r.amount}</td></tr>`).join('');pageNo.textContent='第 '+(n+1)+' / 2 页'}render()</script>'''
    return STYLE + '<h1>业务测试工作台</h1><a href="/crm">客户管理</a><a href="/weekly">团队周报</a><a href="/orders">订单报表</a>'
