import { useState, type ReactElement } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { WorkflowSnapshotPayload } from '../../lib/workflow-snapshot'
import { useChatStore } from '../../store/chat-store'

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
  snapshot,
  runId
}: {
  workflowName: string
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'timed_out'
  snapshot: WorkflowSnapshotPayload
  runId?: string
}): ReactElement | null {
  const { t } = useTranslation('common')
  const sendMessage = useChatStore((s) => s.sendMessage)
  const busy = useChatStore((s) => s.busy)
  // Hooks must run unconditionally — early-return on `running` used to skip
  // these useState calls, then crash with "Rendered more hooks" when status
  // flipped to failed/timed_out (white screen).
  const [expanded, setExpanded] = useState(false)
  const [resuming, setResuming] = useState(false)

  // Live progress lives in ProcessTray + the 处理中 tag; keep the timeline calm.
  if (status === 'running') return null

  const header =
    status === 'completed'
      ? t('workflowCompleted', { defaultValue: 'Workflow completed' })
      : status === 'cancelled'
        ? t('workflowCancelled', { defaultValue: 'Workflow cancelled' })
        : status === 'timed_out'
          ? t('workflowTimedOut', { defaultValue: 'Workflow timed out' })
          : t('workflowFailed', { defaultValue: 'Workflow failed' })

  const stateLine =
    snapshot.error_count > 0
      ? t('workflowErrors', {
          defaultValue: '{{done}}/{{total}} done, {{errors}} errors',
          done: snapshot.done_count,
          total: snapshot.agent_count,
          errors: snapshot.error_count
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

  const tone =
    status === 'failed' || status === 'timed_out'
      ? 'border-red-300/50 text-red-800 dark:border-red-800/50 dark:text-red-200'
      : status === 'cancelled'
        ? 'border-ds-border-muted text-ds-muted'
        : 'border-sky-300/40 text-sky-800 dark:border-sky-800/40 dark:text-sky-200'

  const canResume =
    Boolean(runId) &&
    (status === 'cancelled' || status === 'failed' || status === 'timed_out') &&
    !busy &&
    !resuming

  const onResume = async () => {
    if (!runId || !canResume) return
    setResuming(true)
    try {
      const prompt = t('workflowResumePrompt', {
        defaultValue:
          '请用 workflow 工具【只传 run_id】续跑被中断的工作流 {{runId}}。不要重新用 name+task 开新跑；从 checkpoint 跳过已完成步骤继续。',
        runId
      })
      await sendMessage(prompt, 'workflow')
    } finally {
      setResuming(false)
    }
  }

  return (
    <div className={`rounded-[10px] border bg-ds-card/50 text-[12.5px] leading-5 ${tone}`}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left transition hover:bg-ds-hover/40"
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 opacity-45" strokeWidth={1.8} />
        )}
        <span className="min-w-0 flex-1 truncate font-medium">{header}</span>
        <span className="shrink-0 text-[11px] text-ds-faint">{workflowName || snapshot.name}</span>
        <span className="shrink-0 tabular-nums text-[11px] text-ds-faint">{stateLine}</span>
      </button>

      {runId ? (
        <div className="flex items-center gap-2 border-t border-ds-border/40 px-2.5 py-1.5">
          <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-ds-faint">
            {runId}
          </span>
          {status === 'cancelled' || status === 'failed' || status === 'timed_out' ? (
            <button
              type="button"
              disabled={!canResume}
              onClick={(e) => {
                e.stopPropagation()
                void onResume()
              }}
              className="shrink-0 rounded-md border border-ds-border bg-ds-card px-2 py-0.5 text-[11px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-45"
            >
              {resuming
                ? t('workflowResuming', { defaultValue: '续跑中…' })
                : t('workflowResume', { defaultValue: '续跑此 workflow' })}
            </button>
          ) : null}
        </div>
      ) : null}

      {expanded ? (
        <div className="border-t border-ds-border/50 px-3 py-2.5 text-[12px] text-ds-ink">
          <p className="text-ds-muted">
            ◆ {snapshot.name} ({stateLine})
          </p>
          {snapshot.current_phase ? (
            <p className="mt-1 text-[11px] text-ds-faint">
              {t('workflowCurrentPhase', {
                defaultValue: 'Phase: {{phase}}',
                phase: snapshot.current_phase
              })}
            </p>
          ) : null}
          <div className="mt-2 space-y-2">
            {snapshot.nodes && snapshot.nodes.length > 0 ? (
              <div>
                <div className="text-[11.5px] font-medium text-ds-muted">
                  {t('workflowDagProgress', { defaultValue: 'DAG nodes' })}
                  {snapshot.dynamic_rounds && Object.keys(snapshot.dynamic_rounds).length > 0
                    ? ` · dyn ${Object.entries(snapshot.dynamic_rounds)
                        .map(([id, r]) => `${id}@${r}`)
                        .join(', ')}`
                    : ''}
                </div>
                <ul className="mt-1 space-y-0.5 pl-2">
                  {snapshot.nodes.map((node) => (
                    <li
                      key={node.id}
                      className="truncate text-[11px] text-ds-ink"
                      title={
                        node.predecessors && node.predecessors.length
                          ? `after: ${node.predecessors.join(', ')}`
                          : undefined
                      }
                    >
                      {STATUS_ICON[node.status] ?? '○'} {node.label || node.id}
                      <span className="text-ds-faint"> ({node.type})</span>
                      {node.generated ? (
                        <span className="text-ds-faint"> *</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
                {snapshot.edges && snapshot.edges.length > 0 ? (
                  <p className="mt-1 truncate font-mono text-[10px] text-ds-faint">
                    edges:{' '}
                    {snapshot.edges
                      .slice(0, 12)
                      .map((e) => `${e.from}→${e.to}`)
                      .join(' ')}
                    {snapshot.edges.length > 12 ? ' …' : ''}
                  </p>
                ) : null}
              </div>
            ) : (
              phaseOrder.map((phaseId) => {
                const agents = agentsByPhase.get(phaseId) ?? []
                if (!agents.length) return null
                const done = agents.filter((a) => a.status === 'done').length
                return (
                  <div key={phaseId}>
                    <div className="text-[11.5px] font-medium text-ds-muted">
                      ✓ {phaseId} {done}/{agents.length}
                    </div>
                    <ul className="mt-1 space-y-0.5 pl-2">
                      {agents.map((agent) => (
                        <li
                          key={`${agent.step_id}-${agent.label}`}
                          className="truncate text-[11px] text-ds-ink"
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
              })
            )}
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
      ) : null}
    </div>
  )
}
