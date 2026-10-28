"""Self-contained evidence report, generated from immutable runs."""
import gzip
import html
import json
import statistics
from pathlib import Path
from summarize import rows

ROOT=Path(__file__).resolve().parent
def esc(x):return html.escape(str(x))
labels={'shopping':'商品筛选与预算变更（中等）','crm':'客户维护与持久化核对（中等）',
        'weekly':'长周报续写、格式与二次修改（困难）','orders':'分页订单与本地退款表核对（困难）'}
metrics=rows();complete=[r for r in metrics if r['complete']]
manifest=json.loads((ROOT/'manifest.json').read_text())
parts=['''<!doctype html><meta charset="utf-8"><title>浏览器业务验收 · 2026-10-28</title><style>
body{font:16px/1.65 system-ui,-apple-system,sans-serif;color:#24313d;max-width:1200px;margin:36px auto;padding:0 24px;background:#f7f8fa}h1,h2{line-height:1.25}section,details{background:white;border:1px solid #dde2e7;border-radius:10px;padding:18px;margin:18px 0}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #e2e6eb;padding:10px;text-align:left;vertical-align:top}th{background:#eff3f6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 system-ui;background:#f4f6f8;padding:14px;border-radius:6px}a{color:#145eb0}.pass{color:#176e44}.fail{color:#b03527}.muted{color:#647383}summary{cursor:pointer;font-weight:600}code{overflow-wrap:anywhere}</style>''',
'<h1>浏览器业务验收</h1><p>2026-10-28 · deepseek-v4-1-flash · 优化前后各 3 次独立重复 · 每次 2 轮用户需求</p>',
'<section><h2>方法与边界</h2><p>以真实需求和独立结果判定验收，而非仅验证修复代码。每次创建新浏览器配置和工作目录，两轮对话共享同一会话。使用项目实际 Engine 工具循环、工具目录、任务交付与上下文逻辑；未覆盖 Workbench 服务/UI 集成。</p>',
'<p>商品场景使用公开 books.toscrape.com 测试商店，仅浏览；其余使用本机可重置的业务模拟页面，通过真实 Chromium 点击、输入、滚动和保存。它们不等同于真实语雀、CRM 服务端或登录流程。</p>',
'<p>每轮配置 max_tool_round_trips=35、480 秒（引擎可追加收尾轮）；先后版本交替顺序。产品源码冻结，正式批次不边测边修。试运行不纳入成绩。三次重复只用于发现稳定性问题，不足以证明普遍提升或统计显著性。</p>',
'<p>浏览器及相关引擎回归初次 588 通过、1 个测试替身失败；精确修正替身匹配后，该用例单独通过。未再次运行整套回归。</p></section>',
'<section><h2>需求与判定</h2><table><tr><th>场景</th><th>第一轮</th><th>后续修改</th><th>独立判定</th></tr>',
'<tr><td>商品 · 中等</td><td>Travel 分类有货、£30 内最便宜三本，不足则列实际数量</td><td>预算降到 £20，重新确认最多两本</td><td>对照独立读取的价格、完整书名、数量、顺序和链接；人工检查超预算推荐及证据</td></tr>',
'<tr><td>客户 · 中等</td><td>区域与负责人筛选，修改 C037 优先级、备注并保存</td><td>保留 C037，修改 C073，重新打开核对</td><td>已保存的 80 条记录与期望逐字段对比，确保其他记录不变</td></tr>',
'<tr><td>周报 · 困难</td><td>21 周历史文档后追加第43周二级标题和两条列表</td><td>只修改本周第二条，避免重复追加</td><td>检查已保存 HTML 的历史前缀、h2/li 结构、内容及数量</td></tr>',
'<tr><td>对账 · 困难</td><td>读取两页订单，与本地退款表关联，筛华东已付款并导出 CSV</td><td>改华南，覆盖文件，避免混入上一轮数据</td><td>逐行核对 CSV 编号/金额/退款/净额及排序，核对回答合计</td></tr></table></section>',
f'<section><h2>结果（已完成 {len(complete)}/24）</h2><p>通过表示两轮均通过自动业务断言；人工复核中的表达、证据或合规问题另列，不由模型自报完成决定。</p><table><tr><th>场景</th><th>版本</th><th>通过/完成</th><th>工具调用中位数</th><th>失败调用合计</th><th>耗时中位数</th></tr>']
for case,label in labels.items():
    for version in ['before','after']:
        group=[r for r in complete if r['case']==case and r['version']==version]
        if group:
            parts.append(f'<tr><td>{esc(label)}</td><td>{"优化前" if version=="before" else "优化后"}</td><td>{sum(r["passed"] for r in group)}/{len(group)}</td><td>{statistics.median(r["tool_calls"] for r in group):g}</td><td>{sum(r["failed_calls"] for r in group)}</td><td>{statistics.median(r["seconds"] for r in group):.1f}s</td></tr>')
parts.append('</table><p class="muted">耗时统计包括失败任务，不能将未完成任务更快退出解释为效率提高。模型请求、工具调用与用户轮次是不同指标。</p></section>')
review=ROOT/'review.json'
if review.exists():
    parts.append('<section><h2>人工证据复核</h2><pre>'+esc(json.dumps(json.loads(review.read_text()),ensure_ascii=False,indent=2))+'</pre></section>')
for row in metrics:
    path=ROOT/row['file']
    data=json.loads(gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes())
    status='通过' if row['passed'] else '未通过' if row['complete'] else '中断，未计入成绩'
    parts.append(f'<details><summary>{esc(labels[row["case"]])} · {row["version"]} · 第 {row["repeat"]} 次：{status}</summary><p>模型请求 {row["requests"]} · 工具调用 {row["tool_calls"]} · 失败调用 {row["failed_calls"]} · {row["seconds"]} 秒 · <a href="{row["file"]}">完整原始日志</a></p>')
    for i,turn in enumerate(data.get('turns',[]),1):
        parts.extend([f'<h3>第 {i} 轮需求</h3><pre>{esc(turn["query"])}</pre>',
            '<p>判定：'+esc(turn['verdict'].get('checks',turn.get('error')))+ '</p>',
            '<h3>模型回答</h3><pre>'+esc(turn.get('answer',turn.get('error','')))+ '</pre>'])
        if turn.get('human_request'):
            parts.append('<h3>请求人工接手</h3><pre>'+esc(json.dumps(turn['human_request'],ensure_ascii=False,indent=2))+'</pre>')
    if row['errors']:
        parts.append('<h3>失败工具调用</h3><pre>'+esc(json.dumps(row['errors'],ensure_ascii=False,indent=2))+'</pre>')
    parts.append('</details>')
parts.append('<section><h2>复现记录</h2><p><a href="manifest.json">版本与参数</a> · <a href="metrics.json">结构化指标</a> · <a href="run_case.py">单任务程序</a> · <a href="run_matrix.py">批次程序</a> · <a href="fixtures.py">业务页面</a> · <a href="implementation.patch.gz">优化补丁</a></p><pre>'+esc(json.dumps(manifest,ensure_ascii=False,indent=2))+'</pre></section>')
(ROOT/'report.html').write_text('\n'.join(parts))
(ROOT/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
print('report:',len(complete),'completed')
