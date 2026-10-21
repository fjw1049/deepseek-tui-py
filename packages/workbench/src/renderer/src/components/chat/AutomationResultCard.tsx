import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, ChevronDown } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { markdownExternalLinkComponents } from '../../lib/markdown-external-link'
import type { ChatBlock } from '../../agent/types'

export function AutomationResultCard({ block }: { block: Extract<ChatBlock, { kind: 'system' }> }) {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const meta = block.automation ?? {}
  const header = block.text.match(/^\[([^\n]+?)\] ?/)
  const title = header?.[1] || t('automationResultTitle')
  const text = header ? block.text.slice(header[0].length) : block.text
  // The runtime appends context and IDs after the report; keep them in details.
  const footer = text.match(/(?:\n\n任务要求：[\s\S]*?)?\nTask ID: [^\n]+\nRun ID: [^\n]+$/)
  const report = footer ? text.slice(0, footer.index) : text
  const time = typeof meta.ended_at === 'string' ? meta.ended_at : block.createdAt
  const date = time ? new Date(time) : null
  return (
    <section className="w-full min-w-0 overflow-hidden rounded-2xl border border-ds-border-muted bg-ds-card/40 text-left">
      <div className="flex items-start gap-3 px-4 py-4">
        <FileText size={18} className="mt-0.5 shrink-0 text-ds-muted" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="text-[11px] text-ds-faint">{t('automationResultTitle')}</div>
          <div className="mt-1 break-words text-[14px] font-medium text-ds-ink">{title}</div>
          {date && !Number.isNaN(date.getTime()) && <time dateTime={time} className="mt-1 block text-[11px] text-ds-faint">{date.toLocaleString()}</time>}
        </div>
        <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
          {t(expanded ? 'automationHideReport' : 'automationViewReport')}
          <ChevronDown size={14} className={expanded ? 'rotate-180' : ''} aria-hidden="true" />
        </button>
      </div>
      {expanded && <div className="border-t border-ds-border-muted px-4 py-4">
        <div className="ds-markdown max-w-none overflow-x-auto break-words text-ds-ink">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownExternalLinkComponents}>{report || t('automationNoReport')}</ReactMarkdown>
        </div>
        {footer && <details className="mt-4 border-t border-ds-border-muted pt-3 text-[12px] text-ds-muted">
          <summary className="cursor-pointer">{t('executionDetails')}</summary>
          <pre className="mt-2 whitespace-pre-wrap break-all font-mono text-[11px]">{footer[0].trim()}</pre>
        </details>}
      </div>}
    </section>
  )
}
