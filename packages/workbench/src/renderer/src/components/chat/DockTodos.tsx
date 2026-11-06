import { useState } from 'react'
import { Check, ChevronRight, ListTodo, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TodoItemView } from '../../lib/extract-todos-from-blocks'

const DOCK_SECTION_HEADER_CLASS = 'group flex w-full items-center gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left text-ds-muted transition-colors hover:text-ds-ink'

export function DockTodos({ todos, collapsed, onToggle }: { todos: TodoItemView[]; collapsed: boolean; onToggle: () => void }): React.JSX.Element {
  const { t } = useTranslation('common')
  const [expandedTodoKey, setExpandedTodoKey] = useState<string | null>(null)
  const totalCount = todos.length
  const doneCount = todos.filter((item) => item.status === 'completed').length
  return <>      {todos.length > 0 ? (
      <div className="ds-operation-dock-status__section">
      <button
        type="button"
        onClick={() => onToggle()}
        aria-expanded={!collapsed}
        className={DOCK_SECTION_HEADER_CLASS}
      >
        <ListTodo className="h-4 w-4 shrink-0 text-ds-muted" strokeWidth={1.75} aria-hidden />
        <span className="ds-operation-dock-section-label min-w-0 flex-1">
          {t('contextRailProcess')}
        </span>
        {totalCount > 0 ? (
          <span className="text-[12px] tabular-nums text-ds-muted">
            {doneCount}/{totalCount}
          </span>
        ) : null}
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform duration-200 ${
            collapsed ? '' : 'rotate-90'
          }`}
          strokeWidth={2}
          aria-hidden
        />
      </button>

      {!collapsed ? (
        totalCount > 0 ? (
          <ul className="mt-1 flex max-h-80 flex-col gap-0.5 overflow-y-auto overflow-x-hidden [scrollbar-width:thin]">
            {todos.map((item, index) => {
              const completed = item.status === 'completed'
              const cancelled = item.status === 'cancelled'
              const inProgress = item.status === 'in_progress'
              const step = index + 1
              const rowKey = item.id
              const expanded = expandedTodoKey === rowKey
              return (
                <li key={rowKey}>
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedTodoKey((current) => (current === rowKey ? null : rowKey))
                    }
                    aria-expanded={expanded}
                    title={expanded ? undefined : item.content}
                    className={[
                      'flex min-h-8 w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors',
                      'hover:bg-ds-hover/50',
                      inProgress ? 'bg-ds-hover/60' : ''
                    ].join(' ')}
                  >
                    <span
                      className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center"
                      aria-hidden
                    >
                      {cancelled ? <X className="h-4 w-4 text-ds-faint" /> : completed ? (
                        <span className="flex h-5 w-5 items-center justify-center text-ds-faint">
                          <Check className="h-4 w-4" strokeWidth={2} />
                        </span>
                      ) : (
                        <span
                          className={[
                            'flex h-5 w-5 items-center justify-center rounded-full text-[12px] font-medium tabular-nums',
                            inProgress
                              ? 'bg-accent/10 text-accent'
                              : 'text-ds-faint'
                          ].join(' ')}
                        >
                          {step}
                        </span>
                      )}
                    </span>
                    <span
                      className={[
                        'min-w-0 flex-1 text-[13px] leading-5',
                        cancelled ? 'line-through' : '',
                        expanded ? 'break-words whitespace-pre-wrap' : 'truncate',
                        completed
                          ? 'text-ds-muted'
                          : inProgress
                            ? 'font-medium text-ds-ink'
                            : 'text-ds-muted'
                      ].join(' ')}
                    >
                      <span className="sr-only">{t(`todoInlineStatus_${item.status}`)}: </span>{item.content}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="mt-1 text-[13px] leading-5 text-ds-faint">{t('contextRailEmptyProcess')}</p>
        )
      ) : null}
      </div>
      ) : null}

</>
}
