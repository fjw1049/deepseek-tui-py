import { useId, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import { FeedbackNotice } from '../FeedbackNotice'
import { ApprovalBubble } from './ApprovalBubble'
import { ElevationBubble } from './ElevationBubble'
import { UserInputBubble } from './UserInputBubble'

type Decision = Extract<ChatBlock, { kind: 'approval' | 'elevation' | 'user_input' | 'evolution' }>

export function PendingDecisionPanel({ blocks }: { blocks: ChatBlock[] }): ReactElement | null {
  const { t } = useTranslation('common')
  const refresh = useChatStore((s) => s.refreshPendingUserInputs)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(true)
  const [checking, setChecking] = useState(false)
  const panelId = useId()
  const decisions = blocks.filter((block): block is Decision =>
    (block.kind === 'approval' || block.kind === 'elevation' || block.kind === 'user_input' || block.kind === 'evolution') &&
    ((block.status === 'error' && !!block.submissionFailed) || (block.kind !== 'evolution' && block.status === 'pending'))
  )
  if (!decisions.length) return null
  const selected = decisions.find((block) => block.id === selectedId) ?? decisions.find((block) => block.status === 'error') ?? decisions[0]
  const label = (block: Decision): string => block.status === 'error' ? t('feedbackSubmissionUncertain')
    : t(block.kind === 'user_input' ? 'feedbackInputRequired' : 'feedbackPermissionRequired')
  const context = (block: Decision): string => (block.kind === 'user_input'
    ? block.questions[0]?.question ?? '' : block.kind === 'elevation' ? block.reason : block.summary).slice(0, 60)

  return (
    <section aria-label={t('feedbackPendingCount', { count: decisions.length })} className="ds-no-drag mb-2 min-w-0 rounded-xl border border-ds-border bg-ds-card">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button type="button" className="min-h-8 rounded text-left text-[13px] font-medium text-ds-ink" aria-expanded={expanded} aria-controls={panelId} onClick={() => setExpanded(!expanded)}>
          {t('feedbackPendingCount', { count: decisions.length })} · {t(expanded ? 'feedbackCollapse' : 'feedbackExpand')}
        </button>
        {decisions.length > 1 ? <select aria-label={t('feedbackSelectPending')} value={selected.id} className="min-h-8 min-w-0 max-w-full flex-1 rounded-lg border border-ds-border bg-ds-card px-2 text-[12px] text-ds-ink" onChange={(event) => { setSelectedId(event.target.value); setExpanded(true) }}>
          {decisions.map((block, index) => <option key={block.id} value={block.id}>{index + 1}. {label(block)}{context(block) ? ` · ${context(block)}` : ''}</option>)}
        </select> : null}
      </div>
      <div id={panelId} hidden={!expanded} className="ds-scroll-surface max-h-[min(320px,40vh)] overflow-y-auto overscroll-contain px-2 pb-2">
        {/* Keep drafts mounted while switching between requests. */}
        {decisions.map((block) => <div key={block.id} hidden={selected.id !== block.id}>
          {block.status === 'error' ? <FeedbackNotice tone="warning" title={t('feedbackSubmissionUncertain')} message={t('decisionSubmissionUncertain')} details={block.errorMessage} actions={
            <button type="button" disabled={checking} className="min-h-8 rounded-lg bg-ds-ink px-3 py-1 text-[12px] font-medium text-ds-card disabled:opacity-50" onClick={() => {
              setChecking(true)
              void refresh().finally(() => setChecking(false))
            }}>{t(checking ? 'decisionChecking' : 'decisionCheckStatus')}</button>
          } /> : block.kind === 'approval' ? <ApprovalBubble block={block} /> : block.kind === 'elevation' ? <ElevationBubble block={block} /> : block.kind === 'user_input' ? <UserInputBubble block={block} /> : null}
        </div>)}
      </div>
    </section>
  )
}
