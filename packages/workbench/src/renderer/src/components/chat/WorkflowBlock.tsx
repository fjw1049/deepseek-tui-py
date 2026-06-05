import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { WorkflowSnapshotPayload } from '../../lib/workflow-snapshot'

const STATUS_ICON: Record<string, string> = {
  running: '●',
  done: '✓',
  error: '✗',
  skipped: '−',
  queued: '○'
}

export function WorkflowBlock({
  workflowName,
  status,
  snapshot
}: {
  workflowName: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  snapshot: WorkflowSnapshotPayload
}): ReactElement {
  const { t } = useTranslation('common')
  const header =
    status === 'completed'
      ? t('workflowCompleted', { defaultValue: 'Workflow completed' })
      : status === 'cancelled'
        ? t('workflowCancelled', { defaultValue: 'Workflow cancelled' })
        : status === 'failed'
          ? t('workflowFailed', { defaultValue: 'Workflow failed' })
          : t('workflowRunning', { defaultValue: 'Workflow running' })

  const stateLine =
    snapshot.error_count > 0
      ? t('workflowErrors', {
          defaultValue: '{{done}}/{{total}} done, {{errors}} errors',
          done: snapshot.done_count,
          total: snapshot.agent_count,
          errors: snapshot.error_count
        })
      : snapshot.running_count > 0
        ? t('workflowActive', {
            defaultValue: '{{done}}/{{total}} done, {{running}} running',
            done: snapshot.done_count,
            total: snapshot.agent_count,
            running: snapshot.running_count
          })
        : t('workflowProgress', {
            defaultValue: '{{done}}/{{total}} done',
            done: snapshot.done_count,
            total: snapshot.agent_count
          })

  const agentsByPhase = new Map<string, typeof snapshot.agents>()
  for (const agent of snapshot.agents) {
    const list = agentsByPhase.get(agent.phase_id) ?? []
    list.push(agent)
    agentsByPhase.set(agent.phase_id, list)
  }

  const phaseOrder =
    snapshot.phases.length > 0 ? snapshot.phases : [...agentsByPhase.keys()]

  return (
    <div className="rounded-[22px] border border-sky-300/50 bg-[linear-gradient(180deg,rgba(14,165,233,0.05),rgba(14,165,233,0.12))] px-4 py-4 text-[13px] leading-6 text-ds-ink shadow-[0_12px_30px_rgba(86,103,136,0.04)] dark:border-sky-800/50">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="font-semibold text-sky-800 dark:text-sky-200">{header}</div>
        <span className="font-mono text-[11px] text-ds-faint">{workflowName}</span>
      </div>
      <p className="mt-1 text-[12px] text-ds-muted">
        ◆ {snapshot.name} ({stateLine})
      </p>
      {snapshot.current_phase ? (
        <p className="mt-1 text-[12px] text-ds-faint">
          {t('workflowCurrentPhase', {
            defaultValue: 'Phase: {{phase}}',
            phase: snapshot.current_phase
          })}
        </p>
      ) : null}
      <div className="mt-3 space-y-2">
        {phaseOrder.map((phaseId) => {
          const agents = agentsByPhase.get(phaseId) ?? []
          if (!agents.length) return null
          const done = agents.filter((a) => a.status === 'done').length
          return (
            <div key={phaseId}>
              <div className="text-[12px] font-medium text-ds-muted">
                ✓ {phaseId} {done}/{agents.length}
              </div>
              <ul className="mt-1 space-y-0.5 pl-2">
                {agents.map((agent) => (
                  <li
                    key={`${agent.step_id}-${agent.label}`}
                    className="truncate font-mono text-[11px] text-ds-ink"
                    title={agent.result_preview ?? agent.error ?? undefined}
                  >
                    {STATUS_ICON[agent.status] ?? '○'} {agent.label}
                    {agent.error ? (
                      <span className="text-red-600 dark:text-red-400"> — {agent.error}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
      {snapshot.logs.length > 0 ? (
        <div className="mt-2 border-t border-ds-border/60 pt-2">
          {snapshot.logs.slice(-3).map((line, index) => (
            <p key={`log-${index}`} className="truncate font-mono text-[10px] text-ds-faint">
              log: {line}
            </p>
          ))}
        </div>
      ) : null}
      {snapshot.result != null && status === 'completed' ? (
        <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-ds-hover/80 p-2 font-mono text-[10px] text-ds-muted">
          {typeof snapshot.result === 'string'
            ? snapshot.result
            : JSON.stringify(snapshot.result, null, 2)}
        </pre>
      ) : null}
    </div>
  )
}
