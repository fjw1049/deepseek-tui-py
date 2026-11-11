// Real Electron DOM -> IPC -> localhost FastAPI -> persisted delivery journal.
const { app, BrowserWindow, ipcMain } = require('electron')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { pathToFileURL } = require('node:url')
const base = path.resolve(__dirname, '..')
const repo = path.resolve(base, '../..')
const output = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'delivery-electron-audit-'))
app.setPath('userData', path.join(output, 'electron-profile'))
let server
let win

app.whenReady().then(async () => {
  server = spawn(path.join(repo, '.venv/bin/python'), [path.join(repo, 'scripts/audit-delivery-server.py'), output], {
    env: { ...process.env, PYTHONPATH: path.join(repo, 'src'), DEEPSEEK_HOME: path.join(output, 'home') },
    stdio: ['ignore', 'pipe', 'pipe']
  })
  const port = await new Promise((resolve, reject) => {
    let text = ''
    const timer = setTimeout(() => reject(Error('runtime startup timeout')), 10000)
    server.once('error', reject)
    server.stdout.on('data', chunk => {
      text += chunk
      if (text.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(text.split('\n')[0]).port) }
    })
    server.stderr.on('data', chunk => process.stderr.write(chunk))
  })
  const api = `http://127.0.0.1:${port}`
  ipcMain.handle('audit-runtime', async (_event, route, method, body) => {
    const response = await fetch(api + route, { method, body, headers: { 'Content-Type': 'application/json' } })
    return { ok: response.ok, status: response.status, body: await response.text() }
  })
  fs.writeFileSync(path.join(output, 'preload.cjs'), `const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('dsGui',{runtimeRequest:(...args)=>ipcRenderer.invoke('audit-runtime',...args)});`)
  await require('esbuild').build({
    stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
import i18n from 'i18next'; import {initReactI18next} from 'react-i18next';
import common from './src/renderer/src/locales/zh/common.json';
import {AutomationCenter} from './src/renderer/src/components/automation/AutomationCenter';
await i18n.use(initReactI18next).init({lng:'zh',resources:{zh:{common}},defaultNS:'common'});
createRoot(document.getElementById('root')).render(<AutomationCenter runtimeReady workspaceRoot="/audit" onOpenRuntimeSettings={()=>{}}/>);`,
      resolveDir: base, loader: 'tsx' },
    bundle: true, format: 'esm', jsx: 'automatic', outfile: path.join(output, 'bundle.js'),
    alias: { '@shared': path.join(base, 'src/shared') },
    define: { 'process.env.NODE_ENV': '"production"', 'import.meta.hot': 'undefined' }
  })
  const assets = path.join(base, 'out/renderer/assets')
  const css = fs.readdirSync(assets).filter(name => name.endsWith('.css'))
    .map(name => `<link rel="stylesheet" href="${pathToFileURL(path.join(assets, name)).href}">`).join('')
  fs.writeFileSync(path.join(output, 'index.html'), `<html><head>${css}</head><body><div id="root" style="height:100vh"></div><script type="module" src="bundle.js"></script></body></html>`)
  win = new BrowserWindow({ show: false, width: 1200, height: 850,
    webPreferences: { preload: path.join(output, 'preload.cjs'), contextIsolation: true, backgroundThrottling: false } })
  await win.loadFile(path.join(output, 'index.html'))
  await win.webContents.executeJavaScript(`(async()=>{
    const until = async predicate => { for(let i=0;i<100;i++){if(predicate()) return;await new Promise(r=>setTimeout(r,50))}throw Error('UI timeout') };
    await until(()=>document.body.innerText.includes('投递结果待确认'));
    const buttons=()=>[...document.querySelectorAll('button')];
    const received=buttons().find(b=>b.innerText==='已收到，标记投递成功');
    received.closest('div').querySelector('details').open=true;
    received.click();
    await until(()=>buttons().filter(b=>b.innerText==='已收到，标记投递成功').length===1);
    buttons().find(b=>b.innerText==='确认未收到，重新投递').click();
    await until(()=>!document.body.innerText.includes('投递结果待确认'));
  })()`)
  const records = fs.readdirSync(path.join(output, 'automations/runs/_http_triggers'))
    .map(name => JSON.parse(fs.readFileSync(path.join(output, 'automations/runs/_http_triggers', name))))
  assert.deepEqual(records.map(record => record.delivery_state).sort(), ['pending', 'sent'])
  assert.deepEqual(await (await fetch(api + '/v1/automations/deliveries/pending')).json(), [])
  console.log(JSON.stringify({ result: 'passed', nativeWindow: true, persistedStates: ['pending', 'sent'] }))
}).catch(error => { console.error(error); process.exitCode = 1 }).finally(async () => {
  if (win) win.destroy()
  if (server && server.exitCode === null) {
    const stopped = new Promise(resolve => server.once('exit', resolve))
    server.kill('SIGTERM')
    await stopped
  }
  fs.rmSync(output, { recursive: true, force: true })
  app.exit(process.exitCode || 0)
})
