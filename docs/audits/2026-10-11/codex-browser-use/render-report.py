"""Render the local report without external fonts, scripts, or network requests."""
from pathlib import Path
from html import escape, unescape
import json
import re
from markdown_it import MarkdownIt

root = Path(__file__).resolve().parent
text = (root / "REPORT.md").read_text()
flow = """<div class="flow" aria-label="浏览器执行链">
<div>任务与模型决策</div><span>↓</span><div>持久运行时 · 浏览器与标签绑定</div>
<span>↓</span><div>结构化观察 · AX / DOM / 截图</div><span>↓</span>
<div>权限与所有权检查 · 语义定位 · 有限等待</div><span>↓</span>
<div>原生 RPC → IAB / Chrome 后端</div><span>↓</span>
<div>页面变化 → 验证效果 → 再观察 / 恢复 / 交付</div>
<small>Chrome 扩展内部、云端决策与 AX WASM 内部仍未覆盖。</small></div>"""
text = re.sub(r"```mermaid\n.*?```", flow, text, flags=re.S)
body = MarkdownIt("commonmark", {"html": True}).enable("table").render(text)
body = re.sub(r"^<h1>.*?</h1>\n", "", body, count=1)
nav = []
def heading(match):
    ident = f"section-{len(nav) + 1}"
    content = match.group(1)
    label = unescape(re.sub(r"<[^>]*>", "", content))
    nav.append(f'<a href="#{ident}">{escape(label)}</a>')
    return f'<h2 id="{ident}">{content}</h2>'
body = re.sub(r"<h2>(.*?)</h2>", heading, body)
checks = json.loads((root / "replica/results/report.json").read_text())["checks"]
count = sum(c["passed"] for c in checks)
css = """
:root{color-scheme:light;--ink:#18332f;--muted:#60706b;--line:#dce4dd;--accent:#246854}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;background:#f5f6f1;color:var(--ink);font:16px/1.85 -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif}
.hero{background:#183d33;color:#fff;padding:48px max(28px,calc((100vw - 1180px)/2));border-bottom:5px solid #bdce9e}
.eyebrow{font-size:12px;letter-spacing:2px;color:#c4d4b3}.hero h1{font-size:clamp(27px,4vw,42px);line-height:1.3;margin:10px 0 14px;font-weight:650}
.hero p{max-width:760px;color:#dce9df;margin:0}.badges{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}.badge{padding:8px 14px;border:1px solid #6c9080;border-radius:8px;font-size:14px}
.layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:42px;max-width:1240px;margin:auto;padding:36px 30px}
aside{position:sticky;top:22px;align-self:start;font-size:13px;line-height:1.7}aside strong{display:block;margin:0 0 10px}aside a{display:block;padding:7px 0;color:#46665a;text-decoration:none}
main{min-width:0;background:#fff;padding:28px 38px;border:1px solid var(--line);border-radius:12px;box-shadow:0 8px 28px #18332f06}
h2{font-size:24px;margin:40px 0 16px;padding-top:14px;border-top:1px solid var(--line);line-height:1.45}h2:first-of-type{margin-top:0;border:0;padding:0}
h3{font-size:19px;margin:30px 0 12px}p{margin:14px 0}a{color:var(--accent);text-underline-offset:3px}strong{font-weight:650}
code{font:13px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace;background:#eef2ed;border-radius:4px;padding:2px 5px;overflow-wrap:anywhere}
pre{background:#edf2ec;padding:18px;overflow:auto;border-radius:8px;line-height:1.55}pre code{padding:0;overflow-wrap:normal}
table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.75;margin:20px 0;table-layout:fixed}th,td{border:1px solid var(--line);padding:12px;vertical-align:top;overflow-wrap:anywhere}th{background:#edf3eb;text-align:left}tr:nth-child(even) td{background:#fafbf8}
.flow{margin:24px auto;padding:22px;background:#f0f5ec;border:1px solid #d2dfc8;border-radius:10px;text-align:center;max-width:650px}.flow div{background:#fff;border:1px solid #c6d5c1;border-radius:7px;padding:9px}.flow span{display:block;font-size:21px;color:#7b9674;line-height:1.6}.flow small{display:block;color:var(--muted);margin-top:16px;font-size:12px}
.evidence{padding:18px 0;color:var(--muted);font-size:13px}.evidence img{width:100%;border:1px solid var(--line);border-radius:8px;margin-top:12px}footer{max-width:1240px;margin:auto;padding:0 30px 36px;color:var(--muted);font-size:12px}
@media(max-width:900px){.layout{grid-template-columns:1fr;padding:20px;gap:20px}aside{position:static;display:flex;flex-wrap:wrap;gap:6px 18px}aside strong{width:100%}main{padding:20px}table{font-size:12px}th,td{padding:8px}}
@media print{.hero{background:#fff;color:#000;padding:10px;border:0}.hero p,.eyebrow{color:#333}.badges,aside,footer{display:none}.layout{display:block;padding:0}main{border:0;box-shadow:none;padding:0}a{color:#000}h2,h3{break-after:avoid}pre,.flow,tr{break-inside:avoid}}
"""
page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Codex Browser Use 逆向审核与复现</title><style>{css}</style></head><body>
<header class="hero"><div class="eyebrow">LOCAL EVIDENCE · 2026.10.11</div><h1>Codex Browser Use<br>逆向审核与可运行复现</h1><p>本地执行链已核验。先修观察裁剪与滚动派发，再完善可信观察和效果验证。真实异常与未知范围逐项保留。</p><div class="badges"><div class="badge">REA 已安装 · 170 个 MCP 工具</div><div class="badge">独立演示 · {count}/{len(checks)} 通过</div><div class="badge">Codex IAB · 8 通过 / 2 失败</div></div></header>
<div class="layout"><aside><strong>阅读导航</strong>{''.join(nav)}<a href="replica/README.md">运行独立演示 ↗</a><a href="REPORT.md">Markdown 原稿 ↗</a></aside><main>{body}<div class="evidence"><strong>独立演示 · 验证后的真实页面</strong><br>此截图来自独立 Chrome 执行器，Codex IAB 的截图另见证据目录。<img src="replica/results/verified.png" alt="独立演示完成表单、iframe、Shadow 与遮挡验证后的页面"></div></main></div><footer>目标版本 26.1007.21159 / build 20052 · 静态实现、隔离验证与真实浏览器结果分别记录 · 完整来源摘要随报告交付</footer></body></html>"""
(root / "REPORT.html").write_text(page)
print("Rendered REPORT.html with local assets only.")
