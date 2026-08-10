import type { FormEvent, ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  ArrowRight,
  Bug,
  Camera,
  CircleStop,
  ExternalLink,
  Globe2,
  Loader2,
  Plus,
  Radar,
  RefreshCw,
  Send,
  X
} from 'lucide-react'
import type { ChatBlock } from '../agent/types'
import {
  DEFAULT_DEV_PREVIEW_URL,
  isLocalPreviewUrl,
  normalizeBrowseUrlInput
} from '@shared/dev-preview-url'
import { isHtmlPreviewPath } from '@shared/html-preview'
import {
  extractDetectedDevPreviewUrls,
  formatDevPreviewUrlLabel
} from '../lib/dev-preview-detection'
import {
  PREVIEW_AUTO_FOLLOW_STORAGE_KEY,
  createTab,
  formatAddressInput,
  reduceCloseTab,
  reduceOpenOrFocusUrl,
  resolveAutoFollow,
  selectDevBrowserView,
  tabLabel,
  updateTabById,
  type PreviewTab
} from '../lib/dev-browser-tabs'
import {
  PREVIEW_PICK_CONSOLE_PREFIX,
  buildPreviewPickerCleanupScript,
  buildPreviewPickerInjectScript,
  extractWebviewConsoleMessage,
  parsePreviewPickConsoleMessage,
  type PreviewElementPick
} from '../lib/preview-element-picker'
import { localizeDevBrowserScreenshotError } from '../lib/dev-browser-screenshot-errors'

type DevWebviewTag = HTMLElement & {
  canGoBack(): boolean
  canGoForward(): boolean
  getURL(): string
  getWebContentsId(): number
  goBack(): void
  goForward(): void
  loadURL(url: string): Promise<void>
  openDevTools(): void
  reloadIgnoringCache(): void
  stop(): void
  setAudioMuted(muted: boolean): void
  executeJavaScript(code: string): Promise<unknown>
}

/** Synara-style window + cursor icon for element pick / annotate mode. */
function BrowserWindowCursorIcon({ className }: { className?: string }): ReactElement {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
    >
      <path d="M5.75 4C3.67893 4 2 5.67893 2 7.75V17.25C2 19.3211 3.67893 21 5.75 21H12.25C12.6642 21 13 20.6642 13 20.25C13 19.8358 12.6642 19.5 12.25 19.5H5.75C4.50736 19.5 3.5 18.4926 3.5 17.25V7.75C3.5 6.50736 4.50736 5.5 5.75 5.5H18.25C19.4926 5.5 20.5 6.50736 20.5 7.75V12.25C20.5 12.6642 20.8358 13 21.25 13C21.6642 13 22 12.6642 22 12.25V7.75C22 5.67893 20.3211 4 18.25 4H5.75Z" />
      <path d="M6.5 9.5C5.94772 9.5 5.5 9.05228 5.5 8.5C5.5 7.94772 5.94772 7.5 6.5 7.5C7.05228 7.5 7.5 7.94772 7.5 8.5C7.5 9.05228 7.05228 9.5 6.5 9.5Z" />
      <path d="M14.4697 14.4697C14.6661 14.2732 14.9551 14.2015 15.2206 14.2832L22.2206 16.437C22.5136 16.5272 22.7222 16.7865 22.7475 17.092C22.7727 17.3975 22.6096 17.6876 22.3354 17.8247L19.3283 19.3283L17.8247 22.3354C17.6876 22.6096 17.3975 22.7727 17.092 22.7475C16.7865 22.7222 16.5272 22.5136 16.437 22.2206L14.2832 15.2206C14.2015 14.9551 14.2732 14.6661 14.4697 14.4697Z" />
      <path d="M10 9.5C9.44772 9.5 9 9.05228 9 8.5C9 7.94772 9.44772 7.5 10 7.5C10.5523 7.5 11 7.94772 11 8.5C11 9.05228 10.5523 9.5 10 9.5Z" />
      <path d="M13.5 9.5C12.9477 9.5 12.5 9.05228 12.5 8.5C12.5 7.94772 12.9477 7.5 13.5 7.5C14.0523 7.5 14.5 7.94772 14.5 8.5C14.5 9.05228 14.0523 9.5 13.5 9.5Z" />
    </svg>
  )
}

/** Pause in-page media so background/hidden guests stop decoding video frames. */
function pauseGuestMedia(webview: DevWebviewTag): void {
  // executeJavaScript throws synchronously when the guest is not attached /
  // dom-ready yet (e.g. switching to a newly opened preview tab). .catch()
  // alone cannot prevent the React crash.
  try {
    const pending = webview.executeJavaScript(
      `(() => {
        for (const el of document.querySelectorAll('video, audio')) {
          try { el.pause() } catch {}
        }
      })()`
    )
    if (pending && typeof (pending as Promise<unknown>).catch === 'function') {
      void (pending as Promise<unknown>).catch(() => {
        /* guest may be mid-navigation */
      })
    }
  } catch {
    /* webview not attached / not dom-ready yet */
  }
}

type WebviewNavigateEvent = Event & {
  url: string
}

type WebviewFailLoadEvent = Event & {
  errorCode: number
  errorDescription: string
  isMainFrame: boolean
}

type WebviewTitleEvent = Event & {
  title: string
}

function readStoredAutoFollow(): boolean {
  try {
    return resolveAutoFollow(window.localStorage.getItem(PREVIEW_AUTO_FOLLOW_STORAGE_KEY))
  } catch {
    return false
  }
}

function persistAutoFollow(value: boolean): void {
  try {
    window.localStorage.setItem(PREVIEW_AUTO_FOLLOW_STORAGE_KEY, String(value))
  } catch {
    /* ignore persistence failures */
  }
}

type LoadOptions = {
  keepAutoFollow?: boolean
}

type DevBrowserWebviewProps = {
  tabId: string
  url: string
  registerWebview: (tabId: string, webview: DevWebviewTag | null) => void
  onNavigate: (tabId: string, url: string) => void
  onTitle: (tabId: string, title: string) => void
  onLoadingChange: (tabId: string, loading: boolean) => void
  onFailLoad: (tabId: string, description: string) => void
  onConsoleMessage: (tabId: string, message: string) => void
  onDomReadyChange: (tabId: string, ready: boolean) => void
}

/**
 * One persistent webview per tab. The `src` attribute is fixed to the URL the
 * tab was created with (only used for the very first load); every later load
 * goes through `loadURL` so in-page navigation state never echoes back into
 * the src attribute and triggers a full reload (which also broke SPA routes).
 */
function DevBrowserWebview({
  tabId,
  url,
  registerWebview,
  onNavigate,
  onTitle,
  onLoadingChange,
  onFailLoad,
  onConsoleMessage,
  onDomReadyChange
}: DevBrowserWebviewProps): ReactElement {
  const webviewRef = useRef<DevWebviewTag | null>(null)
  const initialUrlRef = useRef(url)
  // URL the guest is at or loading toward; navigation events keep it in sync
  // so the load effect below never re-loads what the page already navigated to.
  const loadedUrlRef = useRef<string | null>(url)

  useEffect(() => {
    const webview = webviewRef.current
    if (!webview) return
    if (loadedUrlRef.current === url) return
    try {
      onDomReadyChange(tabId, false)
      const pending = webview.loadURL(url)
      if (pending && typeof pending.catch === 'function') {
        void pending.catch(() => {
          /* load failures surface via did-fail-load */
        })
      }
      loadedUrlRef.current = url
    } catch {
      /* webview not attached / not dom-ready yet */
    }
  }, [onDomReadyChange, tabId, url])

  useEffect(() => {
    const webview = webviewRef.current
    if (!webview) return

    const handleStartLoading = (): void => {
      onDomReadyChange(tabId, false)
      onLoadingChange(tabId, true)
    }
    const handleStopLoading = (): void => {
      onLoadingChange(tabId, false)
      // Stop-loading is a reliable "guest can run JS" signal when we missed
      // the one-shot dom-ready (Strict Mode remount / late listener attach).
      onDomReadyChange(tabId, true)
    }
    const handleDomReady = (): void => onDomReadyChange(tabId, true)
    const handleNavigate: EventListener = (event): void => {
      const currentUrl = normalizeBrowseUrlInput((event as WebviewNavigateEvent).url)
      if (!currentUrl) return
      loadedUrlRef.current = currentUrl
      onNavigate(tabId, currentUrl)
    }
    const handleFailLoad: EventListener = (event): void => {
      const failEvent = event as WebviewFailLoadEvent
      if (!failEvent.isMainFrame || failEvent.errorCode === -3) return
      onFailLoad(tabId, failEvent.errorDescription)
    }
    const handleTitle: EventListener = (event): void => {
      onTitle(tabId, (event as WebviewTitleEvent).title)
    }
    const handleConsoleMessage: EventListener = (event): void => {
      const message = extractWebviewConsoleMessage(event)
      // Cheap gate: ignore unrelated guest logs before crossing into React state.
      if (!message || !message.includes(PREVIEW_PICK_CONSOLE_PREFIX)) return
      onConsoleMessage(tabId, message)
    }

    webview.addEventListener('did-start-loading', handleStartLoading)
    webview.addEventListener('did-stop-loading', handleStopLoading)
    webview.addEventListener('dom-ready', handleDomReady)
    webview.addEventListener('did-navigate', handleNavigate)
    webview.addEventListener('did-navigate-in-page', handleNavigate)
    webview.addEventListener('did-fail-load', handleFailLoad)
    webview.addEventListener('page-title-updated', handleTitle)
    webview.addEventListener('console-message', handleConsoleMessage)

    // Probe: if the page already finished before listeners attached, mark ready.
    try {
      const probe = webview.executeJavaScript('true')
      if (probe && typeof probe.then === 'function') {
        void probe
          .then(() => onDomReadyChange(tabId, true))
          .catch(() => {
            /* still loading — wait for dom-ready / did-stop-loading */
          })
      }
    } catch {
      /* not attached yet */
    }

    return () => {
      // Do NOT clear ready here: Strict Mode remount would drop the flag after
      // the only dom-ready already fired, leaving magic-pen inject stuck.
      webview.removeEventListener('did-start-loading', handleStartLoading)
      webview.removeEventListener('did-stop-loading', handleStopLoading)
      webview.removeEventListener('dom-ready', handleDomReady)
      webview.removeEventListener('did-navigate', handleNavigate)
      webview.removeEventListener('did-navigate-in-page', handleNavigate)
      webview.removeEventListener('did-fail-load', handleFailLoad)
      webview.removeEventListener('page-title-updated', handleTitle)
      webview.removeEventListener('console-message', handleConsoleMessage)
    }
  }, [
    tabId,
    onNavigate,
    onTitle,
    onLoadingChange,
    onFailLoad,
    onConsoleMessage,
    onDomReadyChange
  ])

  return (
    <webview
      ref={(element) => {
        webviewRef.current = element as DevWebviewTag | null
        registerWebview(tabId, element as DevWebviewTag | null)
      }}
      src={initialUrlRef.current}
      // React 19 refuses to write BOOLEAN attributes on non-standard elements
      // (runtime warning, attribute dropped), while its built-in webview JSX
      // typing declares allowpopups?: boolean. Pass the string form through
      // the boolean-typed prop so `allowpopups="true"` actually lands in the
      // DOM and window.open works in the guest.
      allowpopups={'true' as unknown as boolean}
      partition="persist:deepseek-dev-browser"
      webpreferences="contextIsolation=yes,nodeIntegration=no,sandbox=yes"
      className="flex h-full w-full bg-white"
    />
  )
}

export function DevBrowserPanel({
  blocks,
  preferredUrl,
  preferredFilePath = null,
  externalError,
  onPreferredUrlConsumed,
  onExternalErrorConsumed,
  onPreviewPick,
  className
}: {
  blocks: ChatBlock[]
  preferredUrl?: string | null
  preferredFilePath?: string | null
  externalError?: string | null
  onPreferredUrlConsumed?: () => void
  onExternalErrorConsumed?: () => void
  onPreviewPick?: (pick: PreviewElementPick) => void
  className?: string
}): ReactElement {
  const { t } = useTranslation('common')
  const webviewRefs = useRef(new Map<string, DevWebviewTag>())
  const iframeLoadedUrlRef = useRef<string | null>(null)
  const preferredUrlRef = useRef<string | null>(null)
  const detectedUrls = useMemo(() => extractDetectedDevPreviewUrls(blocks), [blocks])
  const latestDetectedUrl = detectedUrls[0] ?? null
  const useElectronWebview = typeof window.dsGui?.openExternal === 'function'

  // Preferred may be a local workspace/HTML preview or a user-opened browse URL.
  const normalizedPreferredUrl = useMemo(
    () => (preferredUrl ? normalizeBrowseUrlInput(preferredUrl) : null),
    [preferredUrl]
  )

  const [tabs, setTabs] = useState<PreviewTab[]>(() => [createTab(null)])
  const [activeTabId, setActiveTabId] = useState(() => tabs[0]!.id)
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? tabs[0]!
  const activeUrl = activeTab?.url ?? null

  // Mirrors let webview event callbacks (bound once per tab) read the current
  // tab state without re-binding listeners on every navigation.
  const activeTabIdRef = useRef(activeTabId)
  const tabsRef = useRef(tabs)
  useEffect(() => {
    activeTabIdRef.current = activeTabId
    tabsRef.current = tabs
  })
  // URLs auto-follow already opened; survives tab navigation (unlike a
  // tabs.some(url) guard) so redirects don't re-trigger opens.
  const autoFollowedUrlsRef = useRef(new Set<string>())

  const [draftUrl, setDraftUrl] = useState('')
  const [autoFollow, setAutoFollow] = useState(readStoredAutoFollow)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [canGoBack, setCanGoBack] = useState(false)
  const [canGoForward, setCanGoForward] = useState(false)
  const [iframeBackStack, setIframeBackStack] = useState<string[]>([])
  const [iframeForwardStack, setIframeForwardStack] = useState<string[]>([])
  const [iframeReloadNonce, setIframeReloadNonce] = useState(0)
  const [inspectMode, setInspectMode] = useState(false)
  const inspectModeRef = useRef(false)
  const [screenshotNotice, setScreenshotNotice] = useState<string | null>(null)
  const [screenshotNoticeTone, setScreenshotNoticeTone] = useState<'info' | 'success' | 'error'>(
    'info'
  )
  const screenshotNoticeTimerRef = useRef<number | null>(null)
  const copyingScreenshotRef = useRef(false)
  const [copyingScreenshot, setCopyingScreenshot] = useState(false)
  /** Tabs where the picker script was successfully requested (cleanup only these). */
  const pickerInjectedTabsRef = useRef(new Set<string>())
  /** Tabs that have emitted Electron `dom-ready` (safe for executeJavaScript). */
  const webviewDomReadyRef = useRef(new Set<string>())
  const canNavigateBack = useElectronWebview ? canGoBack : iframeBackStack.length > 0
  const canNavigateForward = useElectronWebview ? canGoForward : iframeForwardStack.length > 0
  const activeFilePath = activeTab?.filePath?.trim() || ''
  // Magic pen only for workspace static HTML opened with source path meta —
  // hide (don't just disable) on Vite/dev-server/public browse tabs.
  const canInspect =
    useElectronWebview &&
    Boolean(activeUrl && activeFilePath && isHtmlPreviewPath(activeFilePath))

  useEffect(() => {
    inspectModeRef.current = inspectMode
  }, [inspectMode])

  useEffect(() => {
    return () => {
      if (screenshotNoticeTimerRef.current !== null) {
        window.clearTimeout(screenshotNoticeTimerRef.current)
      }
    }
  }, [])

  const updateActiveTab = useCallback((patch: Partial<PreviewTab>): void => {
    const tabId = activeTabIdRef.current
    setTabs((current) => updateTabById(current, tabId, patch))
  }, [])

  const registerWebview = useCallback((tabId: string, webview: DevWebviewTag | null): void => {
    if (webview) webviewRefs.current.set(tabId, webview)
    else {
      webviewRefs.current.delete(tabId)
      pickerInjectedTabsRef.current.delete(tabId)
      webviewDomReadyRef.current.delete(tabId)
    }
  }, [])

  const syncActiveNavigationState = useCallback((tabId: string): void => {
    const webview = webviewRefs.current.get(tabId)
    if (!webview || !webviewDomReadyRef.current.has(tabId)) return
    try {
      setCanGoBack(webview.canGoBack())
      setCanGoForward(webview.canGoForward())
    } catch {
      /* webview may not be attached yet */
    }
  }, [])

  const runGuestScript = useCallback((tabId: string, code: string): boolean => {
    const webview = webviewRefs.current.get(tabId)
    if (!webview) return false
    // Soft gate: prefer the ready set, but still attempt executeJavaScript —
    // missing a one-shot dom-ready must not permanently disable magic pen.
    // Sync throws are caught; success marks the tab ready.
    try {
      const pending = webview.executeJavaScript(code)
      webviewDomReadyRef.current.add(tabId)
      if (pending && typeof (pending as Promise<unknown>).catch === 'function') {
        void (pending as Promise<unknown>).catch(() => {
          /* guest may be mid-navigation */
        })
      }
      return true
    } catch {
      return false
    }
  }, [])

  const cleanupPickerOnTab = useCallback(
    (tabId: string): void => {
      // Always run the guest cleanup script — do not gate on the inject set.
      // did-start-loading used to clear the set without disposing, so a later
      // "turn Inspect off" early-returned and left capture listeners armed.
      pickerInjectedTabsRef.current.delete(tabId)
      runGuestScript(tabId, buildPreviewPickerCleanupScript())
    },
    [runGuestScript]
  )

  const injectPickerOnTab = useCallback(
    (tabId: string): void => {
      // Hard gate: never re-arm after Inspect was turned off (stop-loading /
      // dom-ready can race past a stale inspectModeRef).
      if (!inspectModeRef.current) return
      if (!runGuestScript(tabId, buildPreviewPickerInjectScript())) return
      if (!inspectModeRef.current) {
        // Toggled off while executeJavaScript was queued — disarm immediately.
        runGuestScript(tabId, buildPreviewPickerCleanupScript())
        pickerInjectedTabsRef.current.delete(tabId)
        return
      }
      pickerInjectedTabsRef.current.add(tabId)
    },
    [runGuestScript]
  )

  const handleWebviewDomReadyChange = useCallback(
    (tabId: string, ready: boolean): void => {
      if (ready) {
        webviewDomReadyRef.current.add(tabId)
        // Magic pen may have been toggled before the guest finished loading.
        if (inspectModeRef.current && tabId === activeTabIdRef.current) {
          injectPickerOnTab(tabId)
        }
        if (tabId === activeTabIdRef.current) syncActiveNavigationState(tabId)
        return
      }
      // Disarm before dropping tracking — same-document start-loading must not
      // orphan capture listeners that a later cleanup would skip.
      cleanupPickerOnTab(tabId)
      webviewDomReadyRef.current.delete(tabId)
    },
    [cleanupPickerOnTab, injectPickerOnTab, syncActiveNavigationState]
  )

  const stopInspectMode = useCallback(
    (tabId: string = activeTabIdRef.current): void => {
      // Sync ref immediately so stop-loading / dom-ready cannot re-inject
      // between setState and the inspectMode effect flush.
      inspectModeRef.current = false
      setInspectMode(false)
      cleanupPickerOnTab(tabId)
    },
    [cleanupPickerOnTab]
  )

  const handleWebviewNavigate = useCallback(
    (tabId: string, url: string): void => {
      // Full navigations drop the injected picker. Keep Inspect armed and
      // re-inject on the next dom-ready / stop-loading instead of forcing off
      // (initial did-navigate used to cancel magic pen immediately).
      if (inspectModeRef.current) cleanupPickerOnTab(tabId)
      setTabs((current) => updateTabById(current, tabId, { url }))
      if (tabId !== activeTabIdRef.current) return
      setDraftUrl(formatAddressInput(url))
      setLoadError(null)
      syncActiveNavigationState(tabId)
    },
    [cleanupPickerOnTab, syncActiveNavigationState]
  )

  const handleWebviewTitle = useCallback((tabId: string, title: string): void => {
    setTabs((current) => updateTabById(current, tabId, { title }))
  }, [])

  const handleWebviewLoadingChange = useCallback(
    (tabId: string, nextLoading: boolean): void => {
      if (tabId !== activeTabIdRef.current) return
      setLoading(nextLoading)
      if (nextLoading) setLoadError(null)
      else {
        syncActiveNavigationState(tabId)
        // Inspect may have been toggled before dom-ready; retry inject once loaded.
        if (inspectModeRef.current) injectPickerOnTab(tabId)
      }
    },
    [injectPickerOnTab, syncActiveNavigationState]
  )

  const handleWebviewFailLoad = useCallback(
    (tabId: string, description: string): void => {
      if (tabId !== activeTabIdRef.current) return
      setLoading(false)
      setLoadError(description || t('browserLoadFailed'))
      syncActiveNavigationState(tabId)
    },
    [syncActiveNavigationState, t]
  )

  const handleWebviewConsoleMessage = useCallback(
    (tabId: string, message: string): void => {
      const parsed = parsePreviewPickConsoleMessage(message)
      if (!parsed) return
      if (parsed.type === 'cancel') {
        stopInspectMode(tabId)
        return
      }
      // Inspect off: ignore stale guest picks (orphaned listeners / late console).
      if (!inspectModeRef.current) return
      if (tabId !== activeTabIdRef.current) return
      const filePath =
        tabsRef.current.find((tab) => tab.id === tabId)?.filePath?.trim() || ''
      // Keep Inspect armed so the user can append more chips; Esc / toggle
      // still call stopInspectMode. Missing filePath is a hard gate — bail
      // without clearing Composer chips.
      if (!filePath) return
      onPreviewPick?.({ ...parsed.payload, filePath })
    },
    [onPreviewPick, stopInspectMode]
  )

  const openOrFocusUrl = useCallback(
    (
      url: string,
      options: { title?: string; select?: boolean; filePath?: string | null } = {}
    ): void => {
      const normalized = normalizeBrowseUrlInput(url)
      if (!normalized) return
      // Read the latest state via refs (updated every commit) so the reducer
      // stays outside the setTabs updater — side effects inside updaters are
      // double-invoked under StrictMode.
      const current = tabsRef.current
      const next = reduceOpenOrFocusUrl(
        { tabs: current, activeTabId: activeTabIdRef.current },
        normalized,
        options
      )
      if (next.tabs !== current) setTabs(next.tabs)
      if (next.activeTabId !== activeTabIdRef.current) setActiveTabId(next.activeTabId)
      if (options.select !== false) {
        setLoadError(null)
        setLoading(true)
        setDraftUrl(formatAddressInput(normalized))
        stopInspectMode()
      }
      setIframeBackStack([])
      setIframeForwardStack([])
    },
    [stopInspectMode]
  )

  useEffect(() => {
    persistAutoFollow(autoFollow)
  }, [autoFollow])

  // Reset toolbar/nav state only when switching tabs. In-page navigation is
  // reflected by the webview event handlers instead, so it must not wipe
  // canGoBack/canGoForward here.
  useEffect(() => {
    const tabId = activeTabId
    inspectModeRef.current = false
    setInspectMode(false)
    const tab = tabsRef.current.find((candidate) => candidate.id === tabId)
    const url = tab?.url ?? null
    setDraftUrl(formatAddressInput(url))
    setLoadError(null)
    setCanGoBack(false)
    setCanGoForward(false)
    setIframeBackStack([])
    setIframeForwardStack([])
    setLoading(Boolean(url))
    // The newly focused tab's webview kept its own history while hidden —
    // restore the real nav state from it.
    const webview = webviewRefs.current.get(tabId)
    if (webview && webviewDomReadyRef.current.has(tabId)) {
      try {
        setCanGoBack(webview.canGoBack())
        setCanGoForward(webview.canGoForward())
        const currentUrl = normalizeBrowseUrlInput(webview.getURL())
        if (currentUrl) setDraftUrl(formatAddressInput(currentUrl))
      } catch {
        /* webview may not be attached yet */
      }
    }
    // Cleanup the tab we leave so a lingering overlay never sticks on a
    // background guest after Inspect was active.
    return () => {
      cleanupPickerOnTab(tabId)
    }
  }, [activeTabId, cleanupPickerOnTab])

  // Inactive guests used to stay `display:none` while still decoding page
  // media. Chromium then logs ffmpeg_common "Unsupported pixel format: -1"
  // (AV_PIX_FMT_NONE) for zero-sized / background video frames. Keep full
  // geometry via absolute stacking, mute + pause media on background tabs.
  useEffect(() => {
    for (const [tabId, webview] of webviewRefs.current.entries()) {
      const active = tabId === activeTabId
      const ready = webviewDomReadyRef.current.has(tabId)
      try {
        webview.setAudioMuted(!active)
      } catch {
        /* webview may not expose muting yet */
      }
      // Never call executeJavaScript on a guest that has not reached dom-ready
      // (switching to a freshly opened preview tab used to crash here).
      if (!active && ready) pauseGuestMedia(webview)
    }
  }, [activeTabId, tabs])

  useEffect(() => {
    if (!externalError) return
    setLoadError(externalError)
    setLoading(false)
    onExternalErrorConsumed?.()
  }, [externalError, onExternalErrorConsumed])

  useEffect(() => {
    if (!normalizedPreferredUrl) {
      preferredUrlRef.current = null
      return
    }
    if (preferredUrlRef.current === normalizedPreferredUrl) return
    preferredUrlRef.current = normalizedPreferredUrl
    setAutoFollow(false)
    const filePath = preferredFilePath?.trim() || null
    openOrFocusUrl(normalizedPreferredUrl, { filePath })
    onPreferredUrlConsumed?.()
  }, [normalizedPreferredUrl, onPreferredUrlConsumed, openOrFocusUrl, preferredFilePath])

  useEffect(() => {
    if (!inspectMode) return
    if (!canInspect) {
      stopInspectMode(activeTabId)
      return
    }
    injectPickerOnTab(activeTabId)
    return () => {
      cleanupPickerOnTab(activeTabId)
    }
  }, [
    activeTabId,
    canInspect,
    cleanupPickerOnTab,
    injectPickerOnTab,
    inspectMode,
    stopInspectMode
  ])

  useEffect(() => {
    if (!canInspect && inspectMode) stopInspectMode()
  }, [canInspect, inspectMode, stopInspectMode])

  useEffect(() => {
    // Auto-follow stays local-only so agent-mentioned public links never hijack
    // preview. Guard on a ref-set of already-followed URLs (not on tab state):
    // a tab navigating away from the detected URL (redirect, in-page nav) must
    // not make the effect open it again on every navigation — that cascading
    // effect → setTabs → effect chain is what tripped "Maximum update depth".
    if (!autoFollow || !latestDetectedUrl) return
    if (!isLocalPreviewUrl(latestDetectedUrl)) return
    const normalized = normalizeBrowseUrlInput(latestDetectedUrl)
    if (!normalized) return
    if (autoFollowedUrlsRef.current.has(normalized)) return
    autoFollowedUrlsRef.current.add(normalized)
    openOrFocusUrl(normalized, { select: tabsRef.current.every((tab) => !tab.url) })
  }, [autoFollow, latestDetectedUrl, openOrFocusUrl])

  // Main process denies window.open inside webview guests and navigates the
  // same guest instead (target=_blank behaves like a normal browser tab, so
  // the back button covers returning).
  useEffect(() => {
    if (useElectronWebview || !activeUrl) return
    // Public https can't be reliably embedded in iframe — skip load timeout.
    if (!isLocalPreviewUrl(activeUrl)) {
      setLoading(false)
      setLoadError(null)
      return
    }
    iframeLoadedUrlRef.current = null
    setLoading(true)
    setLoadError(null)

    const timeout = window.setTimeout(() => {
      if (iframeLoadedUrlRef.current === activeUrl) return
      setLoading(false)
      setLoadError(t('browserLoadFailed'))
    }, 10000)

    return () => window.clearTimeout(timeout)
  }, [activeUrl, iframeReloadNonce, t, useElectronWebview])

  const resetNavState = (): void => {
    setCanGoBack(false)
    setCanGoForward(false)
    setIframeBackStack([])
    setIframeForwardStack([])
  }

  const addTab = (): void => {
    const next = createTab(null)
    setAutoFollow(false)
    setTabs((current) => [...current, next])
    setActiveTabId(next.id)
    setDraftUrl('')
    setLoadError(null)
    setLoading(false)
    resetNavState()
  }

  const closeTab = (tabId: string): void => {
    const result = reduceCloseTab({ tabs, activeTabId }, tabId)
    if (result.tabs === tabs) return
    setTabs(result.tabs)
    if (result.clearedSoleTab) {
      setDraftUrl('')
      setLoadError(null)
      setLoading(false)
      resetNavState()
      return
    }
    if (result.activeTabId !== activeTabId) {
      // The [activeTabId] effect resets draft/loading/nav state for the
      // fallback tab and restores history from its live webview.
      setActiveTabId(result.activeTabId)
    }
  }

  const loadUrl = (value: string, options: LoadOptions = {}): void => {
    const normalized = normalizeBrowseUrlInput(value)
    if (!normalized) {
      setLoadError(t('browserInvalidUrl'))
      return
    }
    if (!options.keepAutoFollow) setAutoFollow(false)
    stopInspectMode()
    setLoadError(null)
    setLoading(true)
    if (!useElectronWebview && activeUrl && normalized !== activeUrl) {
      setIframeBackStack((stack) => [...stack, activeUrl].slice(-30))
      setIframeForwardStack([])
    }
    // Omnibox navigations have no workspace source meta.
    updateActiveTab({ url: normalized, title: '', filePath: null })
    setDraftUrl(formatAddressInput(normalized))
  }

  const toggleInspectMode = (): void => {
    if (!canInspect) return
    if (inspectMode) {
      stopInspectMode()
      return
    }
    setInspectMode(true)
  }

  const submitUrl = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault()
    loadUrl(draftUrl)
  }

  const activeWebview = (): DevWebviewTag | null =>
    webviewRefs.current.get(activeTabIdRef.current) ?? null

  const reload = (): void => {
    if (!activeUrl) return
    if (!useElectronWebview) {
      iframeLoadedUrlRef.current = null
      setIframeReloadNonce((nonce) => nonce + 1)
      setLoading(true)
      setLoadError(null)
      return
    }
    setLoading(true)
    setLoadError(null)
    try {
      activeWebview()?.reloadIgnoringCache()
    } catch {
      loadUrl(activeUrl, { keepAutoFollow: true })
    }
  }

  const stopLoading = (): void => {
    try {
      activeWebview()?.stop()
    } catch {
      /* ignore unavailable webview */
    }
    setLoading(false)
  }

  const openDevTools = (): void => {
    try {
      activeWebview()?.openDevTools()
    } catch {
      /* ignore unavailable webview */
    }
  }

  const showScreenshotNotice = useCallback(
    (message: string, tone: 'info' | 'success' | 'error' = 'info', timeoutMs = 2_000): void => {
      setScreenshotNotice(message)
      setScreenshotNoticeTone(tone)
      if (screenshotNoticeTimerRef.current !== null) {
        window.clearTimeout(screenshotNoticeTimerRef.current)
      }
      screenshotNoticeTimerRef.current = window.setTimeout(() => {
        setScreenshotNotice(null)
        screenshotNoticeTimerRef.current = null
      }, timeoutMs)
    },
    []
  )

  const resolveScreenshotWebContentsId = useCallback(
    (tabId: string, webview: DevWebviewTag): number | null => {
      try {
        const webContentsId = webview.getWebContentsId()
        if (!Number.isFinite(webContentsId) || webContentsId <= 0) return null
        webviewDomReadyRef.current.add(tabId)
        return webContentsId
      } catch {
        return null
      }
    },
    []
  )

  const copyScreenshotToClipboard = useCallback(async (): Promise<void> => {
    if (!useElectronWebview || !activeUrl) {
      showScreenshotNotice(t('browserScreenshotNotReady'), 'error')
      return
    }
    if (copyingScreenshotRef.current) {
      showScreenshotNotice(t('browserScreenshotBusy'), 'info', 1_200)
      return
    }

    const tabId = activeTabIdRef.current
    const webview = activeWebview()
    if (!webview) {
      showScreenshotNotice(t('browserScreenshotNotReady'), 'error')
      return
    }

    const webContentsId = resolveScreenshotWebContentsId(tabId, webview)
    if (webContentsId === null) {
      showScreenshotNotice(t('browserScreenshotNotReady'), 'error')
      return
    }
    if (typeof window.dsGui?.copyDevBrowserScreenshotToClipboard !== 'function') {
      showScreenshotNotice(t('browserScreenshotNeedRestart'), 'error', 4_000)
      return
    }

    copyingScreenshotRef.current = true
    setCopyingScreenshot(true)
    showScreenshotNotice(t('browserScreenshotCopying'), 'info', 12_000)

    try {
      const result = await window.dsGui.copyDevBrowserScreenshotToClipboard(webContentsId)
      if (!result.ok) {
        showScreenshotNotice(
          localizeDevBrowserScreenshotError(result.message, t),
          'error',
          4_000
        )
        return
      }
      showScreenshotNotice(t('browserScreenshotCopied'), 'success')
    } catch (error) {
      showScreenshotNotice(
        localizeDevBrowserScreenshotError(
          error instanceof Error ? error.message : String(error),
          t
        ),
        'error',
        4_000
      )
    } finally {
      copyingScreenshotRef.current = false
      setCopyingScreenshot(false)
    }
  }, [
    activeUrl,
    resolveScreenshotWebContentsId,
    showScreenshotNotice,
    t,
    useElectronWebview
  ])

  const openExternalUrl = (url: string | null | undefined = activeUrl): void => {
    if (!url) return
    const normalized = normalizeBrowseUrlInput(url)
    if (!normalized) return
    if (typeof window.dsGui?.openExternal === 'function') {
      void window.dsGui.openExternal(normalized)
      return
    }
    window.open(normalized, '_blank', 'noopener,noreferrer')
  }

  const view = selectDevBrowserView(activeUrl, useElectronWebview)

  const goBack = (): void => {
    if (!useElectronWebview) {
      const previousUrl = iframeBackStack.at(-1)
      if (!previousUrl) return
      setIframeBackStack((stack) => stack.slice(0, -1))
      setIframeForwardStack((stack) => (activeUrl ? [activeUrl, ...stack] : stack).slice(0, 30))
      setLoadError(null)
      setLoading(true)
      updateActiveTab({ url: previousUrl })
      setDraftUrl(formatAddressInput(previousUrl))
      return
    }
    try {
      const webview = activeWebview()
      if (webview?.canGoBack()) webview.goBack()
    } catch {
      /* ignore unavailable webview navigation */
    }
  }

  const goForward = (): void => {
    if (!useElectronWebview) {
      const nextUrl = iframeForwardStack[0]
      if (!nextUrl) return
      setIframeForwardStack((stack) => stack.slice(1))
      setIframeBackStack((stack) => (activeUrl ? [...stack, activeUrl] : stack).slice(-30))
      setLoadError(null)
      setLoading(true)
      updateActiveTab({ url: nextUrl })
      setDraftUrl(formatAddressInput(nextUrl))
      return
    }
    try {
      const webview = activeWebview()
      if (webview?.canGoForward()) webview.goForward()
    } catch {
      /* ignore unavailable webview navigation */
    }
  }

  return (
    <aside className={`ds-tool-panel ds-no-drag flex min-h-0 flex-col ${className ?? ''}`}>
      <div className="ds-dev-browser__chrome shrink-0">
        <div className="ds-dev-browser__tabs">
          <div className="ds-dev-browser__tab-scroll">
            {tabs.map((tab) => {
              const active = tab.id === activeTabId
              const isSoleBlank = tabs.length === 1 && !tab.url
              return (
                <div
                  key={tab.id}
                  className={`ds-dev-browser__tab group${active ? ' ds-dev-browser__tab--active' : ''}`}
                >
                  <button
                    type="button"
                    onClick={() => setActiveTabId(tab.id)}
                    className="ds-dev-browser__tab-main"
                    title={tab.url ?? t('browserNewTab')}
                  >
                    <Globe2 className="ds-dev-browser__tab-icon" strokeWidth={1.75} aria-hidden />
                    <span className="ds-dev-browser__tab-label">
                      {tabLabel(tab, t('browserNewTab'))}
                    </span>
                  </button>
                  <button
                    type="button"
                    disabled={isSoleBlank}
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      closeTab(tab.id)
                    }}
                    className={`ds-dev-browser__tab-close${active ? ' is-visible' : ''}`}
                    aria-label={t('browserCloseTab')}
                    title={isSoleBlank ? t('browserCloseTabDisabled') : t('browserCloseTab')}
                  >
                    <X className="h-2.5 w-2.5" strokeWidth={2.2} />
                  </button>
                </div>
              )
            })}
          </div>
          <button
            type="button"
            onClick={addTab}
            className="ds-dev-browser__icon-btn"
            aria-label={t('browserNewTab')}
            title={t('browserNewTab')}
          >
            <Plus className="h-3.5 w-3.5" strokeWidth={1.9} />
          </button>
          <div className="ds-dev-browser__actions">
            {canInspect ? (
              <button
                type="button"
                onClick={toggleInspectMode}
                className={`ds-dev-browser__magic${inspectMode ? ' is-on' : ''}`}
                aria-label={t('browserInspect')}
                aria-pressed={inspectMode}
                title={t('browserInspectHint')}
              >
                <BrowserWindowCursorIcon className="ds-dev-browser__magic-icon h-3.5 w-3.5" />
              </button>
            ) : null}
            {useElectronWebview ? (
              <button
                type="button"
                onClick={() => void copyScreenshotToClipboard()}
                disabled={!activeUrl}
                aria-busy={copyingScreenshot}
                className={`ds-dev-browser__icon-btn${copyingScreenshot ? ' is-busy' : ''}`}
                aria-label={t('browserCopyScreenshot')}
                title={t('browserCopyScreenshot')}
              >
                {copyingScreenshot ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
                ) : (
                  <Camera className="h-3.5 w-3.5" strokeWidth={1.75} />
                )}
              </button>
            ) : null}
            <div className="ds-dev-browser__action-pill">
              <button
                type="button"
                onClick={() => openExternalUrl()}
                disabled={!activeUrl}
                className="ds-dev-browser__icon-btn"
                aria-label={t('browserOpenExternal')}
                title={t('browserOpenExternal')}
              >
                <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} />
              </button>
              {useElectronWebview ? (
                <button
                  type="button"
                  onClick={openDevTools}
                  disabled={!activeUrl}
                  className="ds-dev-browser__icon-btn"
                  aria-label={t('browserDevTools')}
                  title={t('browserDevTools')}
                >
                  <Bug className="h-3.5 w-3.5" strokeWidth={1.8} />
                </button>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => setAutoFollow((value) => !value)}
              className={`ds-dev-browser__follow${autoFollow ? ' is-on' : ''}`}
              aria-label={t('browserAutoFollow')}
              aria-pressed={autoFollow}
              title={t('browserAutoFollow')}
            >
              <Radar className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
          </div>
        </div>

        <form onSubmit={submitUrl} className="ds-dev-browser__toolbar">
          <div className="ds-dev-browser__nav">
            <button
              type="button"
              onClick={goBack}
              disabled={!canNavigateBack}
              className="ds-dev-browser__icon-btn"
              aria-label={t('browserBack')}
              title={t('browserBack')}
            >
              <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.9} />
            </button>
            <button
              type="button"
              onClick={goForward}
              disabled={!canNavigateForward}
              className="ds-dev-browser__icon-btn"
              aria-label={t('browserForward')}
              title={t('browserForward')}
            >
              <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.9} />
            </button>
            {loading && useElectronWebview && activeUrl ? (
              <button
                type="button"
                onClick={stopLoading}
                className="ds-dev-browser__icon-btn"
                aria-label={t('browserStop')}
                title={t('browserStop')}
              >
                <CircleStop className="h-3.5 w-3.5" strokeWidth={1.9} />
              </button>
            ) : (
              <button
                type="button"
                onClick={reload}
                disabled={!activeUrl}
                className="ds-dev-browser__icon-btn"
                aria-label={t('browserReload')}
                title={t('browserReload')}
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.9} />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.9} />
                )}
              </button>
            )}
          </div>

          <input
            value={draftUrl}
            onChange={(event) => setDraftUrl(event.target.value)}
            className="ds-dev-browser__omnibox"
            placeholder={t('browserAddressPlaceholder')}
            spellCheck={false}
          />

          <button
            type="submit"
            className="ds-dev-browser__icon-btn"
            aria-label={t('browserOpen')}
            title={t('browserOpen')}
          >
            <Send className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        </form>

        {screenshotNotice ? (
          <div
            className={`ds-dev-browser__screenshot-notice ds-dev-browser__screenshot-notice--${screenshotNoticeTone}`}
            role="status"
            aria-live="polite"
          >
            {screenshotNotice}
          </div>
        ) : null}

        {detectedUrls.length > 0 ? (
          <div className="ds-dev-browser__chips">
            {detectedUrls.map((url) => (
              <button
                key={url}
                type="button"
                onClick={() => {
                  setAutoFollow(false)
                  openOrFocusUrl(url)
                }}
                className="ds-dev-browser__chip"
                title={url}
              >
                {formatDevPreviewUrlLabel(url)}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {loadError ? (
        <div className="shrink-0 border-b border-red-200/70 bg-red-50/85 px-3 py-2 text-[11px] leading-5 text-red-800 dark:border-red-900/50 dark:bg-red-950/35 dark:text-red-100">
          {loadError}
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1 bg-white dark:bg-ds-canvas">
        {view === 'empty' ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
            <Globe2 className="h-8 w-8 text-ds-faint" strokeWidth={1.5} />
            <div className="text-[14px] font-medium text-ds-ink">{t('browserEmptyTitle')}</div>
            <div className="max-w-sm text-[12.5px] leading-5 text-ds-muted">
              {t('browserEmptyBody')}
            </div>
            <button
              type="button"
              onClick={() => loadUrl(DEFAULT_DEV_PREVIEW_URL)}
              className="mt-1 rounded-full bg-accent px-4 py-2 text-[12.5px] font-semibold text-white"
            >
              {t('browserOpenDefault')}
            </button>
          </div>
        ) : view === 'webview' ? (
          // Every tab keeps its webview mounted (inactive tabs stay in the
          // layout tree with full size — visibility/pointer only) so page
          // state, scroll and history survive switches. Avoid `display:none`:
          // it zero-sizes the guest compositor and aggravates Chromium media
          // decode noise (ffmpeg "Unsupported pixel format: -1").
          <div className="relative h-full w-full">
            {tabs.map((tab) =>
              tab.url ? (
                <div
                  key={tab.id}
                  className={
                    tab.id === activeTabId
                      ? 'absolute inset-0 z-10 h-full w-full'
                      : 'pointer-events-none invisible absolute inset-0 z-0 h-full w-full'
                  }
                  aria-hidden={tab.id !== activeTabId}
                >
                  <DevBrowserWebview
                    tabId={tab.id}
                    url={tab.url}
                    registerWebview={registerWebview}
                    onNavigate={handleWebviewNavigate}
                    onTitle={handleWebviewTitle}
                    onLoadingChange={handleWebviewLoadingChange}
                    onFailLoad={handleWebviewFailLoad}
                    onConsoleMessage={handleWebviewConsoleMessage}
                    onDomReadyChange={handleWebviewDomReadyChange}
                  />
                </div>
              ) : null
            )}
          </div>
        ) : view === 'iframe' && activeUrl ? (
          <iframe
            key={`${activeTabId}:${activeUrl}:${iframeReloadNonce}`}
            src={activeUrl}
            title={tabLabel(activeTab, t('browserTitle'))}
            sandbox="allow-downloads allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
            referrerPolicy="no-referrer"
            onLoad={() => {
              iframeLoadedUrlRef.current = activeUrl
              setLoading(false)
              setLoadError(null)
            }}
            className="block h-full w-full border-0 bg-white"
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
            <Globe2 className="h-8 w-8 text-ds-faint" strokeWidth={1.5} />
            <div className="text-[14px] font-medium text-ds-ink">{t('browserEmbedUnsupportedTitle')}</div>
            <div className="max-w-sm text-[12.5px] leading-5 text-ds-muted">
              {t('browserEmbedUnsupportedBody')}
            </div>
            <div className="max-w-md truncate text-[12px] text-ds-faint" title={activeUrl ?? undefined}>
              {activeUrl}
            </div>
            <button
              type="button"
              onClick={() => openExternalUrl(activeUrl)}
              className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-[12.5px] font-semibold text-white"
            >
              <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.85} />
              {t('browserOpenExternal')}
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
