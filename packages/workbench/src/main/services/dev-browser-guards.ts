import { app, session } from 'electron'
import { isBrowsableUrl, upgradeToBrowsableUrl } from '../../shared/dev-preview-url'
import { DEV_BROWSER_PARTITION } from '../../shared/browser-bridge'
import { logWarn } from '../logger'

/** Decides whether a page may open a window now; false while the agent drives its tab. */
let popupGate: ((openerId: number, url: string) => boolean) | null = null
export function setPopupGate(gate: typeof popupGate): void {
  popupGate = gate
}

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
    // Public http (search result redirectors, older links) is tried over https, never in cleartext.
    const navigate = (url: string): void => {
      void contents.loadURL(url).catch((error: unknown) => {
        logWarn('dev-browser-navigation', 'Link navigation failed', String(error))
      })
    }
    const guardNavigation = (event: { preventDefault(): void }, url: string): void => {
      const next = upgradeToBrowsableUrl(url)
      if (next === url) return
      event.preventDefault()
      if (next) navigate(next)
    }
    contents.on('will-navigate', (event, url) => {
      if (isBrowser()) guardNavigation(event, url)
    })
    contents.on('will-redirect', (event, url, _isInPlace, isMainFrame) => {
      if (isBrowser() && isMainFrame) guardNavigation(event, url)
    })

    contents.setWindowOpenHandler(({ url, disposition }) => {
      if (!isBrowser()) return { action: 'allow' }
      const next = url === 'about:blank' ? url : upgradeToBrowsableUrl(url)
      if (!next) return { action: 'deny' }
      // Plain new-tab links (search results) stay in the current tab: no bare window, and a
      // demonstration keeps recording the same page. Sized popups (sign-in) keep their opener.
      // A child window cannot be given another URL, so an upgraded link also stays here.
      const tabLink = disposition === 'foreground-tab' || disposition === 'background-tab'
      if (contents.getType() === 'webview' && next !== 'about:blank' && (tabLink || next !== url)) {
        navigate(next)
        return { action: 'deny' }
      }
      if (next !== url) return { action: 'deny' }
      // Sign-in and payment windows open only from the user's own clicks, never the agent's.
      if (popupGate && !popupGate(contents.id, url)) return { action: 'deny' }
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
