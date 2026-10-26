import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { SquareGrid } from './SquareGrid'

export type TurnActivityKind = 'Waiting' | 'Thinking' | 'Responding' | 'Browser' | 'Desktop' | 'Tool' | 'User' | 'Subagent'

/** UI surfaces the agent drives directly (mirrors src/deepseek_tui/surfaces.py), in priority order. */
const SURFACE_ACTIVITY: ReadonlyArray<[string, TurnActivityKind]> = [
  ['browser_use', 'Browser'],
  // The agent is driving the user's real mouse and keyboard: say so plainly.
  ['cua_js', 'Desktop'],
  ['cua_observe', 'Desktop']
]

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
  const latest = blocks.at(-1)
  if (latest?.kind === 'system' && /^Waiting on \d+ sub-agent\(s\) to complete\.\.\.$/.test(latest.text)) {
    return 'Subagent'
  }
  const running = blocks.filter((block) => block.kind === 'tool' && block.status === 'running')
  for (const [toolName, activity] of SURFACE_ACTIVITY) {
    if (running.some((block) => block.kind === 'tool' && block.meta?.tool_name === toolName)) return activity
  }
  return running.length ? 'Tool' : 'Waiting'
}

/** The running desktop call's own step title, so a long task shows which step it is on. */
export function resolveTurnActivityStep(blocks: ChatBlock[]): string | null {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i]
    if (block.kind !== 'tool' || block.status !== 'running' || block.meta?.tool_name !== 'cua_js') continue
    const input = block.meta.tool_input
    const title = input && typeof input === 'object' ? (input as { title?: unknown }).title : undefined
    return typeof title === 'string' && title.trim() ? title.trim() : null
  }
  return null
}

export function TurnActivity({ activity, step = null }: {
  activity: TurnActivityKind | null
  step?: string | null
}): React.ReactElement | null {
  const { t } = useTranslation('common')
  if (!activity) return null
  return <div role="status" aria-live="polite" aria-atomic="true" data-turn-activity={activity}
    className="flex items-center gap-2 py-1 text-[13px] leading-5 text-ds-faint">
    {activity !== 'User' ? <SquareGrid className="shrink-0" /> : null}
    <span className="min-w-0 truncate">{t(`turnActivity${activity}`)}{step ? ` · ${step}` : ''}</span>
  </div>
}
