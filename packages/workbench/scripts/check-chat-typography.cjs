const { app, BrowserWindow } = require('electron')
const fs = require('node:fs'), path = require('node:path'), os = require('node:os')
const assert = require('node:assert/strict'), postcss = require('postcss'), tailwind = require('tailwindcss')
const base = path.resolve(__dirname, '..'), phase = process.argv[2] || 'after'
const output = path.resolve(base, '../../docs/chat-typography-audit-2026-09-14')
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'chat-typography-'))
const text = '中文提问 Query / 项目 Project 0123'
const md = html => `<div class="ds-markdown ds-markdown--answer">${html}</div>`
const samples = [
 ['user', `<div class="ds-user-message-bubble">${text}</div>`],
 ['edit', `<div class="ds-user-message-bubble"><textarea class="ds-user-message-edit-textarea text-[15px] font-medium">${text}</textarea></div>`],
 ['composer', `<div class="ds-composer-shell ds-chat-composer"><textarea class="ds-composer-input">${text}</textarea></div>`],
 ['answer', md(`<p>${text}</p>`)],
 ...['h1','h2','h3','h4','strong'].map(tag=>[tag,md(`<${tag}>${text}</${tag}>`)]),
 ['inline-code',md('<p>代码 <code class="ds-code-inline">query()</code></p>')],
 ['code',md('<div class="ds-code-block-body"><div class="ds-code-block-html"><pre><code>const query = "中文"</code></pre></div></div>')],
 ['table',md(`<table><tbody><tr><td>${text}</td></tr></tbody></table>`)],
 ['reasoning',`<div class="ds-process-reasoning"><div class="ds-markdown"><p>${text}</p></div></div>`],
 ['tool',`<div class="ds-tool-header-row"><span class="ds-tool-header-row__title ds-tool-header-row__main">${text}</span></div>`],
 ['meta',`<div class="ds-model-meta-tag"><span class="text-[12px]">${text}</span></div>`],
 ['todo',`<div class="ds-inline-todo"><span class="text-[13px]">${text}</span></div>`]
]
async function run() {
 const config=(await import(path.join(base,'tailwind.config.js'))).default
 config.content=config.content.map(p=>path.resolve(base,p))
 const source=path.join(base,'src/renderer/src/index.css')
 const css=(await postcss([tailwind(config)]).process(fs.readFileSync(source,'utf8'),{from:source})).css
 await app.whenReady()
 const win=new BrowserWindow({show:false,width:1400,height:1400})
 const file=path.join(scratch,'audit.html')
 fs.writeFileSync(file,`<html lang="zh-CN"><head><style>${css}</style></head><body><main id="audit"></main></body></html>`)
 await win.loadFile(file)
 const rows=await win.webContents.executeJavaScript(`(()=>{
 const samples=${JSON.stringify(samples)}, host=document.querySelector('#audit'),rows=[];
 for(const theme of ['light','dark']) for(const size of [13,15,18]) for(const width of [360,760]) for(const mode of ['main','ide']) {
 document.documentElement.dataset.theme=theme;document.documentElement.style.setProperty('--ds-chat-font-size',size+'px');
 host.className=mode==='ide'?'ds-ide-chat-rail':'';host.style.width=width+'px';
 host.innerHTML=samples.map(([name,html])=>'<section data-name="'+name+'">'+html+'</section>').join('');
 for(const [name] of samples) {const node=[...host.querySelector('[data-name="'+name+'"]').querySelectorAll('*')].at(-1),s=getComputedStyle(node);
 rows.push({theme,size,width,mode,name,font:s.fontSize,weight:s.fontWeight,line:s.lineHeight,family:s.fontFamily});}
 }return rows;})()`)
 fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(output,phase+'.json'),JSON.stringify(rows,null,2))
 if(phase==='after') for(const r of rows){
 const n=r.mode==='ide'?13:r.size, label=JSON.stringify(r)
 if(['user','edit','composer','answer'].includes(r.name)) assert.equal(parseFloat(r.font),n,label)
 if(r.name==='strong') assert.equal(r.weight,'600',label)
 if(r.name==='edit') assert.equal(r.weight,'400',label)
 if(r.name==='code') {assert.equal(r.font,'13px',label);assert.equal(r.line,'19.5px',label)}
 const ratio={h1:1.45,h2:1.35,h3:1.25,h4:1.1}[r.name]
 if(ratio) assert.ok(Math.abs(parseFloat(r.font)-n*ratio)<0.01,label)
 if(r.mode==='ide'&&['code','inline-code','table','reasoning','tool','meta','todo'].includes(r.name)) assert.equal(r.font,'13px',label)
 }
 const visual=['main','ide'].map(mode=>`<div class="${mode==='ide'?'ds-ide-chat-rail':''}"><div style="font:600 16px sans-serif">${mode==='ide'?'编辑视图 · 13px':'主会话 · 设置 15px'}</div>${samples.map(([name,html])=>`<section style="margin:8px 0"><label style="font:11px sans-serif;color:#888">${name}</label>${html}</section>`).join('')}</div>`).join('')
 await win.webContents.executeJavaScript(`document.documentElement.dataset.theme='light';document.documentElement.style.setProperty('--ds-chat-font-size','15px');const host=document.querySelector('#audit');host.className='';document.body.style.zoom='.7';host.style.cssText='display:grid;grid-template-columns:1fr 1fr;gap:32px;padding:24px;background:white';host.innerHTML=${JSON.stringify(visual)};undefined`)
 await win.webContents.executeJavaScript('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
 fs.writeFileSync(path.join(output,phase+'.png'),(await win.webContents.capturePage()).toPNG())
 console.log(phase+': '+rows.length+' computed typography samples checked');win.destroy()
}
run().then(()=>app.quit()).catch(e=>{console.error(e);app.exit(1)}).finally(()=>fs.rmSync(scratch,{recursive:true,force:true}))
