import { copyText } from '../../lib/copy-text'
import { useConversationScope } from './conversation-scope'
import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  Maximize2,
  X
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode
} from 'react'
import type { ThemeRegistration, ThemeRegistrationRaw } from 'shiki'
import { useChatStore } from '../../store/chat-store'
import { basenameOfPath, formatFileLineRange } from '../../lib/file-chip'
import { CODE_CHROME, CODE_PALETTE, SHIKI_SCOPE_SLOTS, type CodeAppearance } from '../../lib/code-palette'
import { normalizeLanguage } from './code-language'
import { FileChip } from './FileChip'
import { ResizableFullscreenDialog } from './ResizableFullscreenDialog'

const TRAILING_NEWLINES_REGEX = /\n+$/
const COLLAPSE_HEIGHT = 480
const COPY_RESET_MS = 2000

/**
 * Both chat themes come from lib/code-palette.ts — the same slots the Monaco
 * editor consumes — so a file keeps its colors as it moves between the editor
 * and a chat block. The built-in `github-light` this replaces was the light
 * half of that drift.
 */
function shikiTheme(appearance: CodeAppearance, name: string): ThemeRegistration {
  const slots = CODE_PALETTE[appearance]
  const background = appearance === 'dark' ? '#181818' : '#ffffff'
  // One TextMate settings entry per distinct style, scopes grouped under it.
  const groups = new Map<string, { scope: string[]; settings: Record<string, string> }>()
  for (const [scope, slot, fontStyle] of SHIKI_SCOPE_SLOTS) {
    const style = slots[slot]
    const font = fontStyle ?? style.fontStyle ?? ''
    const settings: Record<string, string> = { foreground: style.color }
    if (font) settings.fontStyle = font
    if (style.background) settings.background = style.background
    const key = JSON.stringify(settings)
    const group = groups.get(key)
    if (group) group.scope.push(scope)
    else groups.set(key, { scope: [scope], settings })
  }
  return {
    name,
    displayName: name,
    type: appearance,
    fg: slots.ink.color,
    bg: background,
    colors: {
      ...CODE_CHROME[appearance],
      'editor.background': background,
      'terminal.ansiGreen': slots.added.color,
      'terminal.ansiRed': slots.removed.color,
      'terminal.ansiBlue': slots.changed.color,
      'terminal.ansiMagenta': slots.function.color
    },
    settings: [
      { settings: { foreground: slots.ink.color, background } },
      ...groups.values()
    ]
  } satisfies ThemeRegistration as ThemeRegistrationRaw as ThemeRegistration
}

const SHIKI_THEMES = {
  light: shikiTheme('light', 'ds-light'),
  dark: shikiTheme('dark', 'codex')
}

const DOWNLOAD_EXTENSIONS: Record<string, string> = {
  bash: 'sh',
  c: 'c',
  cpp: 'cpp',
  cs: 'cs',
  css: 'css',
  diff: 'diff',
  dockerfile: 'dockerfile',
  go: 'go',
  html: 'html',
  java: 'java',
  js: 'js',
  json: 'json',
  jsx: 'jsx',
  md: 'md',
  php: 'php',
  py: 'py',
  python: 'py',
  rb: 'rb',
  rs: 'rs',
  rust: 'rs',
  sh: 'sh',
  shell: 'sh',
  sql: 'sql',
  swift: 'swift',
  ts: 'ts',
  tsx: 'tsx',
  txt: 'txt',
  typescript: 'ts',
  xml: 'xml',
  yaml: 'yml',
  yml: 'yml'
}

let shikiPromise: Promise<typeof import('shiki')> | null = null
const highlightCache = new Map<string, string>()
const inflightHighlights = new Map<string, Promise<string>>()
const HIGHLIGHT_CACHE_MAX = 48

function trimHighlightCache(): void {
  while (highlightCache.size > HIGHLIGHT_CACHE_MAX) {
    const oldest = highlightCache.keys().next().value
    if (oldest === undefined) break
    highlightCache.delete(oldest)
  }
}

function loadShiki(): Promise<typeof import('shiki')> {
  shikiPromise ??= import('shiki')
  return shikiPromise
}

function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function renderFallbackHtml(code: string): string {
  const lines = code.split('\n')
  return `<pre class="shiki shiki-themes"><code>${lines
    .map((line) => `<span class="line">${escapeHtml(line)}</span>`)
    .join('\n')}</code></pre>`
}

export async function highlightCodeHtml(code: string, language: string): Promise<string> {
  const normalized = normalizeLanguage(language)
  const cacheKey = `${normalized || 'plain'}\u0000${code}`
  const cached = highlightCache.get(cacheKey)
  if (cached) return cached

  const inflight = inflightHighlights.get(cacheKey)
  if (inflight) return inflight

  const task = (async () => {
    if (!normalized) {
      const fallback = renderFallbackHtml(code)
      highlightCache.set(cacheKey, fallback)
      trimHighlightCache()
      return fallback
    }

    try {
      const { codeToHtml } = await loadShiki()
      const html = await codeToHtml(code, {
        lang: normalized,
        themes: SHIKI_THEMES
      })
      highlightCache.set(cacheKey, html)
      trimHighlightCache()
      return html
    } catch (error) {
      // Common cause in Electron: CSP missing 'wasm-unsafe-eval' for Oniguruma.
      // Do not cache failures — CSP/HMR fixes should be able to retry.
      console.warn('[SharedCodeBlock] Shiki highlight failed; using plain text', error)
      return renderFallbackHtml(code)
    }
  })()

  inflightHighlights.set(cacheKey, task)
  try {
    return await task
  } finally {
    inflightHighlights.delete(cacheKey)
  }
}

function extensionForLanguage(language: string): string {
  const normalized = normalizeLanguage(language)
  if (!normalized) return 'txt'
  return DOWNLOAD_EXTENSIONS[normalized] ?? normalized
}

function downloadCode(code: string, language: string, filename?: string): void {
  const ext = extensionForLanguage(language)
  const blob = new Blob([code], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename?.trim() || `code.${ext}`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export type SharedCodeBlockProps = {
  code: string
  language?: string
  /** Header label; defaults to language (or "text"). */
  title?: string
  /** When set, the header becomes a clickable file chip. */
  filePath?: string
  lineStart?: number
  lineEnd?: number
  /** Download filename hint (e.g. basename of a file path). */
  downloadName?: string
  /** When true, skip Shiki while the chat turn is busy (streaming). */
  deferHighlightWhileBusy?: boolean
  /** Disable action buttons (e.g. while streamdown animates). */
  actionsDisabled?: boolean
  className?: string
}

export function SharedCodeBlock({
  code,
  language = '',
  title,
  filePath,
  lineStart,
  lineEnd,
  downloadName,
  deferHighlightWhileBusy = false,
  actionsDisabled = false,
  className
}: SharedCodeBlockProps): ReactElement {
  const scope = useConversationScope()
  const mainBusy = useChatStore((s) => s.busy)
  const busy = scope?.active ?? mainBusy
  const trimmedCode = useMemo(() => code.replace(TRAILING_NEWLINES_REGEX, ''), [code])
  const [html, setHtml] = useState(() => renderFallbackHtml(trimmedCode))
  const [isCopied, setIsCopied] = useState(false)
  const [expandable, setExpandable] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)
  const copyResetRef = useRef<number | null>(null)
  /** Content key that currently has successful Shiki HTML (not plain fallback). */
  const highlightedForRef = useRef<string | null>(null)
  const headerLabel = filePath
    ? `${basenameOfPath(filePath)}${formatFileLineRange(lineStart, lineEnd)}`
    : title?.trim() || language || 'text'
  const contentKey = `${normalizeLanguage(language) || 'plain'}\u0000${trimmedCode}`

  useEffect(() => {
    let cancelled = false
    const skipHighlight = deferHighlightWhileBusy && busy

    if (skipHighlight) {
      // Keep prior highlight for this content; only fall back when none yet
      // (e.g. first paint mid-stream). Avoid wiping every block while busy.
      if (highlightedForRef.current !== contentKey) {
        setHtml(renderFallbackHtml(trimmedCode))
      }
      return () => {
        cancelled = true
      }
    }

    if (highlightedForRef.current !== contentKey) {
      setHtml(renderFallbackHtml(trimmedCode))
    }

    void highlightCodeHtml(trimmedCode, language).then((nextHtml) => {
      if (cancelled) return
      setHtml(nextHtml)
      highlightedForRef.current = contentKey
    })

    return () => {
      cancelled = true
    }
  }, [busy, contentKey, deferHighlightWhileBusy, language, trimmedCode])

  useEffect(() => {
    const el = bodyRef.current
    if (!el) return

    const update = (): void => {
      setExpandable(el.scrollHeight > COLLAPSE_HEIGHT)
    }

    update()
    if (typeof ResizeObserver === 'undefined') return

    const observer = new ResizeObserver(() => update())
    observer.observe(el)
    return () => observer.disconnect()
  }, [html, trimmedCode])

  useEffect(() => {
    setExpanded(false)
  }, [trimmedCode, language])

  useEffect(
    () => () => {
      if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current)
    },
    []
  )

  const resolvedDownloadName = downloadName?.trim() || (filePath ? basenameOfPath(filePath) : undefined)

  const closeFullscreen = useCallback(() => setFullscreen(false), [])

  const handleCopy = async (): Promise<void> => {
    if (!await copyText(trimmedCode)) { setIsCopied(false); return }
    setIsCopied(true)
    if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current)
    copyResetRef.current = window.setTimeout(() => setIsCopied(false), COPY_RESET_MS)
  }

  const actions = (
    <div className="ds-code-block-actions">
      <button
        type="button"
        className="ds-code-block-action"
        title="Download code"
        aria-label="Download code"
        onClick={() => downloadCode(trimmedCode, language, resolvedDownloadName)}
        disabled={actionsDisabled}
      >
        <Download className="h-3.5 w-3.5" strokeWidth={1.9} />
      </button>
      <button
        type="button"
        className="ds-code-block-action"
        title="Copy code"
        aria-label="Copy code"
        onClick={() => void handleCopy()}
        disabled={actionsDisabled}
      >
        {isCopied ? (
          <Check className="h-3.5 w-3.5" strokeWidth={2.1} />
        ) : (
          <Copy className="h-3.5 w-3.5" strokeWidth={1.9} />
        )}
      </button>
      <button
        type="button"
        className="ds-code-block-action"
        title="Expand code"
        aria-label="Expand code"
        onClick={(event) => {
          event.stopPropagation()
          setFullscreen(true)
        }}
        disabled={actionsDisabled}
      >
        <Maximize2 className="h-3.5 w-3.5" strokeWidth={1.9} />
      </button>
      {expandable && !fullscreen ? (
        <button
          type="button"
          className="ds-code-block-action"
          title={expanded ? 'Collapse code' : 'Expand code'}
          aria-label={expanded ? 'Collapse code' : 'Expand code'}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5" strokeWidth={1.9} />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" strokeWidth={1.9} />
          )}
        </button>
      ) : null}
    </div>
  )

  const codeBody = (opts: { collapsed: boolean; bodyRef?: typeof bodyRef }): ReactNode => (
    <div className={`ds-code-block-body ${opts.collapsed ? 'is-collapsed' : ''}`}>
      <div
        ref={opts.bodyRef}
        className="ds-code-block-html"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  )

  return (
    <>
      <div
        className={['ds-code-block', className].filter(Boolean).join(' ')}
        data-language={language}
        data-streamdown="code-block"
        style={{
          contentVisibility: 'auto',
          containIntrinsicSize: 'auto 220px'
        }}
      >
        <div className="ds-code-block-header" data-streamdown="code-block-header">
          {filePath ? (
            <FileChip
              path={filePath}
              line={lineStart}
              endLine={lineEnd}
              skipValidation
              variant="list"
              className="ds-code-block-language"
            />
          ) : (
            <span className="ds-code-block-language" title={headerLabel}>
              {headerLabel}
            </span>
          )}
          {actions}
        </div>
        {codeBody({
          collapsed: expandable && !expanded,
          bodyRef
        })}
      </div>
      <ResizableFullscreenDialog
        open={fullscreen}
        onClose={closeFullscreen}
        ariaLabel={headerLabel}
        overlayClassName="ds-code-fullscreen"
        panelClassName="ds-code-fullscreen-panel"
        bodyClassName="ds-code-fullscreen-body"
        dataAttr="code-fullscreen"
        header={
          <>
            {filePath ? (
              <FileChip
                path={filePath}
                line={lineStart}
                endLine={lineEnd}
                skipValidation
                variant="list"
                className="ds-code-block-language"
              />
            ) : (
              <span className="ds-code-block-language" title={headerLabel}>
                {headerLabel}
              </span>
            )}
            <div className="ds-code-block-actions">
              <button
                type="button"
                className="ds-code-block-action"
                title="Download code"
                aria-label="Download code"
                onClick={() => downloadCode(trimmedCode, language, resolvedDownloadName)}
              >
                <Download className="h-3.5 w-3.5" strokeWidth={1.9} />
              </button>
              <button
                type="button"
                className="ds-code-block-action"
                title="Copy code"
                aria-label="Copy code"
                onClick={() => void handleCopy()}
              >
                {isCopied ? (
                  <Check className="h-3.5 w-3.5" strokeWidth={2.1} />
                ) : (
                  <Copy className="h-3.5 w-3.5" strokeWidth={1.9} />
                )}
              </button>
              <button
                type="button"
                className="ds-code-block-action"
                title="Close"
                aria-label="Close"
                onClick={closeFullscreen}
              >
                <X className="h-3.5 w-3.5" strokeWidth={1.9} />
              </button>
            </div>
          </>
        }
      >
        {codeBody({ collapsed: false })}
      </ResizableFullscreenDialog>
    </>
  )
}
