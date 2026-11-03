import { useMemo, useState } from 'react'
import { DockTodos } from '../chat/DockTodos'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { extractTodosFromBlocks } from '../../lib/extract-todos-from-blocks'
import { extractTasksFromBlocks } from '../../lib/extract-tasks-from-blocks'
import { extractSubagentsFromBlocks } from '../../lib/extract-subagents-from-blocks'
import { useRunPanelStore, type RunTarget } from '../../store/run-panel-store'
import { TaskActivity } from '../chat/TaskActivity'

/** Context belongs to this run's conversation, never the parent chat. */
export function RunContext({ blocks, target }: { blocks: ChatBlock[]; target: RunTarget }): React.JSX.Element | null {
  const { t } = useTranslation('common')
  const open = useRunPanelStore((state) => state.open)
  const [expanded, setExpanded] = useState<boolean | null>(null)
  const todos = useMemo(() => extractTodosFromBlocks(blocks)?.items ?? [], [blocks])
  const tasks = useMemo(() => extractTasksFromBlocks(blocks).filter((item) => target.kind !== 'task' || item.id !== target.id), [blocks, target.kind, target.id])
  const agents = useMemo(() => extractSubagentsFromBlocks(blocks).filter((item) => target.kind !== 'subagent' || item.agentId !== target.id), [blocks, target.kind, target.id])
  if (!todos.length && !tasks.length && !agents.length) return null
  const unfinished = todos.some((item) => item.status === 'pending' || item.status === 'in_progress')
  const showTodos = expanded ?? unfinished
  return (
    <aside className="ds-run-context ds-operation-dock ds-hero-panel ds-glass" aria-label={t('contextRailProcess')}>
      <DockTodos todos={todos} collapsed={!showTodos} onToggle={() => setExpanded(!showTodos)} />
      <TaskActivity tasks={tasks} agents={agents} onOpen={(item) => open({ ...item, threadId: target.threadId })} />
    </aside>
  )
}
