import { useMemo, useRef, useState, type ReactElement } from 'react'
import { Check, ChevronRight, CircleAlert, Clock3, FileText, Globe2, Loader2, Search, Terminal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { StepFlowItem } from '../chat/StepFlow'
import { StreamdownAssistant } from '../chat/StreamdownAssistant'
import { humanizeToolName } from '../chat/tool/render-context'
import { groupRunActivity, isRunActive, runActionCount, runActionTargets } from '../../lib/run-activity'
import { probeComposeSegments, probeToolKind } from '../../lib/step-flow-collapse'

export function RunStateIcon({ status }: { status?: string }): ReactElement {
  const className = `ds-run-state-icon ${isRunActive(status) ? 'is-active' : ''}`
  if (status === 'running') return <Loader2 className={className} aria-hidden />
  if (status === 'failed' || status === 'timed_out') return <CircleAlert className={`${className} is-error`} aria-hidden />
  if (status === 'completed' || status === 'ok') return <Check className={className} aria-hidden />
  return <Clock3 className={className} aria-hidden />
}

export function RunActivity({ items, active, followLatest = true }: { items: StepFlowItem[]; active: boolean; followLatest?: boolean }): ReactElement {
  const { t } = useTranslation('common')
  const groups = useMemo(() => groupRunActivity(items), [items])
  // Explicit disclosure choices always win over the compact default.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const recentIds = useRef<Set<string> | null>(null)
  if (followLatest || !recentIds.current) recentIds.current = new Set(groups.slice(-1).map((group) => group.id))
  const visibleIds = recentIds.current
  if (!groups.length) return <p className="ds-run-empty">{t(active ? 'subagentStepFlowWaiting' : 'stepFlowEmpty')}</p>
  return (
    <div className="ds-run-activity">
      {groups.map((group, index) => {
        const hasError = group.actions.some((item) => item.status === 'failed')
        const open = expanded[group.id] ?? (active && visibleIds.has(group.id))
        const text = group.narration?.output || group.narration?.label || ''
        const count = runActionCount(group.actions)
        return (
          <section key={group.id} className={`ds-run-phase ${open ? 'is-open' : ''}`}>
            <button
              type="button"
              className="ds-run-phase-toggle"
              aria-expanded={open}
              aria-label={t(open ? 'runPanelFoldPhase' : 'runPanelExpandPhase', { index: index + 1 })}
              onClick={() => setExpanded((prev) => ({ ...prev, [group.id]: !open }))}
            >
              <ChevronRight className="ds-run-chevron" aria-hidden />
              <span className="ds-run-phase-heading"><span className="ds-run-phase-label">{t('runPanelUpdate', { index: index + 1 })}</span><span className="ds-run-phase-preview">{text.replace(/[`#*_]/g, '').replace(/\s+/g, ' ').trim() || t('runPanelActions')}</span></span>
              {count > 0 ? <span className="ds-run-phase-count">{t('runPanelActionCount', { count })}</span> : null}
              {hasError ? <CircleAlert className="ds-run-state-icon is-error" aria-hidden /> : null}
            </button>
            {open ? (
              <div className="ds-run-phase-body">
                {text ? <div className="ds-run-narration ds-markdown ds-markdown--answer"><StreamdownAssistant text={text} streaming={false} /></div> : null}
                {group.actions.length > 0 ? (
                  <div className="ds-run-actions">
                    {group.actions.map((item) => <RunAction key={item.id} item={item} />)}
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>
        )
      })}
    </div>
  )
}

function RunAction({ item }: { item: StepFlowItem }): ReactElement {
  const { t } = useTranslation('common')
  const name = item.batchToolName || item.toolName
  const kind = probeToolKind(name)
  const Icon = kind === 'web' ? Globe2 : kind === 'command' ? Terminal : kind === 'search' || kind === 'grep' ? Search : FileText
  const count = item.batchCount ?? 1
  const label = item.batchMixed && item.batchCompose
    ? probeComposeSegments(item.batchCompose).map((part) => t(part.key, { count: part.count })).join(' · ')
    : item.variant === 'batch' ? humanizeToolName(name || '') || item.label : item.label
  const target = runActionTargets(item)
  const hasDetail = !!(item.input || item.output || item.batchEntries?.length)
  return (
    <details className="ds-run-action" data-status={item.status}>
      <summary className="ds-run-action-summary" aria-disabled={!hasDetail} onClick={(event) => { if (!hasDetail) event.preventDefault() }}>
        {item.status === 'running' || item.status === 'failed' ? <RunStateIcon status={item.status} /> : <Icon className="ds-run-action-icon" aria-hidden />}
        <span className="ds-run-action-name">{label}{count > 1 ? <span className="ds-run-action-number">{count}</span> : null}</span>
        {target ? <span className="ds-run-target" title={target}>{target}</span> : null}
        {hasDetail ? <ChevronRight className="ds-run-chevron" aria-hidden /> : null}
      </summary>
      {hasDetail ? (
        <div className="ds-run-action-detail">
          {item.batchEntries?.length ? (
            <ul className="ds-run-target-list">
              {item.batchEntries.map((entry, index) => <li key={`${index}:${entry.target}`}><span>{humanizeToolName(entry.toolName)}</span><code>{entry.target}</code></li>)}
            </ul>
          ) : null}
          {item.input ? <div><h4>{t('stepFlowInput')}</h4><pre>{item.input}</pre></div> : null}
          {item.output && !item.batchEntries?.length ? <div><h4>{t('stepFlowOutput')}</h4><pre>{item.output}</pre></div> : null}
        </div>
      ) : null}
    </details>
  )
}
