// Run with: node_modules/.bin/electron scripts/check-typography.cjs
// Uses Chromium's real cascade: DOM emulators miss specificity and font inheritance.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { app, BrowserWindow } = require('electron')
const postcss = require('postcss')
const tailwind = require('tailwindcss')
const esbuild = require('esbuild')
const base = path.resolve(__dirname, '..')
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'workbench-typography-'))

async function check() {
  const config = (await import(path.join(base, 'tailwind.config.js'))).default
  config.content = config.content.map(entry => path.resolve(base, entry))
  const cssPath = path.join(base, 'src/renderer/src/index.css')
  const css = (await postcss([tailwind(config)]).process(fs.readFileSync(cssPath, 'utf8'), { from: cssPath })).css
  await app.whenReady()
  const win = new BrowserWindow({ show: false, width: 1300, height: 1000 })
  const html = `<html data-ui-font="system-native"><head><style>${css}</style></head><body><div class="ds-workbench-shell"><div class="ds-sidebar-shell"><span data-probe="sidebar">项目</span></div><reasoning-effort-selector></reasoning-effort-selector><div id="rail">
<textarea data-probe="composer" class="ds-composer-input">中文 English 012</textarea>
<div data-probe="user" class="ds-user-message-bubble">中文 English</div>
<textarea data-probe="edit-user" class="ds-user-message-edit-textarea text-[15px] font-medium leading-[1.58]">中文 English</textarea>
<div class="ds-markdown ds-markdown--answer ds-chat-answer"><p data-probe="answer">中文 English <strong data-probe="strong">重点 Bold</strong> <em data-probe="em">斜体 italic</em></p>
<h1 data-probe="h1">标题</h1><h2 data-probe="h2">标题</h2><h3 data-probe="h3">标题</h3><h4 data-probe="h4">标题</h4><h5 class="mt-6 mb-2 font-semibold text-base" data-streamdown="heading-5" data-probe="h5">标题</h5><h6 class="mt-6 mb-2 font-semibold text-sm" data-streamdown="heading-6" data-probe="h6">标题</h6>
<p><code class="ds-code-inline" data-streamdown="inline-code" data-probe="inline-code">code()</code> <button data-probe="file-chip" class="ds-file-chip"><span class="ds-file-chip__name">file.ts</span></button></p>
<table><thead><tr><th class="px-4 py-2 font-semibold text-sm" data-streamdown="table-header-cell" data-probe="th">表头</th></tr></thead><tbody><tr><td class="px-4 py-2 text-sm" data-streamdown="table-cell" data-probe="td">表格</td></tr></tbody></table>
<div class="ds-code-block"><span data-probe="code-label" class="ds-code-block-language">typescript</span><div class="ds-code-block-body"><div class="ds-code-block-html"><pre><code data-probe="block-code">const x = 1;</code></pre></div></div></div>
<pre data-probe="structure" class="ds-structure-block-body">tree</pre><summary data-probe="summary">详细信息</summary></div>
<div class="ds-process-reasoning"><div class="ds-markdown text-[13.5px] leading-6"><p data-probe="reasoning">推理文字</p></div></div>
<div data-probe="process-markdown" class="ds-process-assistant-md ds-markdown text-[13.5px] leading-6">过程文字</div>
<div class="ds-process-narration"><p data-probe="narration" class="text-[13.5px] leading-6">过程旁白</p></div>
</div></div>
<div class="ds-code-fullscreen"><div class="ds-expand-header"><span data-probe="fullscreen-label" class="ds-code-block-language">python</span></div><div class="ds-code-fullscreen-body ds-expand-body"><div class="ds-code-block-body"><div class="ds-code-block-html"><pre><code data-probe="fullscreen-code">const x = 1</code></pre></div></div></div></div>
<div class="ds-subagent-dialog"><div class="ds-subagent-dialog-body"><div class="ds-subagent-report-body ds-markdown ds-markdown--answer"><p data-probe="subagent-report">结果报告</p></div></div></div>
<div class="ds-markdown ds-markdown--document"><p data-probe="document">文档预览</p></div>
</body></html>`
  const fixture = path.join(scratch, 'fixture.html')
  fs.writeFileSync(fixture, html)
  await win.loadFile(fixture)
  const theme = esbuild.transformSync(fs.readFileSync(path.join(base, 'src/renderer/src/lib/apply-theme.ts'), 'utf8'), { loader: 'ts', format: 'cjs' }).code
  await win.webContents.executeJavaScript(`window.typographyTheme = (() => { const module = { exports: {} }; ${theme}; return module.exports })(); undefined`)
  const selector = esbuild.buildSync({ entryPoints: [path.join(base, 'src/renderer/src/components/chat/reasoning-effort-selector.js')], bundle: true, write: false, format: 'iife', loader: { '.svg': 'text', '.png': 'dataurl' } }).outputFiles[0].text
  await win.webContents.executeJavaScript(selector)
  const results = await win.webContents.executeJavaScript(`(() => {
    const root = document.documentElement
    const rows = []
    for (const family of ['system-native', 'inter-noto']) {
      typographyTheme.applyUiFontFamily(family)
      for (const scale of ['small', 'medium', 'large']) {
        typographyTheme.applyUiFontScale(scale)
        for (const theme of ['light', 'dark']) {
          root.setAttribute('data-theme', theme)
          for (const mode of ['chat', 'ide']) {
            document.querySelector('.ds-workbench-shell').toggleAttribute('data-ide-mode', mode === 'ide')
            document.querySelector('#rail').className = mode === 'ide' ? 'ds-ide-chat-rail' : ''
            for (const size of [12, 16, 20]) {
              root.style.setProperty('--ds-chat-font-size', size + 'px')
              root.style.setProperty('--ds-answer-font-size', size + 'px')
              const sample = {}
              for (const el of document.querySelectorAll('[data-probe]')) {
                const style = getComputedStyle(el)
                sample[el.dataset.probe] = { size: parseFloat(style.fontSize), family: style.fontFamily, line: style.lineHeight }
              }
              sample.selector = { family: getComputedStyle(document.querySelector('reasoning-effort-selector')).fontFamily }
              rows.push({ family, scale, theme, mode, size, zoom: getComputedStyle(document.body).zoom, sample })
            }
          }
        }
      }
    }
    return rows
  })()`)
  for (const { family, scale, theme, mode, size, zoom, sample } of results) {
    const context = `${family}/${scale}/${theme}/${mode}/${size}`
    assert.equal(Number(zoom), { small: 0.92, medium: 1, large: 1.08 }[scale], context)
    for (const name of ['composer', 'edit-user', 'user', 'answer', 'th', 'td', 'file-chip', 'subagent-report']) {
      assert.equal(sample[name].size, size, `${context}: ${name}`)
      assert.equal(sample[name].family, sample.answer.family, `${context}: ${name} font`)
    }
    assert.equal(sample.sidebar.family, sample.answer.family, context + ': sidebar font')
    assert.equal(sample.selector.family, sample.answer.family, context + ': selector font')
    for (const name of ['inline-code', 'block-code', 'fullscreen-code', 'structure']) {
      assert.ok(Math.abs(sample[name].size - size * 0.9) < 0.01, `${context}: ${name}`)
      assert.match(sample[name].family, /monospace/, `${context}: ${name} font`)
    }
    const headings = [1, 2, 3, 4, 5, 6].map(n => sample['h' + n].size)
    assert.ok(headings.every((value, i) => i === 0 || value <= headings[i - 1]), context + ': heading hierarchy')
    assert.equal(sample['process-markdown'].size, mode === 'ide' ? 13 : 14, context)
    assert.equal(sample.narration.size, sample.reasoning.size, context)
  }
  console.log(`Typography: ${results.length} font/scale/mode/reading-size combinations passed`)
  win.destroy()
}

check().then(() => app.quit()).catch(error => {
  console.error(error)
  app.exit(1)
}).finally(() => fs.rmSync(scratch, { recursive: true, force: true }))
