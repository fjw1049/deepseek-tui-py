import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactElement } from 'react'
import type { BrowserBridgeCommand, BrowserBridgeTab } from '@shared/browser-bridge'
import { DEV_BROWSER_PARTITION } from '@shared/browser-bridge'
import { normalizeBrowseUrlInput } from '@shared/dev-preview-url'
import {
  BLANK_PAGE,
  activatePageTab,
  closePageTab,
  ensureBrowserSession,
  markPageReady,
  openPageTab,
  registerPageWebview,
  updatePageTab,
  useBrowserPagesStore,
  type PageTab,
  type PageWebview
} from '../store/browser-pages-store'

type NavigateEvent = Event & { url: string; isMainFrame?: boolean }
type FailEvent = Event & { errorCode: number; errorDescription: string; isMainFrame: boolean }

const PAUSE_MEDIA = "for (const media of document.querySelectorAll('video, audio')) { try { media.pause() } catch {} }"

function samePage(a: string, b: string): boolean {
  try {
    const left = new URL(a), right = new URL(b)
    return left.origin === right.origin && left.pathname === right.pathname
  } catch { return false }
}

/** One persistent guest per tab; `src` is only the first load, later loads use loadURL. */
function Page({ browserId, tab, shown, onReady }: {
  browserId: string; tab: PageTab; shown: boolean; onReady: (tabId: string, webContentsId: number | null) => void
}): ReactElement {
  const element = useRef<PageWebview | null>(null)
  const [initialUrl] = useState(tab.url)
  const ready = useRef(false)
  const visible = useRef(shown)
  visible.current = shown
  const attach = useCallback((node: HTMLElement | null) => {
    element.current = node as PageWebview | null
    registerPageWebview(tab.id, node as PageWebview | null)
  }, [tab.id])

  useEffect(() => {
    const webview = element.current
    if (!webview) return
    const current = (): PageTab | undefined =>
      useBrowserPagesStore.getState().sessions[browserId]?.tabs.find(item => item.id === tab.id)
    const onDomReady = (): void => {
      if (ready.current) return
      ready.current = true
      markPageReady(tab.id, true)
      try {
        // Tabs that load while hidden (often opened by the agent) stay quiet.
        webview.setAudioMuted(!visible.current)
        onReady(tab.id, webview.getWebContentsId())
      } catch { /* detached */ }
    }
    const onNavigate = (event: Event): void => {
      const navigation = event as NavigateEvent
      if (navigation.isMainFrame === false) return
      const url = navigation.url === BLANK_PAGE ? BLANK_PAGE : normalizeBrowseUrlInput(navigation.url) ?? navigation.url
      const previous = current()
      // The source file only describes the page it was opened as.
      const filePath = previous?.filePath && samePage(previous.url, url) ? previous.filePath : null
      updatePageTab(browserId, tab.id, { url, filePath, error: null })
    }
    const onTitle = (event: Event): void => updatePageTab(browserId, tab.id, { title: (event as Event & { title: string }).title })
    const onStart = (): void => updatePageTab(browserId, tab.id, { loading: true, error: null })
    const onStop = (): void => updatePageTab(browserId, tab.id, { loading: false })
    const onFail = (event: Event): void => {
      const failure = event as FailEvent
      if (!failure.isMainFrame || failure.errorCode === -3) return
      updatePageTab(browserId, tab.id, { loading: false, error: failure.errorDescription })
    }
    const listeners: Array<[string, (event: Event) => void]> = [
      ['dom-ready', onDomReady], ['did-navigate', onNavigate], ['did-navigate-in-page', onNavigate],
      ['page-title-updated', onTitle], ['did-start-loading', onStart], ['did-stop-loading', onStop], ['did-fail-load', onFail]
    ]
    listeners.forEach(([name, listener]) => webview.addEventListener(name, listener))
    return () => listeners.forEach(([name, listener]) => webview.removeEventListener(name, listener))
  }, [browserId, tab.id, onReady])

  useEffect(() => {
    if (!ready.current) return
    try {
      element.current?.setAudioMuted(!shown)
      // Hidden tabs stop playing media; only the shown one should use the decoder.
      if (!shown) void element.current?.executeJavaScript(PAUSE_MEDIA).catch(() => {})
    } catch { /* detached */ }
  }, [shown])

  useEffect(() => () => { markPageReady(tab.id, false); onReady(tab.id, null) }, [tab.id, onReady])

  return <webview ref={attach} src={initialUrl}
    // React writes boolean attributes on custom elements only as strings.
    allowpopups={'true' as unknown as boolean}
    partition={DEV_BROWSER_PARTITION}
    webpreferences="contextIsolation=yes,nodeIntegration=no,sandbox=yes"
    className="flex h-full w-full bg-white" />
}

/**
 * Hosts every Workbench browser tab beneath the right panel. The visible tab sits under
 * the panel's transparent page area; other tabs stay painted but transparent, so the
 * runtime can keep working (and capturing) while the panel is hidden.
 */
export function BrowserPageLayer(): ReactElement {
  const sessions = useBrowserPagesStore(state => state.sessions)
  const display = useBrowserPagesStore(state => state.display)
  const [contents, setContents] = useState<Record<string, number>>({})
  const parkedSize = useRef({ width: 960, height: 720 })
  if (display) parkedSize.current = { width: display.rect.width, height: display.rect.height }
  const onReady = useCallback((tabId: string, id: number | null) => {
    setContents(current => {
      if (id === null) { if (!(tabId in current)) return current; const { [tabId]: _, ...rest } = current; return rest }
      return current[tabId] === id ? current : { ...current, [tabId]: id }
    })
  }, [])

  const announced = useRef<Record<string, string>>({})
  useEffect(() => {
    const bridge = window.dsGui?.browserBridge
    if (!bridge) return
    for (const [browserId, session] of Object.entries(sessions)) {
      const tabs: BrowserBridgeTab[] = session.tabs.filter(tab => contents[tab.id]).map(tab => ({
        tabId: tab.id, webContentsId: contents[tab.id]!, active: tab.id === session.activeTabId,
        visible: display?.browserId === browserId && tab.id === session.activeTabId
      }))
      const key = JSON.stringify(tabs)
      if (announced.current[browserId] === key) continue
      announced.current[browserId] = key
      void bridge.setTabs(browserId, tabs).catch(() => { delete announced.current[browserId] })
    }
  }, [sessions, contents, display?.browserId])

  useEffect(() => window.dsGui?.browserBridge?.onCommand((requestId: string, command: BrowserBridgeCommand) => {
    const reply = (ok: boolean, extra: { tabId?: string; error?: string } = {}): void => {
      void window.dsGui.browserBridge.reply(requestId, { ok, ...extra })
    }
    if (command.kind === 'open') { ensureBrowserSession(command.browserId); reply(true); return }
    if (command.kind === 'create') { reply(true, { tabId: openPageTab(command.browserId, command.url) }); return }
    const done = command.kind === 'activate' ? activatePageTab(command.browserId, command.tabId)
      : closePageTab(command.browserId, command.tabId)
    reply(done, done ? {} : { error: 'Tab no longer exists' })
  }), [])

  return <div className="ds-browser-page-layer" aria-hidden={!display}>
    {Object.entries(sessions).flatMap(([browserId, session]) => session.tabs.map(tab => {
      const shown = display?.browserId === browserId && tab.id === session.activeTabId
      const style: CSSProperties = shown ? { ...display!.rect }
        : { top: 0, right: 0, width: parkedSize.current.width, height: parkedSize.current.height }
      return <div key={tab.id} className={`ds-browser-page${shown ? ' is-shown' : ''}`} style={style}>
        <Page browserId={browserId} tab={tab} shown={shown} onReady={onReady} />
      </div>
    }))}
  </div>
}
