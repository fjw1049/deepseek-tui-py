/** Run with Electron after `npm run build`; exercises the real main/preload/renderer. */
const { app, BrowserWindow, dialog } = require('electron')
const { mkdtempSync, mkdirSync, writeFileSync } = require('node:fs')
const { tmpdir } = require('node:os')
const { join } = require('node:path')
const { pathToFileURL } = require('node:url')
const assert = require('node:assert/strict')

const directory = mkdtempSync(join(tmpdir(), 'workbench-startup-'))
const home = join(directory, 'settings')
const userData = join(directory, 'chromium')
mkdirSync(home); mkdirSync(userData)
process.env.DEEPSEEK_HOME = home
process.env.DEEPSEEK_GUI_BUILT_RENDERER = '1'
process.env.DEEPSEEK_GUI_STARTUP_TRACE = '1'
// Exercise development diagnostics while loading the built renderer offline.
process.env.ELECTRON_RENDERER_URL = 'http://127.0.0.1:1'
delete process.env.DEEPSEEK_API_KEY
writeFileSync(join(home, 'settings.json'), JSON.stringify({ version: 1,
  workspaceRoot: directory, deepseek: { autoStart: false, apiKey: '' },
  browserDownloadDirectory: directory, browserAskDownloadLocation: false }))
writeFileSync(join(home, 'config.toml'), '')
app.setPath('userData', userData)
let finished = false
function finish(error) {
  if (finished) return
  finished = true
  clearTimeout(timeout)
  if (error) console.error('STARTUP_SMOKE_FAILED', error)
  else console.log('STARTUP_SMOKE_PASSED: main initialized, renderer loaded, settings IPC available')
  app.exit(error ? 1 : 0)
}
const timeout = setTimeout(() => finish(new Error('Startup timed out')), 30000)
dialog.showErrorBox = (title, message) => finish(new Error(`${title}: ${message}`))
app.on('browser-window-created', (_event, window) => {
  window.webContents.once('did-fail-load', (_event, code, description) => finish(new Error(`${code}: ${description}`)))
  window.webContents.once('did-finish-load', async () => {
    try {
      assert.equal(app.commandLine.getSwitchValue('remote-debugging-port'), '0')
      const settings = await window.webContents.executeJavaScript('window.dsGui.getSettings()')
      assert.equal(settings.browserDownloadDirectory, directory)
      assert.equal(settings.browserAskDownloadLocation, false)
      assert.ok(BrowserWindow.getAllWindows().length > 0)
      finish()
    } catch (error) { finish(error) }
  })
})
import(pathToFileURL(join(__dirname, '../out/main/index.js')).href).catch(finish)
