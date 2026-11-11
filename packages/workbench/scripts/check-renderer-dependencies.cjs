// Real Chromium acceptance for the sanitizer/editor/diagram dependency upgrade.
const { app, BrowserWindow } = require('electron')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const esbuild = require('esbuild')
const directory = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'renderer-dependencies-'))
app.setPath('userData', path.join(directory, 'chromium'))
const timeout = setTimeout(() => { console.error('Renderer dependency acceptance timed out'); app.exit(1) }, 60000)

app.whenReady().then(async () => {
  const sanitizer = path.join(path.dirname(require.resolve('dompurify')), 'purify.es.mjs')
  for (const [name, entry] of [['json', 'language/json/json.worker'], ['editor', 'editor/editor.worker']]) {
    await esbuild.build({ entryPoints: [require.resolve('monaco-editor/' + entry)],
      bundle: true, format: 'iife', outfile: path.join(directory, name + '.worker.js') })
  }
  await esbuild.build({
    stdin: { contents: `
      import {loadMermaid, initMermaid} from './src/renderer/src/lib/load-mermaid';
      import * as monaco from 'monaco-editor';
      import {getWorker} from 'monaco-editor/language/json/monaco.contribution';
      import {sanitizeHtml} from 'monaco-editor/base/browser/domSanitize';
      window.verifyDependencies = async () => {
        window.MonacoEnvironment = { getWorker: (_id, label) => new Worker(label === 'json' ? 'json.worker.js' : 'editor.worker.js') };
        const editor = monaco.editor.create(document.getElementById('editor'), { value: '中文 editor = 42', language: 'plaintext', automaticLayout: false });
        const model = editor.getModel(); model.setValue('updated 中文 = 43');
        const editorWorks = model.getValue() === 'updated 中文 = 43' && !!editor.getDomNode();
        const sanitized = String(sanitizeHtml('<img src=x onerror="alert(1)"><a href="javascript:alert(1)">unsafe</a><b>safe</b>'));
        const mermaid = await loadMermaid(); initMermaid(mermaid, 'default');
        const graph = await mermaid.render('acceptanceGraph', 'flowchart LR\\n A["中文开始"] --> B["$$x^2$$"]');
        document.getElementById('diagram').innerHTML = graph.svg;
        const json = monaco.editor.createModel('{"broken": }', 'json', monaco.Uri.parse('file:///acceptance.json'));
        const factory = await getWorker();
        const worker = await factory(json.uri);
        const workerValidated = (await worker.doValidation(json.uri.toString())).length > 0;
        const result = {editorWorks, workerValidated, sanitized, svg: graph.svg.includes('<svg'), math: graph.svg.includes('katex'), chinese: graph.svg.includes('中文开始')};
        editor.dispose(); model.dispose(); json.dispose(); return result;
      };
    `, resolveDir: path.resolve(__dirname, '..'), loader: 'ts' },
    bundle: true, format: 'iife', outfile: path.join(directory, 'bundle.js'),
    loader: { '.ttf': 'file' },
    plugins: [{ name: 'patched-monaco-sanitizer', setup(build) {
      build.onResolve({ filter: /^\.\/dompurify\/dompurify\.js$/ }, () => ({ path: sanitizer }))
    } }]
  })
  fs.writeFileSync(path.join(directory, 'index.html'), '<link rel="stylesheet" href="bundle.css"><div id="editor" style="width:700px;height:200px"></div><div id="diagram"></div><script src="bundle.js"></script>')
  const window = new BrowserWindow({ show: false, webPreferences: { backgroundThrottling: false } })
  try {
    await window.loadFile(path.join(directory, 'index.html'))
    const result = await window.webContents.executeJavaScript('window.verifyDependencies()')
    assert(result.editorWorks && result.workerValidated && result.svg && result.math && result.chinese, JSON.stringify(result))
    assert(!/onerror|javascript:/i.test(result.sanitized), result.sanitized)
    assert(result.sanitized.includes('<b>safe</b>'), result.sanitized)
    console.log(JSON.stringify(result))
  } finally { window.destroy() }
}).then(() => app.exit(0)).catch(error => { console.error(error); app.exit(1) }).finally(() => {
  clearTimeout(timeout)
  fs.rmSync(directory, { recursive: true, force: true })
})
