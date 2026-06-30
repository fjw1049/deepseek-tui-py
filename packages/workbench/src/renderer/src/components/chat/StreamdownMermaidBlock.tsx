import { useEffect, useRef, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { useIsCodeFenceIncomplete } from 'streamdown'
import { getMermaidTheme, initMermaid, loadMermaid } from '../../lib/load-mermaid'

type Props = {
  chart: string
}

export function StreamdownMermaidBlock({ chart }: Props): ReactElement {
  const { t } = useTranslation('common')
  const isIncomplete = useIsCodeFenceIncomplete()
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const renderSeqRef = useRef(0)

  useEffect(() => {
    if (isIncomplete || !chart.trim()) return

    const container = containerRef.current
    if (!container) return

    const seq = ++renderSeqRef.current
    container.replaceChildren()

    void loadMermaid()
      .then((mermaid) => {
        if (seq !== renderSeqRef.current || !containerRef.current) return
        initMermaid(mermaid, getMermaidTheme())
        const id = `ds-mermaid-${seq}-${Math.random().toString(36).slice(2, 9)}`
        return mermaid.render(id, chart)
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
  }, [chart, isIncomplete])

  if (isIncomplete) {
    return (
      <div className="ds-mermaid-block" data-streamdown="mermaid-block">
        <div className="ds-mermaid-block-label">mermaid</div>
        <div className="ds-mermaid-loading">{t('mermaidLoading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="ds-mermaid-block ds-mermaid-block--error" data-streamdown="mermaid-block">
        <div className="ds-mermaid-block-label">mermaid</div>
        <p className="ds-mermaid-error">{t('mermaidRenderFailed')}</p>
        <pre className="ds-mermaid-source">{chart}</pre>
      </div>
    )
  }

  return (
    <div className="ds-mermaid-block" data-streamdown="mermaid-block">
      <div className="ds-mermaid-block-label">mermaid</div>
      <div ref={containerRef} className="ds-mermaid-svg" />
    </div>
  )
}
