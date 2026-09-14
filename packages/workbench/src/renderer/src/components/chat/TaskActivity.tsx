import { useId, useState, type ReactElement } from 'react'
import { Check, ChevronRight, CircleAlert, Clock3, ListChecks, Minus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { subagentListTitle, type DockSubagentItem } from '../../lib/extract-subagents-from-blocks'
import { taskListTitle, type TaskItemView } from '../../lib/extract-tasks-from-blocks'
import { isRunActive, runDisplayTitle, runStatusKey } from '../../lib/run-activity'
import type { RunTarget } from '../../store/run-panel-store'
import './task-activity.css'

type Props = {
  tasks: TaskItemView[]
  agents: DockSubagentItem[]
  onOpen: (target: Omit<RunTarget, 'threadId'>) => void
}

function StatusMark({ status, animate = false }: { status?: string; animate?: boolean }): ReactElement {
  const Icon = status === 'completed' ? Check
    : status === 'failed' || status === 'timed_out' ? CircleAlert
      : status === 'queued' || status === 'pending' ? Clock3
        : status ? Minus : ListChecks
  return (
    <span className="ds-task-activity-mark" data-status={status} data-animate={animate} aria-hidden>
      {status === 'running' ? <span className="ds-task-activity-orbit" /> : <Icon />}
    </span>
  )
}

export function TaskActivity({ tasks, agents, onOpen }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [expanded, setExpanded] = useState(false)
  const listId = useId()
  const items = [
    ...tasks.map((task) => ({ kind: 'task' as const, id: task.id, status: task.status, title: runDisplayTitle(taskListTitle(task, Infinity)) })),
    ...agents.map((agent) => ({ kind: 'subagent' as const, id: agent.agentId, status: agent.status, title: runDisplayTitle(subagentListTitle(agent, Infinity)) }))
  ]
  const first = items[0]
  const multiple = items.length > 1
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
  const activeItems = items.filter((item) => isRunActive(item.status))
  const titles = (activeItems.length ? activeItems : items).slice(0, 2).map((item) => item.title).join(' · ')
  const summary = !first ? t('contextRailEmptyTasks') : !multiple
    ? t(first.kind === 'task' ? 'taskActivityBackground' : 'taskActivitySubagent')
    : failed && (running || queued)
      ? `${t('taskActivityCountStatus', { count: failed, status: t('contextRailTaskStatusFailed') })} · ${titles}`
      : titles

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
          <span className="ds-task-activity-title">{multiple ? t('taskActivityParallel') : first?.title || t('contextRailTasks')}</span>
          <span className="ds-task-activity-summary" data-attention={failed > 0 && (running > 0 || queued > 0)}>{summary}</span>
        </span>
        <span className="ds-task-activity-status" data-status={status} role="status">{statusText}</span>
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
