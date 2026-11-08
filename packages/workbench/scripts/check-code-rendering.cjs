// Run npm run build before this integration/performance check.
const {app,BrowserWindow}=require('electron')
const assert=require('node:assert/strict')
const fs=require('fs'),path=require('path'),{pathToFileURL}=require('url')
const base=path.resolve(__dirname, '..')
const esbuild=require(base+'/node_modules/esbuild')
const output=fs.mkdtempSync(path.join(require('os').tmpdir(), 'workbench-render-check-'))
fs.mkdirSync(output,{recursive:true})
app.whenReady().then(async()=>{
const assets=base+'/out/renderer/assets'
const names=fs.readdirSync(assets)
await esbuild.build({
stdin:{contents:`
import React from 'react'; import {createRoot} from 'react-dom/client'; import {flushSync} from 'react-dom';
import {DiffView} from './src/renderer/src/components/DiffView';
window.renderDiff=(props)=>flushSync(()=>root.render(React.createElement(DiffView,props)));
const root=createRoot(document.getElementById('root'));
`,resolveDir:base,loader:'tsx'},define:{'process.env.NODE_ENV':'"production"','import.meta.hot':'undefined'},bundle:true,jsx:'automatic',format:'iife',outfile:output+'/bundle.js',
alias:{'@shared':base+'/src/shared'},plugins:[{name:'workers',setup(build){
build.onResolve({filter:/^virtual:material-icons$/},()=>({path:'icons',namespace:'icons'}))
build.onLoad({filter:/.*/,namespace:'icons'},()=>({contents:'export const materialIconUrlByName = {}'}))
build.onResolve({filter:/\?worker$/},args=>({path:args.path,namespace:'worker-url'}))
build.onLoad({filter:/.*/,namespace:'worker-url'},args=>{
const name=path.basename(args.path).replace('?worker','').replace('.ts','')
const target=names.find(n=>n.startsWith(name+'-')&&n.endsWith('.js'))
if(!target) throw Error('Missing worker '+name)
return {contents:`export default class extends Worker { constructor(){super(${JSON.stringify(pathToFileURL(assets+'/'+target).href)},{type:'module'})} }`}
})
}}]})
const css=names.filter(n=>n.endsWith('.css')).map(n=>'<link rel="stylesheet" href="'+pathToFileURL(assets+'/'+n).href+'">').join('')
fs.writeFileSync(output+'/index.html','<html data-theme="light"><head>'+fs.readFileSync(base+'/src/renderer/index.html','utf8').match(/<meta\s+http-equiv="Content-Security-Policy"[\s\S]*?\/>/)[0]+css+'</head><body><div id="root" style="height:700px;width:900px"></div><script src="bundle.js"></script></body></html>')
const win=new BrowserWindow({show:false,width:1000,height:800,webPreferences:{backgroundThrottling:false}})
win.webContents.on('console-message',(_e,level,message)=>{if(level>=2)console.log('browser:',message)})
await win.loadFile(output+'/index.html')
await win.webContents.executeJavaScript('window.semanticUrl = '+JSON.stringify(pathToFileURL(assets+'/'+names.find(n=>n.startsWith('semantic-tokens.worker-')&&n.endsWith('.js'))).href))

const result=await win.webContents.executeJavaScript(`(async()=>{
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const patch=['@@ -1,900 +1,900 @@',...Array.from({length:900},(_,i)=>'+const item'+i+' = compute("中文", '+i+'); // '+'long content '.repeat(8)), '@@ -901 +901 @@','-last','+end'].join('\\n');
await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
let maxGap=0,last=performance.now(),frames=0,running=true;
function tick(now){maxGap=Math.max(maxGap,now-last);last=now;frames++;if(running)requestAnimationFrame(tick)}requestAnimationFrame(tick);
window.renderDiff({patch,filePath:'sample.ts',diffStyle:'split',chrome:'flush',maxHeight:9000});
for(let i=0;i<200;i++){if(document.querySelector('table')?.style.visibility!=='hidden')break;await wait(50)}
const viewport=document.querySelector('.ds-change-inspector__code');
const out={coloredTokens:document.querySelectorAll('.ds-syntax-line span[style]').length,ready:document.querySelector('table')?.style.visibility,rows:document.querySelectorAll('tbody tr').length,scrollHeight:viewport.scrollHeight,frames,maxGap};
viewport.scrollTop=15000;await wait(150);out.rowsAfterScroll=document.querySelectorAll('tbody tr').length;out.textAfterScroll=document.querySelector('tbody')?.textContent.slice(0,100);
document.querySelector('.ds-diff-navigation button:last-child')?.click();await wait(150);
out.afterJump=viewport.scrollTop;out.endVisible=document.querySelector('tbody')?.textContent.includes('end');
maxGap=0;last=performance.now();
for(let i=0;i<90;i++){viewport.scrollTop=(i*170)%18000; await new Promise(requestAnimationFrame)}
out.scrollMaxGap=maxGap;out.scrollRows=document.querySelectorAll('tbody tr').length;
document.querySelector('.ds-diff-navigation button:last-child')?.click();await wait(150);
out.endVisibleAfterScroll=document.querySelector('tbody')?.textContent.includes('end');

document.querySelector('.ds-diff-view__header button[aria-pressed]')?.click();await wait(100);
out.noWrap=document.querySelector('[data-wrap]')===null;
viewport.scrollLeft=100;await wait(100);out.horizontal=viewport.scrollLeft;
document.querySelector('.ds-diff-view__header button[aria-pressed]')?.click();await wait(100);
document.getElementById('root').style.width='500px';await wait(150);
out.resizedRows=document.querySelectorAll('tbody tr').length;
document.querySelector('.ds-diff-navigation button:last-child')?.click();await wait(200);
out.resizedEnd=document.querySelector('tbody')?.textContent.includes('end');
maxGap=0;last=performance.now();const worker=new Worker(window.semanticUrl,{type:'module'});
const source=Array(350).fill('const value = object.member + '.repeat(134).slice(0,4000)).join('\\n');
const began=performance.now();
out.semanticTokens=await new Promise((resolve,reject)=>{worker.onmessage=e=>resolve(e.data.length/5);worker.onerror=reject;worker.postMessage({source,language:'typescript'})});
out.semanticElapsed=performance.now()-began;out.semanticFrameGap=maxGap;worker.terminate();
running=false;return out;
})()`)
assert.equal(result.ready, '')
assert(result.coloredTokens > 0, 'Expected actual syntax colors, not a plain-text fallback')
assert(result.rows < 100 && result.rowsAfterScroll < 100 && result.resizedRows < 100)
assert(result.endVisible && result.endVisibleAfterScroll && result.resizedEnd)
assert(result.noWrap && result.horizontal > 0)
assert(result.semanticTokens > 0)
console.log(JSON.stringify(result,null,2))
if (process.env.RENDER_AUDIT_OUTPUT) {
fs.mkdirSync(process.env.RENDER_AUDIT_OUTPUT,{recursive:true})
await win.webContents.capturePage().then(img=>fs.writeFileSync(path.join(process.env.RENDER_AUDIT_OUTPUT,'diff.png'),img.toPNG()))
}
win.destroy();app.quit()
}).catch(e=>{console.error(e);app.exit(1)}).finally(()=>fs.rmSync(output,{recursive:true,force:true}))
