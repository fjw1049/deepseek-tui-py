import { useEffect, useId, useState, type ReactElement } from 'react'
import { ChevronRight, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { subagentListTitle, type DockSubagentItem } from '../../lib/extract-subagents-from-blocks'
import { taskListTitle, type TaskItemView } from '../../lib/extract-tasks-from-blocks'
import { runDisplayTitle, runStatusKey } from '../../lib/run-activity'
import type { RunTarget } from '../../store/run-panel-store'
import { humanizeAgentType } from '../../lib/agent-type-label'
import { RunStatusMark } from './RunStatusMark'
import './task-activity.css'

type Props = {
  tasks: TaskItemView[]
  agents: DockSubagentItem[]
  onOpen: (target: Omit<RunTarget, 'threadId'>) => void
  /** Hidden from the list but still counted, so numbers match the full list. */
  exclude?: Omit<RunTarget, 'threadId'>
}

export function TaskActivity({ tasks, agents, onOpen, exclude }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const listId = useId()
  // Number each label on its own (code 1, explore 1, code 2) in list order.
  const counts = new Map<string, number>()
  const numbered = (label: string): string => {
    const count = (counts.get(label) ?? 0) + 1
    counts.set(label, count)
    return `${label} ${count}`
  }
  const items = [
    ...tasks.map((task) => ({ kind: 'task' as const, id: task.id, status: task.status, title: numbered(t('taskActivityBackground')), summary: runDisplayTitle(taskListTitle(task, Infinity)) })),
    ...agents.map((agent) => ({ kind: 'subagent' as const, id: agent.agentId, status: agent.status, title: numbered(humanizeAgentType(agent.agentType) || subagentListTitle({ ...agent, prompt: undefined })), summary: runDisplayTitle(subagentListTitle(agent, Infinity)) }))
  ].filter((item) => !(exclude && item.kind === exclude.kind && item.id === exclude.id))
  const first = items[0]
  const multiple = items.length > 1
  // The list only renders while multiple; without this reset a stale
  // `expanded=true` survives a 1-item dip and the next click folds a list the
  // user never saw open ("点没反应，再点就折叠了").
  useEffect(() => {
    if (!multiple) setExpanded(false)
  }, [multiple])
  // ponytail: hide the whole section when there are no tasks/agents — an empty
  // "暂无任务" card is noise. Reappears automatically once a task exists.
  if (!first) return null
  const running = items.filter((item) => item.status === 'running').length
  const queued = items.filter((item) => item.status === 'queued' || item.status === 'pending').length
  const failed = items.filter((item) => item.status === 'failed' || item.status === 'timed_out').length
  const stopped = items.filter((item) => item.status === 'canceled' || item.status === 'cancelled').length
  const status = !multiple ? first?.status : running ? 'running' : queued ? 'queued'
    : failed ? 'failed' : stopped ? 'canceled' : 'completed'
  const title = multiple
    ? t(items.some((item) => item.kind === 'task') ? 'taskActivityTasksCount' : 'taskActivityAgentsCount', { count: items.length })
    : first.title
  const statusText = multiple
    ? ['running', 'queued', 'completed', 'failed', 'canceled', 'timed_out'].flatMap((value) => {
      const count = items.filter((item) => (item.status === 'pending' ? 'queued' : item.status === 'cancelled' ? 'canceled' : item.status) === value).length
      return count ? [t('taskActivityCountStatus', { count, status: t(runStatusKey(value)) })] : []
    }).join(' · ')
    : first ? t(runStatusKey(status)) : ''

  return (
    <section className="ds-operation-dock-status__section ds-task-activity" aria-label={t('contextRailTasks')}>
      <button
        type="button"
        className="ds-task-activity-trigger"
        disabled={!first}
        aria-expanded={multiple ? expanded : undefined}
        aria-controls={multiple ? listId : undefined}
        title={`${!multiple && first.summary ? first.summary : title} · ${statusText}`}
        aria-label={`${title} · ${statusText}`}
        onClick={() => {
          if (multiple) setExpanded((value) => !value)
          else if (first) onOpen({ kind: first.kind, id: first.id })
        }}
      >
        {multiple && !running && !queued ? <Users className="h-4 w-4 shrink-0 text-ds-muted" strokeWidth={1.75} aria-hidden /> : <RunStatusMark status={status} />}
        <span className="ds-task-activity-heading">
          <span className="ds-task-activity-title">
            {title}
          </span>
        </span>
        {multiple ? (
          <span className={`ds-task-activity-status ${failed > 0 ? 'text-ds-danger' : ''}`}>
            {failed > 0 ? t('taskActivityCountStatus', { count: failed, status: t(runStatusKey('failed')) }) : t(runStatusKey(status))}
          </span>
        ) : null}
        {stopped > 0 && status !== 'canceled' && status !== 'cancelled' ? <RunStatusMark status="canceled" /> : null}
        {first ? <ChevronRight className="ds-task-activity-chevron" aria-hidden /> : null}
      </button>
      {multiple ? (
        <section id={listId} className="ds-task-activity-body" data-expanded={expanded} aria-hidden={!expanded} inert={!expanded}>
          <div className="ds-task-activity-clip">
            <ul className="ds-task-activity-list">
              {items.map((item) => (
                <li key={`${item.kind}:${item.id}`}>
                  <button type="button" className="ds-task-activity-row" title={`${item.summary || item.title} · ${t(item.kind === 'task' ? 'taskActivityBackground' : 'taskActivitySubagent')} · ${t(runStatusKey(item.status))}`} onClick={() => onOpen({ kind: item.kind, id: item.id })}>
                    <RunStatusMark status={item.status} />
                    <span className="ds-task-activity-heading">
                      <span className="ds-task-activity-title">{item.title}</span>
                    </span>
                    <ChevronRight className="ds-task-activity-chevron" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}
    </section>
  )
}
