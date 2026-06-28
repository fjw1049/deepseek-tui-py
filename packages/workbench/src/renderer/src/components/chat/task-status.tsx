import type { ReactElement } from 'react'
import { CheckCircle2, CircleSlash, Clock, XCircle } from 'lucide-react'
import type { TaskStatus } from '../../lib/extract-tasks-from-blocks'

export function formatTaskDuration(ms: number | null): string | null {
  if (ms == null || ms < 0) return null
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`
  const m = Math.floor(s / 60)
  return `${m}m${Math.round(s % 60)}s`
}

export function taskStatusLabelKey(status: TaskStatus): string {
  switch (status) {
    case 'running':
      return 'contextRailTaskStatusRunning'
    case 'completed':
      return 'contextRailTaskStatusCompleted'
    case 'failed':
      return 'contextRailTaskStatusFailed'
    case 'canceled':
      return 'contextRailTaskStatusCanceled'
    default:
      return 'contextRailTaskStatusQueued'
  }
}

export function TaskStatusGlyph({ status }: { status: TaskStatus }): ReactElement {
  return (
    <span className="flex h-4 w-4 shrink-0 items-center justify-center" aria-hidden>
      {status === 'completed' ? (
        <CheckCircle2
          className="h-4 w-4 text-emerald-600/85 dark:text-emerald-400/85"
          strokeWidth={1.9}
        />
      ) : status === 'failed' ? (
        <XCircle className="h-4 w-4 text-rose-500/85 dark:text-rose-400/85" strokeWidth={1.9} />
      ) : status === 'canceled' ? (
        <CircleSlash className="h-4 w-4 text-ds-faint/80" strokeWidth={1.85} />
      ) : status === 'running' ? (
        <span className="relative flex h-3.5 w-3.5 items-center justify-center">
          <span className="absolute inline-flex h-3.5 w-3.5 animate-ping rounded-full bg-accent/30" />
          <span className="relative inline-flex h-[7px] w-[7px] rounded-full bg-accent" />
        </span>
      ) : (
        <Clock className="h-4 w-4 text-ds-faint/80" strokeWidth={1.85} />
      )}
    </span>
  )
}
