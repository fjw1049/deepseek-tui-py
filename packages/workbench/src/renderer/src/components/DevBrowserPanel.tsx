import type { FormEvent, ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  ArrowRight,
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

type DevWebviewTag = HTMLElement & {
  canGoBack(): boolean
  canGoForward(): boolean
  getURL(): string
  goBack(): void
  goForward(): void
  reloadIgnoringCache(): void
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

type PreviewTab = {
  id: string
  url: string | null
  title: string
}

const PREVIEW_AUTO_FOLLOW_STORAGE_KEY = 'deepseekgui.devPreview.autoFollow'

function readStoredAutoFollow(): boolean {
  try {
    const raw = window.localStorage.getItem(PREVIEW_AUTO_FOLLOW_STORAGE_KEY)
    return raw == null ? true : raw === 'true'
  } catch {
    return true
  }
}

function persistAutoFollow(value: boolean): void {
  try {
    window.localStorage.setItem(PREVIEW_AUTO_FOLLOW_STORAGE_KEY, String(value))
  } catch {
    /* ignore persistence failures */
  }
}

function formatAddressInput(url: string | null): string {
  if (!url) return ''
  try {
    const parsed = new URL(url)
    const path = parsed.pathname === '/' ? '' : parsed.pathname
    return `${parsed.host}${path}${parsed.search}${parsed.hash}`
  } catch {
    return url
  }
}

function tabLabel(tab: PreviewTab, fallback: string): string {
  if (tab.title.trim()) return tab.title.trim()
  if (!tab.url) return fallback
  try {
    const parsed = new URL(tab.url)
    const leaf = decodeURIComponent(parsed.pathname.split('/').filter(Boolean).at(-1) ?? '')
    return leaf || parsed.host || fallback
  } catch {
    return fallback
  }
}

function createTab(url: string | null = null, title = ''): PreviewTab {
  return {
    id: `preview-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    url,
    title
  }
}

type LoadOptions = {
  keepAutoFollow?: boolean
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
  const webviewRef = useRef<DevWebviewTag | null>(null)
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

  const updateActiveTab = useCallback(
    (patch: Partial<PreviewTab>): void => {
      setTabs((current) =>
        current.map((tab) => (tab.id === activeTabId ? { ...tab, ...patch } : tab))
      )
    },
    [activeTabId]
  )

  const openOrFocusUrl = useCallback(
    (url: string, options: { title?: string; select?: boolean } = {}): void => {
      const normalized = normalizeBrowseUrlInput(url)
      if (!normalized) return
      setTabs((current) => {
        const existing = current.find((tab) => tab.url === normalized)
        if (existing) {
          if (options.select !== false) setActiveTabId(existing.id)
          if (options.title) {
            return current.map((tab) =>
              tab.id === existing.id ? { ...tab, title: options.title ?? tab.title } : tab
            )
          }
          return current
        }

        // Prefer filling an existing blank tab (usually the initial one) so we
        // don't leave a stuck empty "first tab" beside the real preview.
        const emptyIndex = current.findIndex((tab) => !tab.url)
        if (emptyIndex >= 0) {
          const target = current[emptyIndex]!
          if (options.select !== false) setActiveTabId(target.id)
          return current.map((tab, index) =>
            index === emptyIndex
              ? { ...tab, url: normalized, title: options.title ?? '' }
              : tab
          )
        }

        const next = createTab(normalized, options.title ?? '')
        if (options.select !== false) setActiveTabId(next.id)
        return [...current, next]
      })
      setLoadError(null)
      setLoading(true)
      setDraftUrl(formatAddressInput(normalized))
      setIframeBackStack([])
      setIframeForwardStack([])
    },
    []
  )

  useEffect(() => {
    persistAutoFollow(autoFollow)
  }, [autoFollow])

  useEffect(() => {
    setDraftUrl(formatAddressInput(activeUrl))
    setLoadError(null)
    setCanGoBack(false)
    setCanGoForward(false)
    setIframeBackStack([])
    setIframeForwardStack([])
    setLoading(Boolean(activeUrl))
  }, [activeTabId, activeUrl])

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
    // Auto-follow stays local-only so agent-mentioned public links never hijack preview.
    if (!autoFollow || !latestDetectedUrl) return
    if (!isLocalPreviewUrl(latestDetectedUrl)) return
    if (tabs.some((tab) => tab.url === latestDetectedUrl)) return
    openOrFocusUrl(latestDetectedUrl, { select: tabs.every((tab) => !tab.url) })
  }, [autoFollow, latestDetectedUrl, openOrFocusUrl, tabs])

  useEffect(() => {
    const webview = webviewRef.current
    if (!useElectronWebview || !webview || !activeUrl) return

    const syncNavigationState = (): void => {
      try {
        setCanGoBack(webview.canGoBack())
        setCanGoForward(webview.canGoForward())
        const currentUrl = normalizeBrowseUrlInput(webview.getURL())
        if (currentUrl) {
          updateActiveTab({ url: currentUrl })
          setDraftUrl(formatAddressInput(currentUrl))
        }
      } catch {
        /* webview may not be attached yet */
      }
    }

    const handleStartLoading = (): void => {
      setLoading(true)
      setLoadError(null)
    }
    const handleStopLoading = (): void => {
      setLoading(false)
      syncNavigationState()
    }
    const handleNavigate: EventListener = (event): void => {
      const currentUrl = normalizeBrowseUrlInput((event as WebviewNavigateEvent).url)
      if (!currentUrl) return
      updateActiveTab({ url: currentUrl })
      setDraftUrl(formatAddressInput(currentUrl))
      setLoadError(null)
      syncNavigationState()
    }
    const handleFailLoad: EventListener = (event): void => {
      const failEvent = event as WebviewFailLoadEvent
      if (!failEvent.isMainFrame || failEvent.errorCode === -3) return
      setLoading(false)
      setLoadError(failEvent.errorDescription || t('browserLoadFailed'))
      syncNavigationState()
    }
    const handleTitle: EventListener = (event): void => {
      updateActiveTab({ title: (event as WebviewTitleEvent).title })
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
  }, [activeUrl, t, updateActiveTab, useElectronWebview])

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
    setTabs((current) => {
      const target = current.find((tab) => tab.id === tabId)
      if (!target) return current

      // Sole tab: clear the page instead of recreating another blank tab
      // (which made the X feel broken — "叉不掉").
      if (current.length <= 1) {
        if (!target.url && !target.title) return current
        setDraftUrl('')
        setLoadError(null)
        setLoading(false)
        resetNavState()
        return [{ ...target, url: null, title: '' }]
      }

      const index = current.findIndex((tab) => tab.id === tabId)
      const nextTabs = current.filter((tab) => tab.id !== tabId)
      if (tabId === activeTabId) {
        const fallback = nextTabs[Math.max(0, index - 1)] ?? nextTabs[0]!
        setActiveTabId(fallback.id)
        setDraftUrl(formatAddressInput(fallback.url))
        setLoadError(null)
        setLoading(Boolean(fallback.url))
        resetNavState()
      }
      return nextTabs
    })
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
      webviewRef.current?.reloadIgnoringCache()
    } catch {
      loadUrl(activeUrl, { keepAutoFollow: true })
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

  const iframeCanEmbed = Boolean(activeUrl && isLocalPreviewUrl(activeUrl))

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
      if (webviewRef.current?.canGoBack()) webviewRef.current.goBack()
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
      if (webviewRef.current?.canGoForward()) webviewRef.current.goForward()
    } catch {
      /* ignore unavailable webview navigation */
    }
  }

  return (
    <aside className={`ds-tool-panel ds-no-drag flex min-h-0 flex-col ${className ?? ''}`}>
      <div className="shrink-0 border-b border-ds-border-muted bg-transparent">
        <div className="flex h-11 min-w-0 items-center gap-1 px-2">
          <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
            {tabs.map((tab) => {
              const active = tab.id === activeTabId
              const isSoleBlank = tabs.length === 1 && !tab.url
              return (
                <div
                  key={tab.id}
                  className={`group flex h-8 max-w-[180px] shrink-0 items-center gap-1 rounded-[10px] px-2 transition ${
                    active
                      ? 'bg-ds-surface-subtle text-ds-ink dark:bg-white/10'
                      : 'text-ds-muted hover:bg-ds-hover/70 hover:text-ds-ink'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => setActiveTabId(tab.id)}
                    className="flex min-w-0 flex-1 items-center gap-1.5"
                    title={tab.url ?? t('browserNewTab')}
                  >
                    <Globe2 className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
                    <span className="min-w-0 truncate text-[12px] font-medium">
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
                    className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-default disabled:opacity-30 ${
                      active ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                    }`}
                    aria-label={t('browserCloseTab')}
                    title={isSoleBlank ? t('browserCloseTabDisabled') : t('browserCloseTab')}
                  >
                    <X className="h-3 w-3" strokeWidth={2} />
                  </button>
                </div>
              )
            })}
          </div>
          <button
            type="button"
            onClick={addTab}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label={t('browserNewTab')}
            title={t('browserNewTab')}
          >
            <Plus className="h-4 w-4" strokeWidth={1.8} />
          </button>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => openExternalUrl()}
              disabled={!activeUrl}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-default disabled:opacity-35"
              aria-label={t('browserOpenExternal')}
              title={t('browserOpenExternal')}
            >
              <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} />
            </button>
            <button
              type="button"
              onClick={() => setAutoFollow((value) => !value)}
              className={`inline-flex h-8 items-center justify-center gap-1 rounded-full px-2 transition hover:bg-ds-hover ${
                autoFollow ? 'text-sky-500 dark:text-sky-300' : 'text-ds-faint hover:text-ds-ink'
              }`}
              aria-label={t('browserAutoFollow')}
              aria-pressed={autoFollow}
              title={t('browserAutoFollow')}
            >
              <Radar className="h-3.5 w-3.5" strokeWidth={1.75} />
              <span className="text-[11px] font-medium">{t('browserAutoFollowShort')}</span>
            </button>
          </div>
        </div>

        <form onSubmit={submitUrl} className="flex h-12 min-w-0 items-center gap-2 px-3">
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={goBack}
              disabled={!canNavigateBack}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-default disabled:opacity-35"
              aria-label={t('browserBack')}
              title={t('browserBack')}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={1.8} />
            </button>
            <button
              type="button"
              onClick={goForward}
              disabled={!canNavigateForward}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-default disabled:opacity-35"
              aria-label={t('browserForward')}
              title={t('browserForward')}
            >
              <ArrowRight className="h-4 w-4" strokeWidth={1.8} />
            </button>
            <button
              type="button"
              onClick={reload}
              disabled={!activeUrl}
              className="inline-flex h-8 w-8 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-default disabled:opacity-35"
              aria-label={t('browserReload')}
              title={t('browserReload')}
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.8} />
              ) : (
                <RefreshCw className="h-4 w-4" strokeWidth={1.8} />
              )}
            </button>
          </div>

          <div className="min-w-0 flex-1 px-3">
            <input
              value={draftUrl}
              onChange={(event) => setDraftUrl(event.target.value)}
              className="h-8 w-full min-w-0 rounded-full bg-transparent px-3 text-center text-[14px] font-medium text-ds-ink outline-none transition focus:bg-ds-surface-subtle focus:text-left dark:focus:bg-white/8"
              placeholder={t('browserAddressPlaceholder')}
              spellCheck={false}
            />
          </div>

          <button
            type="submit"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label={t('browserOpen')}
            title={t('browserOpen')}
          >
            <Send className="h-3.5 w-3.5" strokeWidth={1.8} />
          </button>
        </form>

        {detectedUrls.length > 0 ? (
          <div className="flex min-w-0 gap-1.5 overflow-x-auto px-3 pb-2">
            {detectedUrls.map((url) => (
              <button
                key={url}
                type="button"
                onClick={() => {
                  setAutoFollow(false)
                  openOrFocusUrl(url)
                }}
                className="shrink-0 rounded-full border border-ds-border-muted bg-ds-surface-subtle px-2.5 py-1 text-[10.5px] font-medium text-ds-muted transition hover:border-ds-border-strong hover:text-ds-ink dark:bg-white/6"
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
        {!activeUrl ? (
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
        ) : useElectronWebview ? (
          <webview
            key={activeTabId}
            ref={webviewRef}
            src={activeUrl}
            partition="persist:deepseek-dev-browser"
            webpreferences="contextIsolation=yes,nodeIntegration=no,sandbox=yes"
            className="flex h-full w-full bg-white"
          />
        ) : iframeCanEmbed ? (
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
            <div className="max-w-md truncate text-[12px] text-ds-faint" title={activeUrl}>
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
