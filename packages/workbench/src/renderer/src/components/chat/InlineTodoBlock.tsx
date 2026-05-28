import type { ReactElement } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TodoItemView, TodoTurnSession } from '../../lib/extract-todos-from-blocks'

type Props = {
  session: TodoTurnSession
  active?: boolean
  className?: string
}

function statusGlyph(status: TodoItemView['status']): string {
  if (status === 'completed') return '☑'
  if (status === 'in_progress') return '◔'
  return '☐'
}

function TodoItemRow({ item }: { item: TodoItemView }): ReactElement {
  const completed = item.status === 'completed'
  const inProgress = item.status === 'in_progress'

  return (
    <li
      className={[
        'flex items-start gap-2 text-[14px] leading-6',
        completed ? 'text-ds-faint' : inProgress ? 'text-ds-ink' : 'text-ds-muted'
      ].join(' ')}
    >
      <span
        className={[
          'mt-1 shrink-0 text-[13px] font-semibold',
          completed
            ? 'text-emerald-600/85 dark:text-emerald-300/85'
            : inProgress
              ? 'text-accent'
              : 'text-ds-faint'
        ].join(' ')}
        aria-hidden
      >
        {statusGlyph(item.status)}
      </span>
      <span className="min-w-0 break-words">{item.content}</span>
    </li>
  )
}

export function InlineTodoBlock({ session, active = false, className = '' }: Props): ReactElement {
  const { t } = useTranslation('common')
  const count = session.items.length
  const completedCount = session.items.filter((item) => item.status === 'completed').length
  const { openItems, completedItems } = useMemo(() => {
    const open: TodoItemView[] = []
    const done: TodoItemView[] = []
    for (const item of session.items) {
      if (item.status === 'completed') done.push(item)
      else open.push(item)
    }
    return { openItems: open, completedItems: done }
  }, [session.items])

  const [completedExpanded, setCompletedExpanded] = useState(() => session.isComplete)

  useEffect(() => {
    if (session.isComplete) {
      setCompletedExpanded(true)
    }
  }, [session.isComplete])

  const statusLabel = session.isComplete
    ? t('todoInlineDone', { count })
    : active
      ? t('todoInlineWorking', { count })
      : t('todoInlineInProgress')

  const showCompletedFold = completedItems.length > 0 && openItems.length > 0

  return (
    <div className={`my-2 flex flex-col gap-1.5 ${className}`.trim()}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-[14px] font-semibold text-ds-ink">{t('todoInlineTitle')}</span>
        <span
          className={[
            'text-[13.5px] font-medium',
            session.isComplete ? 'text-emerald-600/85 dark:text-emerald-300/85' : 'text-ds-faint',
            active && !session.isComplete ? 'ds-shiny-text' : ''
          ].join(' ')}
        >
          {statusLabel}
        </span>
        {count > 0 ? (
          <span className="text-[13px] tabular-nums text-ds-faint">
            {t('todoInlineProgress', { done: completedCount, total: count })}
          </span>
        ) : null}
      </div>

      {openItems.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {openItems.map((item) => (
            <TodoItemRow key={`${item.id}-${item.content}`} item={item} />
          ))}
        </ul>
      ) : null}

      {showCompletedFold ? (
        <div className="flex flex-col gap-1">
          <button
            type="button"
            onClick={() => setCompletedExpanded((value) => !value)}
            aria-expanded={completedExpanded}
            className="group flex w-fit max-w-full items-center gap-1 rounded-md py-0.5 text-left text-[13.5px] font-medium text-ds-faint transition hover:text-ds-muted"
          >
            {completedExpanded ? (
              <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-55" strokeWidth={1.8} />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
            )}
            <span>{t('todoInlineCompletedFold', { count: completedItems.length })}</span>
          </button>
          {completedExpanded ? (
            <ul className="flex flex-col gap-1 border-l-2 border-ds-border-muted/35 pl-3">
              {completedItems.map((item) => (
                <TodoItemRow key={`${item.id}-${item.content}`} item={item} />
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {!showCompletedFold && completedItems.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {completedItems.map((item) => (
            <TodoItemRow key={`${item.id}-${item.content}`} item={item} />
          ))}
        </ul>
      ) : null}
    </div>
  )
}
