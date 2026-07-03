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
  const [listExpanded, setListExpanded] = useState(true)

  useEffect(() => {
    if (session.isComplete) {
      setCompletedExpanded(true)
    }
  }, [session.isComplete])

  useEffect(() => {
    setListExpanded(true)
  }, [session.anchorBlockId])

  const statusLabel = session.isComplete
    ? t('todoInlineDone', { count })
    : active
      ? t('todoInlineWorking', { count })
      : t('todoInlineInProgress')

  const showCompletedFold = completedItems.length > 0 && openItems.length > 0
  const currentItem = session.items.find((item) => item.id === session.inProgressId)
  const latestCompleted = completedItems[completedItems.length - 1]
  const previewItem = currentItem ?? latestCompleted

  return (
    <section
      id={`todo-session-${session.anchorBlockId}`}
      className={`my-2 overflow-hidden rounded-[12px] border border-ds-border bg-ds-card/70 shadow-[0_10px_28px_rgba(86,103,136,0.04)] ${className}`.trim()}
    >
      <button
        type="button"
        onClick={() => setListExpanded((value) => !value)}
        aria-expanded={listExpanded}
        className="group flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-ds-hover/40"
      >
        <span
          className={[
            'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold',
            session.isComplete
              ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
              : active
                ? 'bg-accent/10 text-accent'
                : 'bg-ds-hover text-ds-muted'
          ].join(' ')}
          aria-hidden
        >
          {session.isComplete ? '✓' : completedCount}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-[14px] font-semibold text-ds-ink">{t('todoInlineTitle')}</span>
            <span
              className={[
                'text-[13.5px] font-medium',
                session.isComplete
                  ? 'text-emerald-600/85 dark:text-emerald-300/85'
                  : 'text-ds-faint',
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
          </span>
          {!listExpanded && previewItem ? (
            <span className="mt-1 block truncate text-[13px] text-ds-muted">
              {currentItem
                ? t('todoInlineCurrent', { item: currentItem.content })
                : t('todoInlineLatestDone', { item: previewItem.content })}
            </span>
          ) : null}
        </span>
        {listExpanded ? (
          <ChevronDown className="mt-1 h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight
            className="mt-1 h-3.5 w-3.5 shrink-0 opacity-40 transition group-hover:opacity-65"
            strokeWidth={1.8}
          />
        )}
      </button>

      {listExpanded ? (
        <div className="border-t border-ds-border-muted/60 px-4 py-3">
          {openItems.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {openItems.map((item) => (
                <TodoItemRow key={`${item.id}-${item.content}`} item={item} />
              ))}
            </ul>
          ) : null}

          {showCompletedFold ? (
            <div className="mt-1 flex flex-col gap-1">
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
      ) : null}
    </section>
  )
}
