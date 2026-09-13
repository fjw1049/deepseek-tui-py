// Isolated CSS probe, not a screenshot of the live application.
// From packages/workbench: npx electron ../../docs/workspace-visual-audit-2026-09-13/probe.cjs
// First compile current CSS to /tmp/workspace-visual-audit.css with Tailwind CLI.
const { app, BrowserWindow } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
app.commandLine.appendSwitch('user-data-dir', '/tmp/workspace-visual-audit-electron')
app.whenReady().then(async () => {
  const css = fs.readFileSync('/tmp/workspace-visual-audit.css', 'utf8')
  const win = new BrowserWindow({ show: false, width: 1000, height: 620, webPreferences: { offscreen: true } })
  await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`<style>${css}</style>
    <div class="ds-ide-workspace" style="padding:24px;background:var(--ds-bg-canvas);height:100vh">
    <p style="margin-bottom:16px">隔离样式验证 · 源码结构样本（非运行中应用截图）</p>
    <div style="display:flex">
      <div style="width:232px" class="ds-workspace-file-tree">
        <div id="tree-header" class="ds-workspace-file-tree__header flex h-10 items-center"><div>项目文件</div></div>
        <button class="ds-workspace-file-tree__row-pad h-7 w-full text-left" style="padding-left:12px">src / components</button>
      </div>
      <div style="flex:1;min-width:0">
        <div id="tabs" class="ds-workspace-editor-tabstrip flex shrink-0 items-center gap-1.5">
          <span class="ds-workspace-editor-tab ds-workspace-editor-tab--active group inline-flex items-center">
            <button class="inline-flex min-w-0 items-center gap-1 px-2 py-1 text-[12.5px]">WorkspaceEditorPanel.tsx</button>
            <button id="close" class="ds-workspace-editor-tab__close relative mr-0.5 inline-flex h-5 w-5 items-center justify-center rounded"><span class="ds-workspace-editor-tab__close-dot"></span></button>
          </span>
        </div>
        <div class="ds-workspace-editor-pane"><div class="monaco-editor"><div class="view-lines"><div id="line" class="view-line ds-editor-line-added" style="position:relative;height:24px"><span id="token" class="ds-editor-line-added-inline">const changed = true;</span></div></div></div></div>
        <div style="width:350px;margin-top:24px"><table class="w-full table-fixed border-collapse"><tbody><tr><td id="code" class="max-w-0 break-all whitespace-pre-wrap px-2 align-top font-mono text-[15px] leading-[1.45]">+ const result = workspaceEditor.getModel().getValue().split('/').filter(Boolean).map(segment =&gt; normalizeSegment(segment));</td></tr></tbody></table></div>
      </div>
    </div></div>`))
  const metrics = await win.webContents.executeJavaScript(`(() => {
    const get = id => { const n=document.getElementById(id),s=getComputedStyle(n);return {height:n.getBoundingClientRect().height,fontSize:s.fontSize,lineHeight:s.lineHeight,opacity:s.opacity,background:s.backgroundColor,wordBreak:s.wordBreak,whiteSpace:s.whiteSpace} };
    const light={tree:get('tree-header'),tabs:get('tabs'),close:get('close'),code:get('code')};
    document.documentElement.setAttribute('data-theme','dark');
    return {light,dark:{close:get('close')},missingAlphaHoverRule:![...document.styleSheets[0].cssRules].some(r=>r.selectorText?.includes('hover\\\\:bg-ds-hover\\\\/55'))};
  })()`)
  fs.writeFileSync(path.join(__dirname, 'computed.json'), JSON.stringify(metrics,null,2)+'\n')
  await win.webContents.executeJavaScript(`document.documentElement.setAttribute('data-theme','light'); new Promise(resolve => setTimeout(resolve, 300))`)
  fs.writeFileSync(path.join(__dirname, 'isolated-light.png'), (await win.webContents.capturePage()).toPNG())
  console.log(JSON.stringify(metrics,null,2))
  app.quit()
}).catch(e => { console.error(e); app.exit(1) })
