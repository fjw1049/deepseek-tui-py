import {
  Check,
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
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useIsCodeFenceIncomplete } from 'streamdown'
import { getMermaidTheme, initMermaid, loadMermaid } from '../../lib/load-mermaid'

type Props = {
  chart: string
}

const COPY_RESET_MS = 2000
const MAX_LABEL_CHARS = 24

/** Truncate long node labels so scaled-down diagrams stay readable. */
export function truncateMermaidLabels(chart: string, maxLen = MAX_LABEL_CHARS): string {
  return chart.replace(
    /(\[[^\]]+\]|\{[^}]+\}|\([^)]+\)|"[^"]+")/g,
    (match) => {
      const open = match[0]
      const close = match[match.length - 1]
      const inner = match.slice(1, -1)
      if (inner.length <= maxLen) return match
      return `${open}${inner.slice(0, Math.max(1, maxLen - 1))}…${close}`
    }
  )
}

function downloadMermaid(chart: string): void {
  const blob = new Blob([chart], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'diagram.mmd'
  link.click()
  URL.revokeObjectURL(url)
}

function MermaidToolbar({
  chart,
  onFullscreen,
  disabled,
  trailing
}: {
  chart: string
  onFullscreen?: () => void
  disabled?: boolean
  trailing?: ReactElement | null
}): ReactElement {
  const [isCopied, setIsCopied] = useState(false)
  const copyResetRef = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current)
    },
    []
  )

  const handleCopy = async (): Promise<void> => {
    if (!navigator?.clipboard?.writeText) return
    await navigator.clipboard.writeText(chart)
    setIsCopied(true)
    if (copyResetRef.current !== null) window.clearTimeout(copyResetRef.current)
    copyResetRef.current = window.setTimeout(() => setIsCopied(false), COPY_RESET_MS)
  }

  return (
    <div className="ds-mermaid-block-actions">
      <button
        type="button"
        className="ds-code-block-action"
        title="Copy mermaid source"
        aria-label="Copy mermaid source"
        onClick={() => void handleCopy()}
        disabled={disabled}
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
        title="Download mermaid"
        aria-label="Download mermaid"
        onClick={() => downloadMermaid(chart)}
        disabled={disabled}
      >
        <Download className="h-3.5 w-3.5" strokeWidth={1.9} />
      </button>
      {onFullscreen ? (
        <button
          type="button"
          className="ds-code-block-action"
          title="Expand diagram"
          aria-label="Expand diagram"
          onClick={onFullscreen}
          disabled={disabled}
        >
          <Maximize2 className="h-3.5 w-3.5" strokeWidth={1.9} />
        </button>
      ) : null}
      {trailing}
    </div>
  )
}

function MermaidSvgHost({
  chart,
  className
}: {
  chart: string
  className?: string
}): ReactElement {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const renderSeqRef = useRef(0)
  const displayChart = useMemo(() => truncateMermaidLabels(chart), [chart])

  useEffect(() => {
    if (!displayChart.trim()) return

    const container = containerRef.current
    if (!container) return

    const seq = ++renderSeqRef.current
    container.replaceChildren()

    void loadMermaid()
      .then((mermaid) => {
        if (seq !== renderSeqRef.current || !containerRef.current) return
        initMermaid(mermaid, getMermaidTheme())
        const id = `ds-mermaid-${seq}-${Math.random().toString(36).slice(2, 9)}`
        return mermaid.render(id, displayChart)
      })
      .then((result) => {
        if (!result || seq !== renderSeqRef.current || !containerRef.current) return
        containerRef.current.innerHTML = result.svg
        setError(null)
      })
      .catch((err: unknown) => {
        if (seq !== renderSeqRef.current) return
        setError(err instanceof Error ? err.message : String(err))
      })
  }, [displayChart])

  if (error) {
    return (
      <div className={className}>
        <p className="ds-mermaid-error">{error}</p>
        <pre className="ds-mermaid-source">{chart}</pre>
      </div>
    )
  }

  return <div ref={containerRef} className={className} />
}

export function StreamdownMermaidBlock({ chart }: Props): ReactElement {
  const { t } = useTranslation('common')
  const isIncomplete = useIsCodeFenceIncomplete()
  const [fullscreen, setFullscreen] = useState(false)

  const closeFullscreen = useCallback(() => setFullscreen(false), [])

  useEffect(() => {
    if (!fullscreen) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') closeFullscreen()
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [fullscreen, closeFullscreen])

  if (isIncomplete) {
    return (
      <div className="ds-mermaid-block" data-streamdown="mermaid-block">
        <div className="ds-mermaid-block-header">
          <div className="ds-mermaid-block-label">mermaid</div>
        </div>
        <div className="ds-mermaid-loading">{t('mermaidLoading')}</div>
      </div>
    )
  }

  return (
    <>
      <div className="ds-mermaid-block" data-streamdown="mermaid-block">
        <div className="ds-mermaid-block-header">
          <div className="ds-mermaid-block-label">mermaid</div>
          <MermaidToolbar chart={chart} onFullscreen={() => setFullscreen(true)} />
        </div>
        <MermaidSvgHost chart={chart} className="ds-mermaid-svg" />
      </div>
      {fullscreen
        ? createPortal(
            <div
              className="ds-mermaid-fullscreen"
              data-streamdown="mermaid-fullscreen"
              role="dialog"
              aria-modal="true"
              aria-label="Mermaid diagram"
              onClick={closeFullscreen}
            >
              <div
                className="ds-mermaid-fullscreen-panel"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="ds-mermaid-fullscreen-header">
                  <div className="ds-mermaid-block-label">mermaid</div>
                  <MermaidToolbar
                    chart={chart}
                    trailing={
                      <button
                        type="button"
                        className="ds-code-block-action"
                        title="Close"
                        aria-label="Close"
                        onClick={closeFullscreen}
                      >
                        <X className="h-3.5 w-3.5" strokeWidth={1.9} />
                      </button>
                    }
                  />
                </div>
                <div className="ds-mermaid-fullscreen-body">
                  <MermaidSvgHost chart={chart} className="ds-mermaid-svg ds-mermaid-svg--fullscreen" />
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  )
}
