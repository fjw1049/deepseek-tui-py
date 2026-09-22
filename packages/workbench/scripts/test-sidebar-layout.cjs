// Run with: npx electron scripts/test-sidebar-layout.cjs
const { app, BrowserWindow } = require('electron')
const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const assert = require('node:assert/strict')

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, webPreferences: { offscreen: true } })
  const source = readFileSync(join(__dirname, '../src/renderer/src/index.css'), 'utf8')
  const css = source.slice(source.indexOf('.ds-sidebar-middle {'), source.indexOf('.ds-sidebar-footer {'))
  await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`
    <style>
      * { box-sizing: border-box } body { margin: 0 }
      .flex { display: flex } .flex-col { flex-direction: column }
      .h-full { height: 100% } .min-h-0 { min-height: 0 }
      .flex-1 { flex: 1 1 0% } .overflow-y-auto { overflow-y: auto }
      ${css}
    </style>
    <div id="shell" style="width:280px;padding:0 12px"><div class="ds-sidebar-middle" style="height:800px">
      <div style="height:40px;flex-shrink:0">Projects</div>
      <div class="ds-sidebar-projects-scroll overflow-y-auto">Project rows</div>
      <div class="ds-sidebar-chats-pane">
        <div class="ds-sidebar-chats-section flex h-full min-h-0 flex-col">
          <div style="height:32px;flex-shrink:0">Workspace</div>
          <div class="ds-sidebar-chats-list min-h-0 flex-1 overflow-y-auto">
            ${'<div style="height:30px">Thread</div>'.repeat(40)}
          </div>
        </div>
      </div>
    </div></div>`))
  const results = await win.webContents.executeJavaScript(`(() => {
    const middle = document.querySelector('.ds-sidebar-middle')
    const pane = document.querySelector('.ds-sidebar-chats-pane')
    const list = document.querySelector('.ds-sidebar-chats-list')
    const projects = document.querySelector('.ds-sidebar-projects-scroll')
    return [400, 800].map(height => {
      middle.style.height = height + 'px'
      const shell = document.querySelector('#shell')
      const rightGap = shell.getBoundingClientRect().right - middle.getBoundingClientRect().right
      middle.scrollTop = middle.scrollHeight
      const scrollable = middle.scrollTop > 0
      return { height, rightGap, scrollable, nestedScroll: list.scrollHeight > list.clientHeight }

    })
  })()`)
  for (const result of results) {
    assert.equal(result.rightGap, 0)
    assert.equal(result.scrollable, true)
    assert.equal(result.nestedScroll, false)
  }
  console.log('Sidebar layout passed:', results)
  app.quit()
}).catch(error => {
  console.error(error)
  app.exit(1)
})
