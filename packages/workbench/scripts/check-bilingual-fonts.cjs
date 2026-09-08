// Run with node_modules/.bin/electron scripts/check-bilingual-fonts.cjs.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { app, BrowserWindow } = require('electron')
const postcss = require('postcss')
const tailwind = require('tailwindcss')
const esbuild = require('esbuild')
const base = path.resolve(__dirname, '..')
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'bilingual-fonts-'))
const output = process.env.FONT_AUDIT_OUTPUT
const samples = [
  ['navigation-button', '<div class="ds-sidebar-shell"><button class="ds-sidebar-link">TEXT</button></div>'],
  ['navigation-active', '<div class="ds-sidebar-shell"><button class="ds-sidebar-link ds-sidebar-link--active">TEXT</button></div>'],
  ...['ds-sidebar-shell', 'ds-settings-page', 'ds-feature-page', 'ds-plugin-page', 'ds-channel-page',
    'ds-automation-page', 'ds-automation-form', 'ds-modal-surface', 'ds-tool-panel', 'ds-topbar-surface',
    'ds-project-context-menu', 'ds-editor-picker-menu', 'ds-composer-command-popover',
    'ds-session-header', 'ds-workbench-right-panel', 'ds-ide-workspace'].map(name => [name, `<div class="${name}"><span>TEXT</span></div>`]),
  ['portal', '<div><button class="font-ui text-[13px]">TEXT</button></div>'],
  ['composer', '<div><textarea class="ds-composer-input">TEXT</textarea></div>'],
  ['edit', '<div><textarea class="ds-user-message-edit-textarea">TEXT</textarea></div>'],
  ['user', '<div><div class="ds-user-message-bubble">TEXT</div></div>'],
  ['answer', '<div class="ds-markdown ds-markdown--answer"><p>TEXT</p></div>'],
  ['heading', '<div class="ds-markdown ds-markdown--answer"><h2>TEXT</h2></div>'],
  ['table', '<div class="ds-markdown ds-markdown--answer"><table><tbody><tr><td>TEXT</td></tr></tbody></table></div>'],
  ['process', '<div class="ds-process-reasoning"><div class="ds-markdown"><p>TEXT</p></div></div>'],
  ['ide-answer', '<div class="ds-ide-chat-rail"><div class="ds-markdown ds-markdown--answer"><p>TEXT</p></div></div>'],
  ['ide-input', '<div class="ds-ide-chat-rail"><textarea class="ds-composer-input">TEXT</textarea></div>'],
  ['report', '<div class="ds-subagent-dialog"><div class="ds-markdown ds-markdown--answer"><p>TEXT</p></div></div>'],
  ['inline-code', '<div class="ds-markdown"><code data-streamdown="inline-code" class="ds-code-inline">TEXT</code></div>', true],
  ['code-block', '<div class="ds-markdown"><pre><code>TEXT</code></pre></div>', true],
  ['fullscreen-code', '<div class="ds-code-fullscreen"><pre><code>TEXT</code></pre></div>', true],
  ['keyboard', '<div><kbd>TEXT</kbd></div>', true],
  ['model-id', '<div><span class="ds-llm-model-row__name">TEXT</span></div>', true],
  ['editor-deletion', '<div class="ds-workspace-editor-pane"><span class="ds-editor-deleted-line">TEXT</span></div>', true]
]
async function check() {
  const config = (await import(path.join(base, 'tailwind.config.js'))).default
  config.content = config.content.map(entry => path.resolve(base, entry))
  const cssPath = path.join(base, 'src/renderer/src/index.css')
  const css = (await postcss([tailwind(config)]).process(fs.readFileSync(cssPath, 'utf8'), { from: cssPath })).css
  await app.whenReady()
  const win = new BrowserWindow({ show: false, width: 1200, height: 900 })
  const fixture = path.join(scratch, 'fixture.html')
  fs.writeFileSync(fixture, `<html data-ui-font="system-native"><head><style>${css}</style></head><body><main id="samples"></main></body></html>`)
  await win.loadFile(fixture)
  const selector = esbuild.buildSync({ entryPoints: [path.join(base, 'src/renderer/src/components/chat/reasoning-effort-selector.js')], bundle: true, write: false, format: 'iife', loader: { '.svg': 'text', '.png': 'dataurl' } }).outputFiles[0].text
  await win.webContents.executeJavaScript(selector)
  const theme = esbuild.transformSync(fs.readFileSync(path.join(base, 'src/renderer/src/lib/apply-theme.ts'), 'utf8'), { loader: 'ts', format: 'cjs' }).code
  await win.webContents.executeJavaScript(`window.theme = (() => { const module = {exports:{}}; ${theme}; return module.exports })(); undefined`)
  const results = await win.webContents.executeJavaScript(`(() => {
    const samples = ${JSON.stringify(samples)}
    const host = document.querySelector('#samples')
    const rows = []
    for (const lang of ['zh-CN', 'en']) for (const theme of ['light', 'dark']) for (const [scale, factor] of [['small', '.86'], ['medium', '.92'], ['large', '1']]) {
      document.documentElement.lang = lang
      document.documentElement.dataset.theme = theme
      window.theme.applyUiFontScale(scale)
      host.innerHTML = samples.map(([name, html]) => '<section data-name="' + name + '">' + html.replace('TEXT', '项目 Project 中文 English 0123，。！？') + '</section>').join('') + '<reasoning-effort-selector></reasoning-effort-selector>'
      const ui = getComputedStyle(document.body).fontFamily
      const mono = getComputedStyle(document.querySelector('kbd')).fontFamily
      for (const [name, , code] of samples) {
        const section = host.querySelector('[data-name="' + name + '"]')
        const leaf = [...section.querySelectorAll('*')].at(-1)
        const style = getComputedStyle(leaf)
        rows.push({ lang, theme, scale, name, expected: code ? mono : ui, family: style.fontFamily, size: style.fontSize, weight: style.fontWeight, line: style.lineHeight, spacing: style.letterSpacing, zoom: getComputedStyle(document.body).zoom, factor })
      }
      const selector = host.querySelector('reasoning-effort-selector')
      rows.push({ lang, theme, scale, name: 'shadow-selector', expected: ui, family: getComputedStyle(selector.shadowRoot.querySelector('.pill')).fontFamily })
    }
    return rows
  })()`)
  for (const row of results) {
    assert.equal(row.family, row.expected, `${row.name}/${row.lang}/${row.theme}/${row.scale}`)
    if (row.name.startsWith('navigation-')) assert.equal(row.weight, '500', row.name)
    if (row.zoom) assert.equal(Number(row.zoom), Number(row.factor))
  }
  // Local Codex desktop default; compare real glyph selection, not CSS strings.
  const cards = ['reference','app'].flatMap(kind => [400,500,600,700].flatMap(weight => ['中文项目设置','Project English 0123'].map((text,i) => `<p id="${kind}-${weight}-${i}" style="font-family:${kind === 'reference' ? '-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif' : 'var(--font-ui)'};font-size:16px;font-weight:${weight}">${text}</p>`))).join('')
  await win.webContents.executeJavaScript(`document.querySelector('#samples').innerHTML = ${JSON.stringify(cards)}; undefined`)
  win.webContents.debugger.attach('1.3')
  const send = (method, params) => win.webContents.debugger.sendCommand(method, params)
  await send('DOM.enable')
  await send('CSS.enable')
  const { root } = await send('DOM.getDocument')
  const glyphs = []
  for (const weight of [400, 500, 600, 700]) for (const language of [0, 1]) {
    const pair = []
    for (const kind of ['reference', 'app']) {
      const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: `#${kind}-${weight}-${language}` })
      const { fonts } = await send('CSS.getPlatformFontsForNode', { nodeId })
      pair.push(fonts.map(font => ({ family: font.familyName, postscript: font.postScriptName, glyphs: font.glyphCount })))
    }
    assert.deepEqual(pair[1], pair[0], `Codex glyph parity ${weight}/${language}`)
    glyphs.push({ weight, language: language ? 'en' : 'zh', fonts: pair[1] })
  }
  if (output) {
    fs.mkdirSync(output, { recursive: true })
    fs.writeFileSync(path.join(output, 'computed-fonts.json'), JSON.stringify({ results, glyphs }, null, 2))
    const visual = '<h1 style="grid-column:1/-1;font-size:22px">中英文混排 · 字体配置对照</h1><b>Codex 默认字体配置</b><b>当前项目</b>' + [400,500,600,700].flatMap(weight => ['reference','app'].map(kind => `<p style="font-family:${kind === 'reference' ? '-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif' : 'var(--font-ui)'};font-size:16px;font-weight:${weight};line-height:1.8">${weight} · 项目 Project / 新会话 New chat<br>中文 English 0123，。！？</p>`)).join('')
    await win.webContents.executeJavaScript(`document.documentElement.dataset.theme='light'; document.body.style.zoom='1'; document.body.style.background='#f6f6f6'; document.querySelector('#samples').style.cssText='display:grid;grid-template-columns:1fr 1fr;padding:32px;gap:16px'; document.querySelector('#samples').innerHTML=${JSON.stringify(visual)}; undefined`)
    fs.writeFileSync(path.join(output, 'font-comparison.png'), (await win.webContents.capturePage()).toPNG())
  }
  console.log(`${results.length} surface/language/theme/scale checks passed; 8 actual glyph comparisons match Codex default.`)
  console.log(JSON.stringify(glyphs))
  win.destroy()
}
check().then(() => app.quit()).catch(error => { console.error(error); app.exit(1) }).finally(() => fs.rmSync(scratch, { recursive: true, force: true }))
