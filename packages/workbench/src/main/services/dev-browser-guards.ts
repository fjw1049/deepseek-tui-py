import { app, session } from 'electron'
import { isBrowsableUrl } from '../../shared/dev-preview-url'
import { DEV_BROWSER_PARTITION } from '../../shared/browser-bridge'

export function installDevPreviewWebviewGuards(): void {
  // This partition is separate from the shell's microphone-enabled session.
  // Electron otherwise grants guest permission requests automatically.
  const browserSession = session.fromPartition(DEV_BROWSER_PARTITION)
  browserSession.setPermissionCheckHandler((_contents, permission) =>
    permission === 'fullscreen' || permission === 'clipboard-sanitized-write'
  )
  browserSession.setPermissionRequestHandler((_contents, permission, callback) => {
    callback(permission === 'fullscreen' || permission === 'clipboard-sanitized-write')
  })

  const popupContents = new Set<number>()
  app.on('web-contents-created', (_, contents) => {
    contents.on('will-attach-webview', (event, webPreferences, params) => {
      // Blank tabs are where agent-opened pages start.
      const src = params.src ?? ''
      if (!(src === 'about:blank' || isBrowsableUrl(src)) || params.partition !== DEV_BROWSER_PARTITION) {
        event.preventDefault()
        return
      }

      delete webPreferences.preload
      delete (webPreferences as { preloadURL?: string }).preloadURL
      webPreferences.nodeIntegration = false
      webPreferences.nodeIntegrationInSubFrames = false
      webPreferences.nodeIntegrationInWorker = false
      webPreferences.contextIsolation = true
      webPreferences.sandbox = true
      webPreferences.webSecurity = true
      webPreferences.webviewTag = false
      webPreferences.allowRunningInsecureContent = false
    })

    const isBrowser = (): boolean => contents.getType() === 'webview' || popupContents.has(contents.id)
    contents.on('did-create-window', child => {
      if (!isBrowser()) return
      const id = child.webContents.id
      popupContents.add(id)
      child.webContents.once('destroyed', () => popupContents.delete(id))
    })
    contents.on('will-navigate', (event, url) => {
      if (isBrowser() && !isBrowsableUrl(url)) event.preventDefault()
    })
    contents.on('will-redirect', (event, url, _isInPlace, isMainFrame) => {
      if (isBrowser() && isMainFrame && !isBrowsableUrl(url)) {
        event.preventDefault()
      }
    })

    contents.setWindowOpenHandler(({ url }) => {
      if (!isBrowser()) return { action: 'allow' }
      if (url !== 'about:blank' && !isBrowsableUrl(url)) return { action: 'deny' }
      // A real child preserves opener/postMessage without replacing the draft page.
      return { action: 'allow', overrideBrowserWindowOptions: {
        autoHideMenuBar: true,
        webPreferences: { partition: DEV_BROWSER_PARTITION, nodeIntegration: false,
          nodeIntegrationInSubFrames: false, nodeIntegrationInWorker: false,
          contextIsolation: true, sandbox: true, webSecurity: true, webviewTag: false,
          allowRunningInsecureContent: false, preload: undefined }
      } }
    })
  })
}
