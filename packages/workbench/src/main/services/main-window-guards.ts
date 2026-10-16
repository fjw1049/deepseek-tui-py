import type { WebContents } from 'electron'

type MainWindowGuardOptions = {
  /** The renderer entry the window is allowed to stay on (dev server URL or file:// index.html). */
  appUrl: string
  openExternal: (url: string) => void
}

const EXTERNAL_URL_RE = /^(https?:|mailto:)/i

/** Same document as the app entry: same origin for http(s), same file for file://. */
export function isAppDocumentUrl(url: string, appUrl: string): boolean {
  try {
    const target = new URL(url)
    const app = new URL(appUrl)
    if (app.protocol === 'file:') return target.protocol === 'file:' && target.pathname === app.pathname
    return target.origin === app.origin
  } catch {
    return false
  }
}

/**
 * The main window carries the privileged `dsGui` preload bridge. Any top-level
 * navigation away from the app (a clicked link in model output or a README, a
 * redirect, `window.open`) would hand that bridge to a foreign page, so keep the
 * window on the app document and send web links to the OS browser instead.
 */
export function installMainWindowNavigationGuards(
  contents: WebContents,
  { appUrl, openExternal }: MainWindowGuardOptions
): void {
  const handOff = (url: string): void => {
    if (EXTERNAL_URL_RE.test(url)) openExternal(url)
  }
  contents.on('will-navigate', (event, url) => {
    if (isAppDocumentUrl(url, appUrl)) return
    event.preventDefault()
    handOff(url)
  })
  contents.on('will-redirect', (event, url, _isInPlace, isMainFrame) => {
    if (!isMainFrame || isAppDocumentUrl(url, appUrl)) return
    event.preventDefault()
  })
  // Overrides the generic `web-contents-created` handler for this window only.
  contents.setWindowOpenHandler(({ url }) => {
    handOff(url)
    return { action: 'deny' }
  })
}
