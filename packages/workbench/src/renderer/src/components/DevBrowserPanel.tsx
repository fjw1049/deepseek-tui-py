import type { FormEvent, ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  ArrowRight,
  Bug,
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

type DevWebviewTag = HTMLElement & {
  canGoBack(): boolean
  canGoForward(): boolean
  getURL(): string
  goBack(): void
  goForward(): void
  loadURL(url: string): Promise<void>
  openDevTools(): void
  reloadIgnoringCache(): void
  stop(): void
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
  onFailLoad
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
      void webview.loadURL(url).catch(() => {
        /* load failures surface via did-fail-load */
      })
      loadedUrlRef.current = url
    } catch {
      /* webview not attached yet */
    }
  }, [url])

  useEffect(() => {
    const webview = webviewRef.current
    if (!webview) return

    const handleStartLoading = (): void => onLoadingChange(tabId, true)
    const handleStopLoading = (): void => onLoadingChange(tabId, false)
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

    webview.addEventListener('did-start-loading', handleStartLoading)
    webview.addEventListener('did-stop-loading', handleStopLoading)
    webview.addEventListener('did-navigate', handleNavigate)
    webview.addEventListener('did-navigate-in-page', handleNavigate)
    webview.addEventListener('did-fail-load', handleFailLoad)
    webview.addEventListener('page-title-updated', handleTitle)

    return () => {
      webview.removeEventListener('did-start-loading', handleStartLoading)
      webview.removeEventListener('did-stop-loading', handleStopLoading)
      webview.removeEventListener('did-navigate', handleNavigate)
      webview.removeEventListener('did-navigate-in-page', handleNavigate)
      webview.removeEventListener('did-fail-load', handleFailLoad)
      webview.removeEventListener('page-title-updated', handleTitle)
    }
  }, [tabId, onNavigate, onTitle, onLoadingChange, onFailLoad])

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
  externalError,
  onPreferredUrlConsumed,
  onExternalErrorConsumed,
  className
}: {
  blocks: ChatBlock[]
  preferredUrl?: string | null
  externalError?: string | null
  onPreferredUrlConsumed?: () => void
  onExternalErrorConsumed?: () => void
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
  const canNavigateBack = useElectronWebview ? canGoBack : iframeBackStack.length > 0
  const canNavigateForward = useElectronWebview ? canGoForward : iframeForwardStack.length > 0

  const updateActiveTab = useCallback((patch: Partial<PreviewTab>): void => {
    const tabId = activeTabIdRef.current
    setTabs((current) => updateTabById(current, tabId, patch))
  }, [])

  const registerWebview = useCallback((tabId: string, webview: DevWebviewTag | null): void => {
    if (webview) webviewRefs.current.set(tabId, webview)
    else webviewRefs.current.delete(tabId)
  }, [])

  const syncActiveNavigationState = useCallback((tabId: string): void => {
    const webview = webviewRefs.current.get(tabId)
    if (!webview) return
    try {
      setCanGoBack(webview.canGoBack())
      setCanGoForward(webview.canGoForward())
    } catch {
      /* webview may not be attached yet */
    }
  }, [])

  const handleWebviewNavigate = useCallback(
    (tabId: string, url: string): void => {
      setTabs((current) => updateTabById(current, tabId, { url }))
      if (tabId !== activeTabIdRef.current) return
      setDraftUrl(formatAddressInput(url))
      setLoadError(null)
      syncActiveNavigationState(tabId)
    },
    [syncActiveNavigationState]
  )

  const handleWebviewTitle = useCallback((tabId: string, title: string): void => {
    setTabs((current) => updateTabById(current, tabId, { title }))
  }, [])

  const handleWebviewLoadingChange = useCallback(
    (tabId: string, nextLoading: boolean): void => {
      if (tabId !== activeTabIdRef.current) return
      setLoading(nextLoading)
      if (nextLoading) setLoadError(null)
      else syncActiveNavigationState(tabId)
    },
    [syncActiveNavigationState]
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

  const openOrFocusUrl = useCallback(
    (url: string, options: { title?: string; select?: boolean } = {}): void => {
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
      }
      setIframeBackStack([])
      setIframeForwardStack([])
    },
    []
  )

  useEffect(() => {
    persistAutoFollow(autoFollow)
  }, [autoFollow])

  // Reset toolbar/nav state only when switching tabs. In-page navigation is
  // reflected by the webview event handlers instead, so it must not wipe
  // canGoBack/canGoForward here.
  useEffect(() => {
    const tab = tabsRef.current.find((candidate) => candidate.id === activeTabId)
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
    const webview = webviewRefs.current.get(activeTabId)
    if (webview) {
      try {
        setCanGoBack(webview.canGoBack())
        setCanGoForward(webview.canGoForward())
        const currentUrl = normalizeBrowseUrlInput(webview.getURL())
        if (currentUrl) setDraftUrl(formatAddressInput(currentUrl))
      } catch {
        /* webview may not be attached yet */
      }
    }
  }, [activeTabId])

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
    openOrFocusUrl(normalizedPreferredUrl)
    onPreferredUrlConsumed?.()
  }, [normalizedPreferredUrl, onPreferredUrlConsumed, openOrFocusUrl])

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
    setLoadError(null)
    setLoading(true)
    if (!useElectronWebview && activeUrl && normalized !== activeUrl) {
      setIframeBackStack((stack) => [...stack, activeUrl].slice(-30))
      setIframeForwardStack([])
    }
    updateActiveTab({ url: normalized, title: '' })
    setDraftUrl(formatAddressInput(normalized))
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
            <button
              type="button"
              onClick={() => setAutoFollow((value) => !value)}
              className={`ds-dev-browser__follow${autoFollow ? ' is-on' : ''}`}
              aria-label={t('browserAutoFollow')}
              aria-pressed={autoFollow}
              title={t('browserAutoFollow')}
            >
              <Radar className="h-3.5 w-3.5" strokeWidth={1.75} />
              <span>{t('browserAutoFollowShort')}</span>
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
          // Every tab keeps its webview mounted (hidden when inactive, same
          // pattern as the terminal panel) so page state, scroll position and
          // history survive tab switches instead of reloading.
          <div className="relative h-full w-full">
            {tabs.map((tab) =>
              tab.url ? (
                <div
                  key={tab.id}
                  className={
                    tab.id === activeTabId ? 'h-full w-full' : 'hidden h-full w-full'
                  }
                >
                  <DevBrowserWebview
                    tabId={tab.id}
                    url={tab.url}
                    registerWebview={registerWebview}
                    onNavigate={handleWebviewNavigate}
                    onTitle={handleWebviewTitle}
                    onLoadingChange={handleWebviewLoadingChange}
                    onFailLoad={handleWebviewFailLoad}
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
