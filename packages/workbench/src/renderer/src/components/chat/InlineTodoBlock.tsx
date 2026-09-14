import type { ReactElement } from 'react'
import { useId, useState } from 'react'
import { Check, ChevronDown, ListTodo } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TodoItemView, TodoTurnSession } from '../../lib/extract-todos-from-blocks'

type Props = {
  session: TodoTurnSession
  active?: boolean
  className?: string
}

function TodoItemRow({ item, active }: { item: TodoItemView; active: boolean }): ReactElement {
  const { t } = useTranslation('common')
  const completed = item.status === 'completed'
  const cancelled = item.status === 'cancelled'
  const inProgress = item.status === 'in_progress'

  return (
    <li
      className={`ds-inline-todo__row flex items-start gap-2.5 px-1.5 py-1.5 text-[14px] leading-5 ${completed || cancelled ? 'text-ds-faint' : inProgress ? 'text-ds-ink' : 'text-ds-muted'}`}
      data-status={item.status}
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 h-4 w-4 shrink-0">
        <circle cx="12" cy="12" r="9" strokeDasharray={item.status === 'pending' ? '2 3' : undefined} opacity={inProgress ? 0.2 : 0.65} />
        <circle cx="12" cy="12" r="9" strokeDasharray="38 57" className={inProgress && active ? 'ds-inline-todo__spinner' : ''} opacity={inProgress ? 1 : 0} transform="rotate(-90 12 12)" />
        <path d="m7.5 12 3 3 6-6" className="ds-inline-todo__mark" style={{ opacity: completed ? 1 : 0 }} />
        <path d="m9 9 6 6m0-6-6 6" className="ds-inline-todo__mark" style={{ opacity: cancelled ? 1 : 0 }} />
      </svg>
      <span className="sr-only">{t(`todoInlineStatus_${item.status}`)}: </span>
      <span className={`min-w-0 flex-1 [overflow-wrap:anywhere] ${completed || cancelled ? 'line-through decoration-ds-faint' : ''}`}>{item.content}</span>
      {cancelled ? <span className="shrink-0 text-[12px]">{t('todoInlineStatus_cancelled')}</span> : null}
    </li>
  )
}

export function InlineTodoBlock({ session, active = false, className = '' }: Props): ReactElement {
  const { t } = useTranslation('common')
  const contentId = useId()
  const triggerId = `${contentId}-trigger`
  const count = session.items.length
  const completedCount = session.items.filter((item) => item.status === 'completed').length
  const cancelledCount = session.items.filter((item) => item.status === 'cancelled').length
  const allCompleted = count > 0 && completedCount === count
  const [expansion, setExpansion] = useState<{ anchor: string; complete: boolean; expanded: boolean } | null>(null)
  if (expansion && (expansion.anchor !== session.anchorBlockId || expansion.complete !== session.isComplete)) {
    setExpansion(null)
  }
  const listExpanded = expansion?.anchor === session.anchorBlockId && expansion.complete === session.isComplete
    ? expansion.expanded
    : !session.isComplete

  const currentItem = session.items.find((item) => item.id === session.inProgressId)
  const latestCompleted = session.items.filter((item) => item.status === 'completed').at(-1)
  const previewItem = currentItem ?? latestCompleted

  return (
    <section
      id={`todo-session-${session.anchorBlockId}`}
      className={`ds-inline-todo my-2 overflow-hidden rounded-2xl border border-ds-border ${className}`.trim()}
    >
      <button
        id={triggerId}
        type="button"
        onClick={() => setExpansion({ anchor: session.anchorBlockId, complete: session.isComplete, expanded: !listExpanded })}
        aria-expanded={listExpanded}
        aria-controls={contentId}
        className="ds-inline-todo__header group flex min-h-11 w-full items-start gap-2.5 rounded-xl px-3.5 py-3 text-left transition-colors hover:bg-ds-hover focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
      >
        <span className={`flex h-5 w-5 shrink-0 items-center justify-center ${allCompleted ? 'rounded-full bg-emerald-500 text-white' : 'text-ds-muted'}`} aria-hidden="true">
          {allCompleted ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} /> : <ListTodo className="h-4 w-4" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="ds-inline-todo__title block text-[14px] font-medium leading-5 text-ds-ink">{t('todoInlineTitle')}</span>
          {!listExpanded && !session.isComplete && previewItem ? (
            <span className="mt-1 block truncate text-[13px] text-ds-muted" title={previewItem.content}>
              {currentItem ? t('todoInlineCurrent', { item: currentItem.content }) : t('todoInlineLatestDone', { item: previewItem.content })}
            </span>
          ) : null}
        </span>
        <span className={`shrink-0 text-right text-[12px] leading-5 tabular-nums ${allCompleted ? 'text-emerald-600 dark:text-emerald-400' : 'text-ds-muted'}`}>
          <span className="sr-only" role="status">{t('todoInlineProgress', { done: completedCount, total: count })}{cancelledCount > 0 ? `, ${t('todoInlineCancelled', { count: cancelledCount })}` : ''}</span>
          <span aria-hidden="true"><span key={completedCount} className="ds-inline-todo__count inline-block">{completedCount}</span>/{count}</span>
          {cancelledCount > 0 ? <span aria-hidden="true" className="ml-2">{t('todoInlineCancelled', { count: cancelledCount })}</span> : null}
        </span>
        <ChevronDown aria-hidden="true" className={`ds-inline-todo__chevron mt-1 h-3 w-3 shrink-0 text-ds-faint ${listExpanded ? 'rotate-180' : ''}`} strokeWidth={1.8} />
      </button>
      <div id={contentId} role="region" aria-labelledby={triggerId} hidden={!listExpanded}>
        {listExpanded ? (
          <div className="ds-inline-todo__body max-h-[248px] overflow-y-auto px-2 pb-2">
            <ul>
              {session.items.map((item) => <TodoItemRow key={item.id} item={item} active={active && !session.isComplete} />)}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  )
}
