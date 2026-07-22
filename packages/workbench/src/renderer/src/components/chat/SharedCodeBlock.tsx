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
import type { ThemeRegistration } from 'shiki'
import { useChatStore } from '../../store/chat-store'
import { ResizableFullscreenDialog } from './ResizableFullscreenDialog'

const TRAILING_NEWLINES_REGEX = /\n+$/
const COLLAPSE_HEIGHT = 200
const COPY_RESET_MS = 2000

const CODEX_CODE_THEME = {
  name: 'codex',
  displayName: 'Codex',
  type: 'dark',
  fg: '#ffffff',
  bg: '#181818',
  colors: {
    'editor.background': '#181818',
    'editor.foreground': '#ffffff',
    'editor.selectionBackground': '#339cff44',
    'editor.inactiveSelectionBackground': '#339cff22',
    'editor.lineHighlightBackground': '#ffffff08',
    'editorCursor.foreground': '#ffffff',
    'editorGutter.addedBackground': '#40c977',
    'editorGutter.deletedBackground': '#fa423e',
    'editorGutter.modifiedBackground': '#339cff',
    'diffEditor.insertedTextBackground': '#40c97724',
    'diffEditor.removedTextBackground': '#fa423e24',
    'terminal.ansiGreen': '#40c977',
    'terminal.ansiRed': '#fa423e',
    'terminal.ansiBlue': '#339cff',
    'terminal.ansiMagenta': '#ad7bf9'
  },
  settings: [
    {
      settings: {
        foreground: '#ffffff',
        background: '#181818'
      }
    },
    {
      scope: ['comment', 'punctuation.definition.comment', 'string.comment'],
      settings: {
        foreground: '#858585',
        fontStyle: 'italic'
      }
    },
    {
      scope: ['keyword', 'storage', 'storage.type', 'storage.modifier'],
      settings: {
        foreground: '#fa423e'
      }
    },
    {
      scope: ['string', 'punctuation.definition.string'],
      settings: {
        foreground: '#40c977'
      }
    },
    {
      scope: ['constant', 'constant.numeric', 'variable.language', 'support.constant'],
      settings: {
        foreground: '#7bbcff'
      }
    },
    {
      scope: [
        'entity.name.function',
        'support.function',
        'meta.function-call',
        'entity.name.type',
        'entity.other.inherited-class'
      ],
      settings: {
        foreground: '#ad7bf9'
      }
    },
    {
      scope: ['variable.parameter', 'variable.other', 'meta.property-name', 'support.type.property-name'],
      settings: {
        foreground: '#c7c7c7'
      }
    },
    {
      scope: ['entity.name.tag', 'entity.other.attribute-name'],
      settings: {
        foreground: '#339cff'
      }
    },
    {
      scope: ['punctuation', 'meta.brace'],
      settings: {
        foreground: '#c7c7c7'
      }
    },
    {
      scope: ['markup.inserted', 'meta.diff.header.to-file', 'punctuation.definition.inserted'],
      settings: {
        foreground: '#40c977',
        background: '#173222'
      }
    },
    {
      scope: ['markup.deleted', 'meta.diff.header.from-file', 'punctuation.definition.deleted'],
      settings: {
        foreground: '#fa423e',
        background: '#351b1b'
      }
    },
    {
      scope: ['markup.changed', 'punctuation.definition.changed', 'meta.diff.range'],
      settings: {
        foreground: '#339cff'
      }
    }
  ]
} satisfies ThemeRegistration

const SHIKI_THEMES = {
  light: 'github-light',
  dark: CODEX_CODE_THEME
} as const

const LANGUAGE_ALIASES: Record<string, string> = {
  csharp: 'cs',
  docker: 'dockerfile',
  plaintext: '',
  shellscript: 'shell',
  text: '',
  typescriptreact: 'tsx',
  javascriptreact: 'jsx'
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

const EXT_TO_LANGUAGE: Record<string, string> = {
  c: 'c',
  cpp: 'cpp',
  cs: 'cs',
  css: 'css',
  go: 'go',
  html: 'html',
  htm: 'html',
  java: 'java',
  js: 'js',
  jsx: 'jsx',
  json: 'json',
  md: 'md',
  mjs: 'js',
  php: 'php',
  py: 'python',
  rb: 'rb',
  rs: 'rust',
  sh: 'shell',
  sql: 'sql',
  swift: 'swift',
  ts: 'typescript',
  tsx: 'tsx',
  xml: 'xml',
  yaml: 'yaml',
  yml: 'yaml'
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
    .map((line) => `<span class="line">${line ? escapeHtml(line) : ' '}</span>`)
    .join('\n')}</code></pre>`
}

export function normalizeLanguage(language: string): string {
  const raw = language.trim().toLowerCase()
  return LANGUAGE_ALIASES[raw] ?? raw
}

export function languageFromPath(path: string | undefined): string {
  if (!path) return ''
  const base = path.split(/[\\/]/).pop() ?? path
  const dot = base.lastIndexOf('.')
  if (dot < 0) return ''
  const ext = base.slice(dot + 1).toLowerCase()
  return EXT_TO_LANGUAGE[ext] ?? ext
}

export function titleFromPath(path: string | undefined): string | undefined {
  if (!path?.trim()) return undefined
  return path.trim()
}

async function highlightCodeHtml(code: string, language: string): Promise<string> {
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
  downloadName,
  deferHighlightWhileBusy = false,
  actionsDisabled = false,
  className
}: SharedCodeBlockProps): ReactElement {
  const busy = useChatStore((s) => s.busy)
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
  const headerLabel = title?.trim() || language || 'text'
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

  const closeFullscreen = useCallback(() => setFullscreen(false), [])

  const handleCopy = async (): Promise<void> => {
    if (!navigator?.clipboard?.writeText) return
    await navigator.clipboard.writeText(trimmedCode)
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
        onClick={() => downloadCode(trimmedCode, language, downloadName)}
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
        onClick={() => setFullscreen(true)}
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
      {opts.collapsed ? (
        <button
          type="button"
          className="ds-code-block-fade"
          aria-label="Expand code"
          onClick={() => setExpanded(true)}
        />
      ) : null}
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
          <span className="ds-code-block-language" title={headerLabel}>
            {headerLabel}
          </span>
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
            <span className="ds-code-block-language" title={headerLabel}>
              {headerLabel}
            </span>
            <div className="ds-code-block-actions">
              <button
                type="button"
                className="ds-code-block-action"
                title="Download code"
                aria-label="Download code"
                onClick={() => downloadCode(trimmedCode, language, downloadName)}
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
