import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { SquareGrid } from './SquareGrid'

export type TurnActivityKind = 'Waiting' | 'Thinking' | 'Responding' | 'Browser' | 'Tool' | 'User'

/** Inputs are projections of runtime events, independent of disclosure/content layout. */
export function resolveTurnActivity({ active, blocks, stream, awaitingBrowserUser = false }: {
  active: boolean
  blocks: ChatBlock[]
  stream: 'thinking' | 'responding' | null
  awaitingBrowserUser?: boolean
}): TurnActivityKind | null {
  if (!active) return null
  if (awaitingBrowserUser || blocks.some((block) =>
    (block.kind === 'approval' || block.kind === 'elevation' || block.kind === 'user_input' ||
      block.kind === 'evolution') && block.status === 'pending')) return 'User'
  if (stream === 'thinking') return 'Thinking'
  if (stream === 'responding') return 'Responding'
  const running = blocks.filter((block) => block.kind === 'tool' && block.status === 'running')
  if (running.some((block) => block.kind === 'tool' && block.meta?.tool_name === 'browser_use')) {
    return 'Browser'
  }
  return running.length ? 'Tool' : 'Waiting'
}

export function TurnActivity({ activity }: { activity: TurnActivityKind | null }): React.ReactElement | null {
  const { t } = useTranslation('common')
  if (!activity) return null
  return <div role="status" aria-live="polite" aria-atomic="true" data-turn-activity={activity}
    className="flex items-center gap-2 py-1 text-[13px] leading-5 text-ds-faint">
    {activity !== 'User' ? <SquareGrid className="shrink-0" /> : null}
    <span>{t(`turnActivity${activity}`)}</span>
  </div>
}
