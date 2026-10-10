// Run npm run build, then npm run audit:fonts.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { pathToFileURL } = require('node:url')
const { app, BrowserWindow } = require('electron')
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
  ['marketplace-file', '<div class="ds-marketplace-doc-file">TEXT</div>', true]
]
function inPage(win, fn, argument) {
  return win.webContents.executeJavaScript('(' + fn.toString() + ')(' + JSON.stringify(argument) + ')')
}
async function check() {
  const assets = path.join(base, 'out/renderer/assets')
  const cssFiles = fs.readdirSync(assets).filter(name => name.endsWith('.css'))
  assert(cssFiles.length > 0, 'Build the renderer before auditing fonts.')
  for (const family of ['inter', 'jetbrains-mono', 'noto-sans-sc']) {
    assert(fs.existsSync(path.join(base, 'out/renderer/font-licenses', family + '-OFL.txt')))
  }
  await app.whenReady()
  const win = new BrowserWindow({ show: false, width: 1200, height: 1200, webPreferences: { backgroundThrottling: false } })
  win.webContents.session.webRequest.onBeforeRequest(
    { urls: ['http://*/*', 'https://*/*'] },
    (_request, callback) => callback({ cancel: true })
  )
  const fixture = path.join(scratch, 'fixture.html')
  const links = cssFiles.map(name => '<link rel="stylesheet" href="' + pathToFileURL(path.join(assets, name)).href + '">').join('')
  fs.writeFileSync(fixture, '<!doctype html><html data-ui-font="inter-noto"><head>' + links + '</head><body><main id="samples"></main></body></html>')
  await win.loadFile(fixture)
  const selector = esbuild.buildSync({ entryPoints: [path.join(base, 'src/renderer/src/components/chat/reasoning-effort-selector.js')], bundle: true, write: false, format: 'iife', loader: { '.svg': 'text', '.png': 'dataurl' } }).outputFiles[0].text
  await win.webContents.executeJavaScript(selector)
  const browser = esbuild.buildSync({
    stdin: {
      contents: [
        "import * as theme from './src/renderer/src/lib/apply-theme';",
        "import * as appearance from './src/shared/appearance';",
        "import { applyAppearance } from './src/renderer/src/lib/apply-appearance';",
        "import { Terminal } from '@xterm/xterm';",
        "import { FitAddon } from '@xterm/addon-fit';",
        "import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';",
        "window.fontAudit = { ...theme, ...appearance, applyAppearance, Terminal, FitAddon, monaco };"
      ].join('\n'),
      resolveDir: base,
      loader: 'ts'
    },
    alias: { '@shared': path.join(base, 'src/shared') },
    bundle: true, write: false, format: 'iife', loader: { '.css': 'empty' }
  }).outputFiles[0].text
  await win.webContents.executeJavaScript(browser)
  await inPage(win, async () => {
    for (const family of ['Inter', 'JetBrains Mono', 'Noto Sans SC']) {
      for (const weight of [400, 500, 600, 700]) {
        const faces = await document.fonts.load(weight + ' 14px "' + family + '"', family === 'Noto Sans SC' ? '中文' : 'English')
        if (!faces.length) throw new Error('Missing bundled font: ' + family + '/' + weight)
      }
    }
    for (const family of ['Inter', 'JetBrains Mono']) for (const weight of [400, 700]) {
      const faces = await document.fonts.load('italic ' + weight + ' 14px "' + family + '"')
      if (!faces.length) throw new Error('Missing bundled italic: ' + family + '/' + weight)
    }
  })
  const results = await inPage(win, (samples) => {
    const api = window.fontAudit
    const host = document.querySelector('#samples')
    const rows = []
    for (const lang of ['zh-CN', 'en']) for (const theme of ['light', 'dark']) for (const preset of api.listThemePresetsForVariant(theme)) for (const [scale, factor] of [['small', '.83'], ['medium', '.88'], ['large', '.95']]) {
      document.documentElement.lang = lang
      document.documentElement.dataset.theme = theme
      api.applyUiFontScale(scale)
      const appearance = api.defaultAppearanceSettings()
      appearance.themes[theme] = api.applyThemePreset(appearance.themes[theme], preset.id, theme)
      api.applyAppearance(appearance)
      host.innerHTML = samples.map(([name, html]) => '<section data-name="' + name + '">' + html.replace('TEXT', '项目 Project 中文 English 0123，。！？') + '</section>').join('') + '<reasoning-effort-selector></reasoning-effort-selector>'
      const ui = getComputedStyle(document.body).fontFamily
      const mono = getComputedStyle(document.querySelector('kbd')).fontFamily
      if (!ui.startsWith('Inter,')) throw new Error('UI fallback in ' + preset.id + ': ' + ui)
      if (!mono.startsWith('"JetBrains Mono",')) throw new Error('Code fallback in ' + preset.id + ': ' + mono)
      for (const [name, , code] of samples) {
        const section = host.querySelector('[data-name="' + name + '"]')
        const leaf = [...section.querySelectorAll('*')].at(-1)
        const style = getComputedStyle(leaf)
        rows.push({ lang, theme, preset: preset.id, scale, name, expected: code ? mono : ui, family: style.fontFamily, size: style.fontSize, weight: style.fontWeight, line: style.lineHeight, spacing: style.letterSpacing, zoom: getComputedStyle(document.body).zoom, factor })
      }
      const selector = host.querySelector('reasoning-effort-selector')
      rows.push({ lang, theme, preset: preset.id, scale, name: 'shadow-selector', expected: ui, family: getComputedStyle(selector.shadowRoot.querySelector('.pill')).fontFamily })
    }
    return rows
  }, samples)
  for (const row of results) {
    assert.equal(row.family, row.expected, row.name + '/' + row.lang + '/' + row.theme + '/' + row.preset + '/' + row.scale)
    if (row.name.startsWith('navigation-')) assert.equal(row.weight, '500', row.name)
    if (row.zoom) assert.equal(Number(row.zoom), Number(row.factor))
  }
  const cards = []
  for (const kind of ['ui', 'code', 'terminal']) for (const weight of [400, 500, 600, 700]) for (const language of ['en', 'zh']) {
    cards.push({ id: kind + '-' + weight + '-' + language, kind, weight, language, italic: false })
  }
  for (const kind of ['ui', 'code']) for (const weight of [400, 700]) {
    cards.push({ id: kind + '-' + weight + '-italic', kind, weight, language: 'en', italic: true })
  }
  const instances = await inPage(win, async (cards) => {
    const api = window.fontAudit
    api.applyUiFontScale('medium')
    api.applyAppearance(api.defaultAppearanceSettings())
    document.documentElement.dataset.theme = 'light'
    document.body.style.zoom = '1'
    document.querySelector('#samples').innerHTML = '<h1 style="font-size:22px">内置字体实际渲染审核</h1><div id="font-cards" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px"></div><div id="audit-monaco" style="width:1100px;height:180px"></div><div id="audit-terminal" style="width:1100px;height:180px"></div>'
    document.body.style.cssText += ';padding:24px;background:#f6f6f6'
    document.querySelector('#font-cards').innerHTML = cards.map(card => {
      const family = card.kind === 'ui' ? 'var(--font-ui)' : card.kind === 'code' ? 'var(--font-mono)' : 'var(--font-terminal)'
      return '<div><small style="font-size:11px;color:#666">' + card.id + '</small><p id="' + card.id + '" style="font-family:' + family + ';font-size:16px;font-weight:' + card.weight + ';font-style:' + (card.italic ? 'italic' : 'normal') + ';margin:4px 0">' + (card.language === 'zh' ? '中文项目设置' : 'Project English 0123') + '</p></div>'
    }).join('')
    await document.fonts.ready
    const mono = getComputedStyle(document.documentElement).getPropertyValue('--font-mono').trim()
    const editor = api.monaco.editor.create(document.querySelector('#audit-monaco'), {
      value: 'const project = "中文项目";\n// JetBrains Mono 0O 1lI == != =>',
      language: 'plaintext', fontFamily: mono, fontSize: 14, lineHeight: 21,
      minimap: { enabled: false }, automaticLayout: false
    })
    const terminal = new api.Terminal({ fontFamily: api.readTerminalFontFamily(), fontSize: 13, lineHeight: 1.2 })
    const fit = new api.FitAddon()
    terminal.loadAddon(fit)
    terminal.open(document.querySelector('#audit-terminal'))
    fit.fit()
    await new Promise(resolve => terminal.write('JetBrains Mono 0O 1lI\r\n中文终端列宽检查\r\n0123456789', resolve))
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    const ctx = document.createElement('canvas').getContext('2d')
    ctx.font = '400 14px ' + mono
    const widths = [...'iW0Ol1'].map(char => ctx.measureText(char).width)
    return {
      editorFamily: editor.getOption(api.monaco.editor.EditorOption.fontFamily),
      editorWidth: editor.getOption(api.monaco.editor.EditorOption.fontInfo).typicalHalfwidthCharacterWidth,
      widths, terminalFamily: terminal.options.fontFamily,
      terminalCellWidths: [
        terminal.buffer.active.getLine(0).getCell(0).getWidth(),
        terminal.buffer.active.getLine(1).getCell(0).getWidth(),
        terminal.buffer.active.getLine(1).getCell(1).getWidth(),
        terminal.buffer.active.getLine(1).getCell(2).getWidth()
      ],
      cols: terminal.cols, rows: terminal.rows, fit: fit.proposeDimensions()
    }
  }, cards)
  assert(instances.editorFamily.startsWith("'JetBrains Mono'"))
  assert(instances.terminalFamily.startsWith('JetBrains Mono'))
  assert(Math.max(...instances.widths) - Math.min(...instances.widths) < 0.05, 'ASCII glyphs must remain monospace')
  assert(Math.abs(instances.editorWidth - instances.widths[0]) < 0.1, 'Monaco measured a fallback font')
  assert(instances.cols > 20 && instances.rows > 5)
  assert.equal(instances.cols, instances.fit.cols)
  assert.equal(instances.rows, instances.fit.rows)
  assert.deepEqual(instances.terminalCellWidths, [1, 2, 0, 2], 'Chinese terminal glyphs must occupy two cells')
  win.webContents.debugger.attach('1.3')
  const send = (method, params) => win.webContents.debugger.sendCommand(method, params)
  await send('DOM.enable')
  await send('CSS.enable')
  const { root } = await send('DOM.getDocument')
  const glyphs = []
  for (const card of cards) {
    const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: '#' + card.id })
    const { fonts } = await send('CSS.getPlatformFontsForNode', { nodeId })
    const expected = card.language === 'zh' ? 'Noto Sans SC' : card.kind === 'ui' ? 'Inter' : 'JetBrains Mono'
    assert(fonts.length > 0, card.id)
    for (const font of fonts) {
      // Static faces expose internal names such as Inter Medium and Noto Sans SC Thin.
      assert(font.familyName === expected || font.familyName.startsWith(expected + ' '), card.id + ': ' + JSON.stringify(font))
      assert(font.isCustomFont, card.id + ' must use the bundled font')
      const weightName = { 400: /regular|italic/i, 500: /medium/i, 600: /semibold/i, 700: /bold/i }[card.weight]
      assert(weightName.test(font.postScriptName), card.id + ' must use the requested weight')
      if (card.italic) assert(/italic/i.test(font.postScriptName), card.id + ' must use a real italic face')
    }
    glyphs.push({ ...card, fonts })
  }
  for (const selector of ['#audit-monaco .view-lines', '#audit-terminal .xterm-rows']) {
    const { nodeIds } = await send('DOM.querySelectorAll', { nodeId: root.nodeId, selector: selector + ' span' })
    assert(nodeIds.length > 0, selector)
    const fonts = []
    for (const nodeId of nodeIds) {
      fonts.push(...(await send('CSS.getPlatformFontsForNode', { nodeId })).fonts)
    }
    assert(fonts.some(font => font.familyName === 'JetBrains Mono'), selector + ': ' + JSON.stringify(fonts))
    assert(fonts.some(font => font.familyName.startsWith('Noto Sans SC')), selector + ': ' + JSON.stringify(fonts))
    assert(fonts.every(font => font.isCustomFont), selector)
    glyphs.push({ selector, fonts })
  }
  if (output) {
    fs.mkdirSync(output, { recursive: true })
    fs.writeFileSync(path.join(output, 'computed-fonts.json'), JSON.stringify({ results, glyphs, instances }, null, 2))
    fs.writeFileSync(path.join(output, 'font-comparison.png'), (await win.webContents.capturePage()).toPNG())
  }
  console.log(results.length + ' surface/language/preset/scale checks passed; ' + glyphs.length + ' actual glyph checks use bundled fonts.')
  console.log(JSON.stringify(instances))
  win.destroy()
}
check().then(() => app.quit()).catch(error => { console.error(error); app.exit(1) }).finally(() => fs.rmSync(scratch, { recursive: true, force: true }))
