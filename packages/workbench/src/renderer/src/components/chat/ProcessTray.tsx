import type { ReactElement } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Pause,
  Target,
  Workflow,
  X
} from 'lucide-react'
import { useChatStore } from '../../store/chat-store'
import {
  buildTrackedProcesses,
  type TrackedProcess,
  type TrackedProcessStatus
} from '../../lib/process-tracker'

function formatSeconds(s: number): string {
  if (s < 60) return `${Math.round(s)}s`
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return sec > 0 ? `${m}m ${sec}s` : `${m}m`
}

function statusLabel(status: TrackedProcessStatus, t: (key: string) => string): string {
  if (status === 'running') return t('processTrayStatusRunning')
  if (status === 'waiting') return t('processTrayStatusWaiting')
  if (status === 'completed') return t('processTrayStatusCompleted')
  if (status === 'failed') return t('processTrayStatusFailed')
  return t('processTrayStatusCancelled')
}

function toneFor(process: TrackedProcess): {
  ring: string
  icon: string
  dot: string
} {
  if (process.status === 'failed') {
    return {
      ring: 'border-red-300/65 bg-red-500/10 dark:border-red-800/55',
      icon: 'bg-red-500/15 text-red-700 dark:text-red-300',
      dot: 'bg-red-500'
    }
  }
  if (process.status === 'cancelled' || process.status === 'waiting') {
    return {
      ring: 'border-amber-300/60 bg-amber-500/10 dark:border-amber-800/50',
      icon: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
      dot: 'bg-amber-500'
    }
  }
  if (process.status === 'completed') {
    return {
      ring: 'border-emerald-300/60 bg-emerald-500/10 dark:border-emerald-800/50',
      icon: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
      dot: 'bg-emerald-500'
    }
  }
  if (process.type === 'workflow') {
    return {
      ring: 'border-sky-300/65 bg-sky-500/10 dark:border-sky-800/55',
      icon: 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
      dot: 'bg-sky-500'
    }
  }
  return {
    ring: 'border-violet-300/60 bg-violet-500/10 dark:border-violet-800/50',
    icon: 'bg-violet-500/15 text-violet-700 dark:text-violet-300',
    dot: 'bg-violet-500'
  }
}

function ProcessIcon({ process }: { process: TrackedProcess }): ReactElement {
  if (process.status === 'running') {
    return <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
  }
  if (process.status === 'completed') {
    return <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2} />
  }
  if (process.status === 'failed') {
    return <AlertTriangle className="h-3.5 w-3.5" strokeWidth={2} />
  }
  if (process.status === 'cancelled' || process.status === 'waiting') {
    return <Pause className="h-3.5 w-3.5" strokeWidth={2} />
  }
  if (process.type === 'workflow') return <Workflow className="h-3.5 w-3.5" strokeWidth={2} />
  return <Target className="h-3.5 w-3.5" strokeWidth={2} />
}

function processKindLabel(_process: TrackedProcess, t: (key: string) => string): string {
  return t('processTrayWorkflow')
}

function ProcessChip({
  process,
  onOpen
}: {
  process: TrackedProcess
  onOpen: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const tone = toneFor(process)

  return (
    <button
      type="button"
      onClick={onOpen}
      title={`${process.title} · ${statusLabel(process.status, t)}`}
      className={[
        'group inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2 text-left transition hover:-translate-y-px',
        tone.ring
      ].join(' ')}
    >
      <span
        className={[
          'flex h-5 w-5 shrink-0 items-center justify-center rounded-full',
          tone.icon
        ].join(' ')}
      >
        <ProcessIcon process={process} />
      </span>
      <span className="shrink-0 text-[12px] font-medium text-ds-ink">
        {processKindLabel(process, t)}
      </span>
      <span
        className={[
          'shrink-0 text-[11px] font-medium',
          process.status === 'running' ? 'ds-shiny-text text-ds-muted' : 'text-ds-faint'
        ].join(' ')}
      >
        {statusLabel(process.status, t)}
      </span>
    </button>
  )
}

function WorkflowDetail({
  process
}: {
  process: Extract<TrackedProcess, { type: 'workflow' }>
}): ReactElement {
  const { t } = useTranslation('common')
  const { workflow } = process
  const snap = workflow.snapshot
  const visibleAgents = snap.agents.slice(-4)
  const pct = process.progressPct

  return (
    <div className="rounded-[18px] border border-ds-border-muted bg-ds-card/70 px-4 py-3 text-[13px] leading-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="font-semibold text-ds-ink">{workflow.workflowName || snap.name}</div>
        <span className="font-mono text-[11px] text-ds-faint">{workflow.toolCallId}</span>
      </div>
      {snap.description ? (
        <p className="mt-1 text-ds-muted">{snap.description}</p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2 text-[11.5px] text-ds-faint">
        <span className="rounded-full bg-ds-hover px-2 py-0.5">
          {t('processTrayStatusLabel')}: {workflow.status}
        </span>
        {snap.current_phase ? (
          <span className="rounded-full bg-ds-hover px-2 py-0.5">
            {t('processTrayPhase')}: {snap.current_phase}
          </span>
        ) : null}
        <span className="rounded-full bg-ds-hover px-2 py-0.5">
          {snap.done_count}/{snap.agent_count} {t('processTrayAgentsDone')}
        </span>
        {snap.error_count > 0 ? (
          <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-red-700 dark:text-red-300">
            {snap.error_count} {t('processTrayErrors')}
          </span>
        ) : null}
      </div>
      {pct !== null ? (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-[11px] text-ds-faint">
            <span>{t('processTrayProgress')}</span>
            <span>{pct}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-ds-border/60">
            <div className="h-full rounded-full bg-sky-500" style={{ width: `${pct}%` }} />
          </div>
        </div>
      ) : null}
      {visibleAgents.length > 0 ? (
        <div className="mt-3 flex flex-col gap-1">
          {visibleAgents.map((agent) => (
            <div
              key={`${agent.step_id}-${agent.label}`}
              className="flex items-center gap-2 rounded-xl bg-ds-hover/50 px-2.5 py-1.5 text-[12.5px]"
            >
              <span
                className={[
                  'h-1.5 w-1.5 shrink-0 rounded-full',
                  agent.status === 'done'
                    ? 'bg-emerald-500'
                    : agent.status === 'error'
                      ? 'bg-red-500'
                      : agent.status === 'running'
                        ? 'bg-sky-500'
                        : 'bg-ds-faint'
                ].join(' ')}
              />
              <span className="min-w-0 flex-1 truncate text-ds-muted">{agent.label}</span>
              <span className="shrink-0 text-[11px] text-ds-faint">{agent.status}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function ProcessDetail({ process }: { process: TrackedProcess }): ReactElement {
  return <WorkflowDetail process={process} />
}

function ProcessDetailModal({
  process,
  onClose
}: {
  process: TrackedProcess
  onClose: () => void
}): ReactElement {
  const { t } = useTranslation('common')

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="ds-no-drag fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/35 backdrop-blur-sm" />
      <div
        className="relative z-10 flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-[22px] border border-ds-border-muted bg-ds-elevated shadow-[0_28px_70px_rgba(0,0,0,0.22)] dark:border-white/[0.08] dark:bg-[#171a1f]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-ds-border-muted/70 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ds-faint">
              {processKindLabel(process, t)}
            </span>
            <span className="truncate text-[13.5px] font-semibold text-ds-ink">
              {process.title}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('processTrayClose')}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
          >
            <X className="h-4 w-4" strokeWidth={1.9} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <ProcessDetail process={process} />
        </div>
      </div>
    </div>
  )
}

export function ProcessTray(): ReactElement | null {
  const blocks = useChatStore(
    useShallow((s) => s.blocks)
  )
  const processes = useMemo(
    () => buildTrackedProcesses({ blocks }),
    [blocks]
  )
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    setOpenId((current) =>
      current && processes.some((process) => process.id === current) ? current : null
    )
  }, [processes])

  if (processes.length === 0) return null

  const opened = openId ? processes.find((process) => process.id === openId) ?? null : null

  return (
    <div className="w-full">
      <div className="ds-no-drag flex w-full flex-wrap items-center gap-1.5">
        {processes.map((process) => (
          <ProcessChip key={process.id} process={process} onOpen={() => setOpenId(process.id)} />
        ))}
      </div>
      {opened ? <ProcessDetailModal process={opened} onClose={() => setOpenId(null)} /> : null}
    </div>
  )
}
