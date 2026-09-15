import { useEffect, useId, useState, type ReactElement } from 'react'
import { ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { subagentListTitle, type DockSubagentItem } from '../../lib/extract-subagents-from-blocks'
import { taskListTitle, type TaskItemView } from '../../lib/extract-tasks-from-blocks'
import { runDisplayTitle, runStatusKey } from '../../lib/run-activity'
import type { RunTarget } from '../../store/run-panel-store'
import './task-activity.css'

type Props = {
  tasks: TaskItemView[]
  agents: DockSubagentItem[]
  onOpen: (target: Omit<RunTarget, 'threadId'>) => void
}

// ponytail: status is a plain dot — green done, red failed, spinning ring while
// running. No glyphs; the color + motion carry the whole state.
function StatusMark({ status, animate = false }: { status?: string; animate?: boolean }): ReactElement {
  return (
    <span className="ds-task-activity-mark" data-status={status} data-animate={animate} aria-hidden>
      {status === 'running' ? <span className="ds-task-activity-orbit" /> : <span className="ds-task-activity-dot" />}
    </span>
  )
}

export function TaskActivity({ tasks, agents, onOpen }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const listId = useId()
  const items = [
    ...tasks.map((task) => ({ kind: 'task' as const, id: task.id, status: task.status, title: runDisplayTitle(taskListTitle(task, Infinity)) })),
    ...agents.map((agent) => ({ kind: 'subagent' as const, id: agent.agentId, status: agent.status, title: runDisplayTitle(subagentListTitle(agent, Infinity)) }))
  ]
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
  const count = running || queued || failed || stopped || items.length
  const statusText = multiple
    ? t('taskActivityCountStatus', { count, status: t(runStatusKey(status)) })
    : first ? t(runStatusKey(status)) : ''

  return (
    <section className="ds-operation-dock-status__section ds-task-activity" aria-label={t('contextRailTasks')}>
      <button
        type="button"
        className="ds-task-activity-trigger"
        disabled={!first}
        aria-expanded={multiple ? expanded : undefined}
        aria-controls={multiple ? listId : undefined}
        title={first ? `${multiple ? t('taskActivityParallel') : first.title} · ${statusText}` : undefined}
        onClick={() => {
          if (multiple) setExpanded((value) => !value)
          else if (first) onOpen({ kind: first.kind, id: first.id })
        }}
      >
        <StatusMark status={status} animate />
        <span className="ds-task-activity-heading">
          <span className="ds-task-activity-title">
            {multiple
              ? t('taskActivityAgentsCount', { count: items.length })
              : t('contextRailAgentGroupTitle')}
          </span>
        </span>
        {first ? <ChevronRight className="ds-task-activity-chevron" aria-hidden /> : null}
      </button>
      {multiple ? (
        <section id={listId} className="ds-task-activity-body" data-expanded={expanded} aria-hidden={!expanded} inert={!expanded}>
          <div className="ds-task-activity-clip">
            <ul className="ds-task-activity-list">
              {items.map((item) => (
                <li key={`${item.kind}:${item.id}`}>
                  <button type="button" className="ds-task-activity-row" title={item.title} onClick={() => onOpen({ kind: item.kind, id: item.id })}>
                    <StatusMark status={item.status} />
                    <span className="ds-task-activity-heading">
                      <span className="ds-task-activity-title">{item.title}</span>
                      <span className="ds-task-activity-summary" data-status={item.status}>
                        {t(item.kind === 'task' ? 'taskActivityBackground' : 'taskActivitySubagent')} · {t(runStatusKey(item.status))}
                      </span>
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
