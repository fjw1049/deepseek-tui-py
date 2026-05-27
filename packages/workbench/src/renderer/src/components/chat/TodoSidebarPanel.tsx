import type { ReactElement } from 'react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { extractTodosFromBlocks } from '../../lib/extract-todos-from-blocks'

type Props = {
  blocks: ChatBlock[]
  className?: string
}

function statusGlyph(status: 'pending' | 'in_progress' | 'completed'): string {
  if (status === 'completed') return '✓'
  if (status === 'in_progress') return '◔'
  return '○'
}

export function TodoSidebarPanel({ blocks, className = '' }: Props): ReactElement {
  const { t } = useTranslation('common')
  const snapshot = useMemo(() => extractTodosFromBlocks(blocks), [blocks])

  return (
    <aside
      className={`ds-no-drag ds-todo-rail flex min-h-0 w-[168px] shrink-0 flex-col ${className}`}
    >
      <div className="flex items-center gap-1.5 px-1 pb-2 pt-1">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ds-faint">
          {t('todoSidebarTitle')}
        </span>
        {snapshot ? (
          <span className="ml-auto text-[11px] font-medium tabular-nums text-ds-faint">
            {snapshot.completionPct}%
          </span>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-2">
        {!snapshot || snapshot.items.length === 0 ? (
          <p className="py-4 text-[12px] leading-5 text-ds-faint">{t('todoSidebarEmpty')}</p>
        ) : (
          <ul className="space-y-1.5">
            {snapshot.items.map((item) => {
              const active = snapshot.inProgressId === item.id || item.status === 'in_progress'
              const completed = item.status === 'completed'
              return (
                <li
                  key={`${item.id}-${item.content}`}
                  className={[
                    'text-[12px] leading-5',
                    completed ? 'text-ds-faint' : active ? 'text-ds-ink' : 'text-ds-muted'
                  ].join(' ')}
                >
                  <div className="flex items-start gap-1.5">
                    <span
                      className={[
                        'mt-0.5 shrink-0 text-[10px] font-semibold',
                        completed
                          ? 'text-emerald-600/80 dark:text-emerald-300/80'
                          : active
                            ? 'text-accent'
                            : 'text-ds-faint'
                      ].join(' ')}
                      aria-hidden
                    >
                      {statusGlyph(item.status)}
                    </span>
                    <span className="min-w-0 break-words">{item.content}</span>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </aside>
  )
}
