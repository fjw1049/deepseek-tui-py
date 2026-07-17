import { useEffect, useMemo, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type {
  WorkflowAgentRun,
  WorkflowNodeSnapshot,
  WorkflowSnapshotPayload
} from '../../lib/workflow-snapshot'
import { StepFlow, type StepFlowItem } from './StepFlow'

type NodeStatus = WorkflowNodeSnapshot['status']

type DagNodeView = {
  id: string
  label: string
  type: string
  status: NodeStatus
  generated: boolean
  predecessors: string[]
  depth: number
  agents: WorkflowAgentRun[]
}

function statusDotClass(status: NodeStatus | WorkflowAgentRun['status']): string {
  switch (status) {
    case 'running':
      return 'border-ds-ink/40 bg-ds-ink/70'
    case 'done':
      return 'border-ds-ink/25 bg-ds-ink/40'
    case 'error':
      return 'border-ds-ink/45 bg-ds-hover'
    case 'skipped':
      return 'border-ds-border-muted bg-ds-faint'
    default:
      return 'border-ds-border-muted bg-transparent'
  }
}

function statusLabelKey(status: NodeStatus): string {
  switch (status) {
    case 'running':
      return 'workflowNodeRunning'
    case 'done':
      return 'workflowNodeDone'
    case 'error':
      return 'workflowNodeError'
    case 'skipped':
      return 'workflowNodeSkipped'
    default:
      return 'workflowNodeQueued'
  }
}

/** Topological depth from predecessors / edges — parallel nodes share a wave. */
export function buildDagNodeViews(snapshot: WorkflowSnapshotPayload): DagNodeView[] {
  const nodes = snapshot.nodes ?? []
  const agentsByStep = new Map<string, WorkflowAgentRun[]>()
  for (const agent of snapshot.agents) {
    const list = agentsByStep.get(agent.step_id) ?? []
    list.push(agent)
    agentsByStep.set(agent.step_id, list)
  }

  if (nodes.length === 0) {
    // Legacy phase-only snapshots: synthesize one node per agent step.
    const byStep = new Map<string, DagNodeView>()
    for (const agent of snapshot.agents) {
      const existing = byStep.get(agent.step_id)
      if (existing) {
        existing.agents.push(agent)
        if (agent.status === 'running') existing.status = 'running'
        else if (agent.status === 'error' && existing.status !== 'running') {
          existing.status = 'error'
        } else if (agent.status === 'done' && existing.status === 'queued') {
          existing.status = 'done'
        }
        continue
      }
      byStep.set(agent.step_id, {
        id: agent.step_id,
        label: agent.label || agent.step_id,
        type: 'agent',
        status: agent.status,
        generated: false,
        predecessors: [],
        depth: 0,
        agents: [agent]
      })
    }
    return [...byStep.values()]
  }

  /** Prefer worker rows that carry agent_id; keep shell parents only when
   * they have preview/error or there are no workers yet. */
  function agentsForStep(stepId: string): WorkflowAgentRun[] {
    const list = agentsByStep.get(stepId) ?? []
    const withId = list.filter((a) => Boolean(a.agent_id))
    if (withId.length === 0) return list
    const shells = list.filter(
      (a) => !a.agent_id && (Boolean(a.result_preview?.trim()) || Boolean(a.error?.trim()))
    )
    return [...withId, ...shells]
  }

  const predMap = new Map<string, string[]>()
  for (const n of nodes) {
    predMap.set(n.id, [...(n.predecessors ?? [])])
  }
  for (const e of snapshot.edges ?? []) {
    const cur = predMap.get(e.to) ?? []
    if (!cur.includes(e.from)) cur.push(e.from)
    predMap.set(e.to, cur)
  }

  const depthCache = new Map<string, number>()
  const depthOf = (id: string, stack: Set<string> = new Set()): number => {
    if (depthCache.has(id)) return depthCache.get(id)!
    if (stack.has(id)) return 0
    stack.add(id)
    const preds = predMap.get(id) ?? []
    const d =
      preds.length === 0 ? 0 : 1 + Math.max(0, ...preds.map((p) => depthOf(p, stack)))
    stack.delete(id)
    depthCache.set(id, d)
    return d
  }

  return nodes.map((n) => ({
    id: n.id,
    label: n.label || n.id,
    type: n.type,
    status: n.status,
    generated: Boolean(n.generated),
    predecessors: predMap.get(n.id) ?? [],
    depth: depthOf(n.id),
    agents: agentsForStep(n.id)
  }))
}

export function workflowFocusLabel(snapshot: WorkflowSnapshotPayload): string | null {
  const views = buildDagNodeViews(snapshot)
  const running = views.find((n) => n.status === 'running')
  if (running) return running.label
  const queued = views.find((n) => n.status === 'queued')
  if (queued) return queued.label
  return snapshot.current_phase ?? null
}

export function workflowProgressPct(snapshot: WorkflowSnapshotPayload): number | null {
  const views = buildDagNodeViews(snapshot)
  if (views.length > 0) {
    const done = views.filter((n) => n.status === 'done' || n.status === 'skipped').length
    return Math.round((done / views.length) * 100)
  }
  if (snapshot.agent_count > 0) {
    return Math.round((snapshot.done_count / snapshot.agent_count) * 100)
  }
  return null
}

function AgentDetail({
  agent,
  steps
}: {
  agent: WorkflowAgentRun
  steps?: StepFlowItem[]
}): ReactElement {
  const { t } = useTranslation('common')
  const [previewOpen, setPreviewOpen] = useState(false)
  // Auto-open the error detail once, when an error first appears — including
  // on mount. Never re-open after the user folds it away.
  const autoOpenedRef = useRef(false)
  useEffect(() => {
    if (autoOpenedRef.current || !agent.error) return
    autoOpenedRef.current = true
    setPreviewOpen(true)
  }, [agent.error])
  const hasSteps = Boolean(steps && steps.length > 0)
  const hasPreview = Boolean(agent.result_preview?.trim() || agent.error?.trim())

  return (
    <div className="rounded-[10px] border border-ds-border/40 bg-ds-card/50 px-2.5 py-2">
      <div className="flex items-center gap-2">
        {agent.status === 'error' ? (
          <span
            className="flex h-3.5 w-3.5 shrink-0 items-center justify-center text-[11px] font-semibold leading-none text-ds-ink/75"
            aria-hidden
          >
            !
          </span>
        ) : (
          <span className={`h-2 w-2 shrink-0 rounded-full border ${statusDotClass(agent.status)}`} />
        )}
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ds-ink">
          {agent.label}
        </span>
        <span className="shrink-0 text-[10.5px] text-ds-faint">{agent.status}</span>
        {agent.agent_id ? (
          <span className="shrink-0 font-mono text-[10px] text-ds-faint">
            {agent.agent_id.slice(0, 10)}
          </span>
        ) : null}
      </div>

      {hasSteps ? (
        <div className="mt-1.5 border-t border-ds-border/35 pt-1">
          <div className="mb-0.5 px-0.5 text-[10.5px] font-semibold text-ds-faint">
            {t('workflowAgentSteps')}
          </div>
          <StepFlow items={steps!} compact />
        </div>
      ) : null}

      {hasPreview ? (
        <div className="mt-1.5 border-t border-ds-border/35 pt-1.5">
          <button
            type="button"
            onClick={() => setPreviewOpen((v) => !v)}
            className="flex w-full items-center gap-1 text-left text-[10.5px] font-semibold text-ds-faint"
          >
            <ChevronDown
              className={[
                'h-3 w-3 transition-transform',
                previewOpen ? 'rotate-180' : 'rotate-0'
              ].join(' ')}
              strokeWidth={1.8}
            />
            {agent.error ? t('workflowAgentError') : t('workflowAgentPreview')}
          </button>
          {previewOpen ? (
            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-ds-muted">
              {agent.error?.trim() || agent.result_preview}
            </pre>
          ) : null}
        </div>
      ) : !hasSteps ? (
        <p className="mt-1 text-[11px] text-ds-faint">
          {agent.status === 'running'
            ? t('workflowAgentWaitingSteps')
            : t('workflowAgentNoDetail')}
        </p>
      ) : null}
    </div>
  )
}

function NodeRow({
  node,
  subagentStepsByAgentId
}: {
  node: DagNodeView
  subagentStepsByAgentId?: Record<string, StepFlowItem[]>
}): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  // Auto-open once when the node transitions into running/error — including
  // on mount. Never re-open after the user folds it away.
  const autoOpenedRef = useRef(false)
  useEffect(() => {
    if (autoOpenedRef.current) return
    if (node.status === 'running' || node.status === 'error') {
      autoOpenedRef.current = true
      setOpen(true)
    }
  }, [node.status])
  const stepCount = node.agents.reduce((n, agent) => {
    const id = agent.agent_id
    if (!id || !subagentStepsByAgentId) return n
    return n + (subagentStepsByAgentId[id]?.length ?? 0)
  }, 0)
  const hasDetail =
    node.agents.length > 0 ||
    node.predecessors.length > 0 ||
    node.status === 'error' ||
    node.status === 'running'

  return (
    <li className="relative">
      <button
        type="button"
        disabled={!hasDetail}
        onClick={() => hasDetail && setOpen((v) => !v)}
        aria-expanded={hasDetail ? open : undefined}
        className={[
          'flex w-full items-start gap-2.5 rounded-[12px] px-2 py-1.5 text-left transition',
          'active:scale-[0.995]',
          hasDetail ? 'hover:bg-black/[0.03] dark:hover:bg-white/[0.04]' : 'cursor-default'
        ].join(' ')}
        style={node.depth > 0 ? { marginLeft: `${Math.min(node.depth, 4) * 0.7}rem` } : undefined}
      >
        <span className="relative mt-1 flex w-3.5 shrink-0 flex-col items-center">
          {node.status === 'error' ? (
            <span
              className="flex h-3.5 w-3.5 items-center justify-center text-[12px] font-semibold leading-none text-ds-ink/75"
              aria-hidden
            >
              !
            </span>
          ) : (
            <span
              className={`h-3.5 w-3.5 rounded-full border ${statusDotClass(node.status)} ${
                node.status === 'running' ? 'animate-pulse' : ''
              }`}
            />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="truncate text-[13px] font-medium tracking-[-0.01em] text-ds-ink">
              {node.label}
            </span>
            <span className="shrink-0 font-mono text-[10.5px] text-ds-faint">{node.type}</span>
            {node.generated ? (
              <span className="shrink-0 text-[10.5px] text-ds-faint">
                {t('workflowNodeGenerated')}
              </span>
            ) : null}
          </span>
          <span className="mt-0.5 block text-[11px] text-ds-faint">
            {t(statusLabelKey(node.status))}
            {node.agents.length > 0
              ? ` · ${t('workflowNodeWorkers', { count: node.agents.length })}`
              : null}
            {stepCount > 0
              ? ` · ${t('workflowNodeStepCount', { count: stepCount })}`
              : null}
            {node.predecessors.length > 0
              ? ` · after ${node.predecessors.slice(0, 3).join(', ')}${
                  node.predecessors.length > 3 ? '…' : ''
                }`
              : null}
          </span>
        </span>
        {hasDetail ? (
          <ChevronDown
            className={[
              'mt-0.5 h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform duration-200',
              open ? 'rotate-180' : 'rotate-0'
            ].join(' ')}
            strokeWidth={1.75}
          />
        ) : null}
      </button>

      {open && hasDetail ? (
        <div
          className="mb-1.5 mt-0.5 space-y-1.5 rounded-[12px] bg-black/[0.03] px-3 py-2 dark:bg-white/[0.04]"
          style={
            node.depth > 0
              ? { marginLeft: `${Math.min(node.depth, 4) * 0.7 + 1.1}rem` }
              : { marginLeft: '1.1rem' }
          }
        >
          {node.agents.length === 0 ? (
            <p className="text-[11.5px] text-ds-faint">
              {node.status === 'running'
                ? t('workflowNodeWaitingAgents')
                : t('workflowNodeNoAgents')}
            </p>
          ) : (
            node.agents.map((agent) => (
              <AgentDetail
                key={`${agent.step_id}-${agent.label}-${agent.agent_id ?? ''}`}
                agent={agent}
                steps={
                  agent.agent_id ? subagentStepsByAgentId?.[agent.agent_id] : undefined
                }
              />
            ))
          )}
        </div>
      ) : null}
    </li>
  )
}

function FoldSection({
  title,
  children,
  defaultOpen = false
}: {
  title: string
  children: ReactNode
  defaultOpen?: boolean
}): ReactElement {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-0.5 text-left text-[12px] font-semibold tracking-[0.02em] text-ds-muted"
      >
        <ChevronDown
          className={[
            'h-3.5 w-3.5 transition-transform duration-200',
            open ? 'rotate-0' : '-rotate-90'
          ].join(' ')}
          strokeWidth={1.8}
        />
        {title}
      </button>
      {open ? <div className="mt-1.5">{children}</div> : null}
    </section>
  )
}

/**
 * Workflow-native DAG inspector: dependency waves, per-node expand for
 * workers / tool steps / previews. Joins live subagent mailbox steps by
 * ``agent_id`` when provided — that is the rich detail layer (not a
 * simplification of the snapshot).
 */
export function WorkflowDagView({
  snapshot,
  compact: _compact,
  subagentStepsByAgentId
}: {
  snapshot: WorkflowSnapshotPayload
  compact?: boolean
  subagentStepsByAgentId?: Record<string, StepFlowItem[]>
}): ReactElement {
  const { t } = useTranslation('common')
  const nodes = useMemo(() => buildDagNodeViews(snapshot), [snapshot])
  const waves = useMemo(() => {
    const byDepth = new Map<number, DagNodeView[]>()
    for (const n of nodes) {
      const list = byDepth.get(n.depth) ?? []
      list.push(n)
      byDepth.set(n.depth, list)
    }
    return [...byDepth.entries()].sort((a, b) => a[0] - b[0])
  }, [nodes])

  if (nodes.length === 0) {
    return (
      <p className="px-1 py-2 text-[12.5px] text-ds-faint">
        {t('workflowDagEmpty')}
      </p>
    )
  }

  return (
    <div>
      <ol className="flex flex-col gap-0.5">
        {waves.map(([depth, waveNodes]) => (
          <li key={`wave-${depth}`} className="min-w-0">
            {waves.length > 1 ? (
              <div className="mb-0.5 mt-1 px-2 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-ds-faint">
                {t('workflowWave', { n: depth + 1 })}
                {waveNodes.length > 1
                  ? ` · ${t('workflowWaveParallel', { count: waveNodes.length })}`
                  : ''}
              </div>
            ) : null}
            <ul className="flex flex-col">
              {waveNodes.map((node) => (
                <NodeRow
                  key={node.id}
                  node={node}
                  subagentStepsByAgentId={subagentStepsByAgentId}
                />
              ))}
            </ul>
          </li>
        ))}
      </ol>

      {snapshot.logs.length > 0 ? (
        <FoldSection
          title={t('workflowLogs', { count: snapshot.logs.length })}
        >
          <div className="max-h-36 overflow-auto rounded-[12px] border border-ds-border/50 bg-ds-card/40 px-3 py-2">
            {snapshot.logs.slice(-12).map((line, index) => (
              <p
                key={`log-${index}`}
                className="truncate font-mono text-[10.5px] leading-4 text-ds-faint"
                title={line}
              >
                {line}
              </p>
            ))}
          </div>
        </FoldSection>
      ) : null}

      {snapshot.result != null ? (
        <FoldSection title={t('workflowResult')}>
          <pre className="max-h-48 overflow-auto rounded-[12px] border border-ds-border/50 bg-ds-card/40 p-3 font-mono text-[11px] leading-5 text-ds-muted whitespace-pre-wrap break-words">
            {typeof snapshot.result === 'string'
              ? snapshot.result
              : JSON.stringify(snapshot.result, null, 2)}
          </pre>
        </FoldSection>
      ) : null}

      {snapshot.dynamic_rounds && Object.keys(snapshot.dynamic_rounds).length > 0 ? (
        <p className="mt-2 px-2 text-[10.5px] text-ds-faint">
          dynamic:{' '}
          {Object.entries(snapshot.dynamic_rounds)
            .map(([id, r]) => `${id}@${r}`)
            .join(', ')}
        </p>
      ) : null}
    </div>
  )
}
