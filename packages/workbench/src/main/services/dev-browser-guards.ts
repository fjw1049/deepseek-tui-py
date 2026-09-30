import { app, session } from 'electron'
import { isBrowsableUrl } from '../../shared/dev-preview-url'
import { logWarn } from '../logger'

export function installDevPreviewWebviewGuards(): void {
  // This partition is separate from the shell's microphone-enabled session.
  // Electron otherwise grants guest permission requests automatically.
  const browserSession = session.fromPartition('persist:deepseek-dev-browser')
  browserSession.setPermissionCheckHandler((_contents, permission) =>
    permission === 'fullscreen' || permission === 'clipboard-sanitized-write'
  )
  browserSession.setPermissionRequestHandler((_contents, permission, callback) => {
    callback(permission === 'fullscreen' || permission === 'clipboard-sanitized-write')
  })

  app.on('web-contents-created', (_, contents) => {
    contents.on('will-attach-webview', (event, webPreferences, params) => {
      if (!isBrowsableUrl(params.src ?? '') || params.partition !== 'persist:deepseek-dev-browser') {
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

    contents.on('will-navigate', (event, url) => {
      if (contents.getType() === 'webview' && !isBrowsableUrl(url)) event.preventDefault()
    })
    contents.on('will-redirect', (event, url, _isInPlace, isMainFrame) => {
      if (contents.getType() === 'webview' && isMainFrame && !isBrowsableUrl(url)) {
        event.preventDefault()
      }
    })

    contents.setWindowOpenHandler(({ url }) => {
      if (contents.getType() !== 'webview') return { action: 'allow' }
      // Keep target=_blank in the existing guest so its history stays usable.
      if (isBrowsableUrl(url)) {
        void contents.loadURL(url).catch((error: unknown) => {
          logWarn('dev-browser-navigation', 'Popup navigation failed', String(error))
        })
      }
      return { action: 'deny' }
    })
  })
}
