import { useEffect, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  Check,
  FileEdit,
  FileText,
  Globe,
  Loader2,
  Search,
  Terminal,
  Wrench,
  X,
  type LucideIcon
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  fetchTaskDetail,
  type TaskDetail,
  type TaskTimelineEntry
} from '../../hooks/use-thread-tasks'
import { isActiveTaskStatus, type TaskStatus } from '../../lib/extract-tasks-from-blocks'
import { formatTaskDuration, TaskStatusGlyph, taskStatusLabelKey } from './task-status'

type Props = {
  taskId: string
  initialStatus: TaskStatus
  open: boolean
  onClose: () => void
}

const POLL_MS = 1500

// Pure status churn — the header badge already conveys these, so they would
// only add noise to the run-process narrative.
const NOISE_KINDS = new Set([
  'queued',
  'running',
  'recovered',
  'cancel_requested',
  'completed',
  'failed',
  'canceled'
])

export function TaskRunDialog({ taskId, initialStatus, open, onClose }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) {
      setDetail(null)
      return
    }
    let cancelled = false
    let interval: number | undefined
    const load = (): void => {
      void fetchTaskDetail(taskId).then((d) => {
        if (cancelled) return
        setDetail(d)
        setLoading(false)
        if (d && !isActiveTaskStatus(d.status) && interval !== undefined) {
          window.clearInterval(interval)
          interval = undefined
        }
      })
    }
    setLoading(true)
    load()
    if (isActiveTaskStatus(initialStatus)) {
      interval = window.setInterval(load, POLL_MS)
    }
    return () => {
      cancelled = true
      if (interval !== undefined) window.clearInterval(interval)
    }
  }, [open, taskId, initialStatus])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open || typeof document === 'undefined') return null

  const status = detail?.status ?? initialStatus
  const active = isActiveTaskStatus(status)
  const timeline = detail?.timeline ?? []
  const visibleTimeline = timeline.filter((entry) => !NOISE_KINDS.has(entry.kind))
  const prompt = detail?.prompt ?? ''
  const durationLabel = formatTaskDuration(detail?.durationMs ?? null)

  return createPortal(
    <div
      className="ds-modal-backdrop ds-modal-backdrop--soft ds-no-drag fixed inset-0 z-[80] flex items-center justify-center p-4 sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="ds-modal-surface ds-modal-surface--solid flex h-full max-h-[54rem] w-full max-w-[56rem] flex-col overflow-hidden rounded-[20px]">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-ds-border px-6 py-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <TaskStatusGlyph status={status} />
            <h2 className="truncate font-mono text-[15px] font-semibold text-ds-ink">{taskId}</h2>
            <span className="shrink-0 rounded-md bg-ds-hover/60 px-1.5 py-0.5 text-[11px] text-ds-muted">
              {t(taskStatusLabelKey(status))}
            </span>
            {durationLabel ? (
              <span className="shrink-0 text-[11px] tabular-nums text-ds-faint">{durationLabel}</span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-2 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label={t('close')}
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
            {prompt ? (
              <section>
                <SectionLabel>{t('contextRailTaskPrompt')}</SectionLabel>
                <div className="rounded-[14px] border border-ds-border bg-ds-card/50 px-4 py-3">
                  <p className="whitespace-pre-wrap break-words text-[13px] leading-6 text-ds-ink">
                    {prompt}
                  </p>
                </div>
              </section>
            ) : null}

            {visibleTimeline.length > 0 ? (
              <section>
                <SectionLabel>{t('contextRailTaskLog')}</SectionLabel>
                <ol className="space-y-2.5">
                  {visibleTimeline.map((entry, idx) => (
                    <TaskLogEntry key={`${idx}-${entry.timestamp ?? ''}`} entry={entry} />
                  ))}
                </ol>
                {active ? (
                  <div className="mt-3 flex items-center gap-2 text-[12px] text-ds-faint">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    {t('contextRailTaskRunning')}
                  </div>
                ) : null}
              </section>
            ) : null}

            {loading && !detail ? (
              <div className="flex items-center gap-2 text-[13px] text-ds-muted">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('contextRailTaskLoading')}
              </div>
            ) : detail?.resultSummary ? (
              <section>
                <SectionLabel tone="result">{t('contextRailTaskResult')}</SectionLabel>
                <div className="rounded-[14px] border border-emerald-300/50 bg-emerald-500/[0.06] px-4 py-3 dark:border-emerald-700/40 dark:bg-emerald-500/[0.08]">
                  <p className="whitespace-pre-wrap break-words text-[13px] leading-6 text-ds-ink">
                    {detail.resultSummary}
                  </p>
                </div>
              </section>
            ) : detail?.error ? (
              <section>
                <SectionLabel tone="error">{t('contextRailTaskResult')}</SectionLabel>
                <div className="rounded-[14px] border border-red-200/80 bg-red-50/80 px-4 py-3 dark:border-red-800/40 dark:bg-red-500/10">
                  <p className="whitespace-pre-wrap break-words text-[13px] leading-6 text-red-700 dark:text-red-300">
                    {detail.error}
                  </p>
                </div>
              </section>
            ) : !loading && active && visibleTimeline.length === 0 ? (
              <p className="text-[13px] leading-5 text-ds-faint">{t('contextRailTaskRunning')}</p>
            ) : null}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

function SectionLabel({
  children,
  tone = 'default'
}: {
  children: ReactNode
  tone?: 'default' | 'result' | 'error'
}): ReactElement {
  const toneClass =
    tone === 'result'
      ? 'text-emerald-600 dark:text-emerald-400'
      : tone === 'error'
        ? 'text-red-600 dark:text-red-400'
        : 'text-ds-faint'
  return (
    <p className={`mb-2 text-[11px] font-semibold uppercase tracking-wider ${toneClass}`}>
      {children}
    </p>
  )
}

const TOOL_ICONS: Record<string, LucideIcon> = {
  exec_shell: Terminal,
  exec_shell_wait: Terminal,
  exec_shell_interact: Terminal,
  run_terminal_cmd: Terminal,
  task_shell_start: Terminal,
  write_file: FileEdit,
  edit_file: FileEdit,
  apply_patch: FileEdit,
  read_file: FileText,
  list_dir: FileText,
  grep_files: Search,
  file_search: Search,
  web_search: Globe,
  fetch_url: Globe
}

/** Split a backend run-log line `name · arg — reason` into its parts. */
function parseToolSummary(
  summary: string,
  failed: boolean
): { name: string; arg: string; reason: string } {
  let main = summary
  let reason = ''
  if (failed) {
    const dash = summary.indexOf(' — ')
    if (dash >= 0) {
      main = summary.slice(0, dash)
      reason = summary.slice(dash + 3)
    }
  }
  const dot = main.indexOf(' · ')
  const name = dot >= 0 ? main.slice(0, dot) : main
  const arg = dot >= 0 ? main.slice(dot + 3) : ''
  return { name: name.trim(), arg: arg.trim(), reason: reason.trim() }
}

/**
 * One run-log line, rendered like a turn in a mini conversation:
 * `text` entries are the model's narration, `tool`/`tool_error` entries get a
 * tool icon + name + argument + success/failure (mirroring the main chat tool
 * rows), everything else is a muted milestone line.
 */
function TaskLogEntry({ entry }: { entry: TaskTimelineEntry }): ReactElement {
  if (entry.kind === 'text') {
    return (
      <li className="whitespace-pre-wrap break-words border-l-2 border-ds-border/70 pl-3 text-[13px] leading-6 text-ds-ink">
        {entry.summary}
      </li>
    )
  }

  if (entry.kind === 'tool' || entry.kind === 'tool_error') {
    const failed = entry.kind === 'tool_error'
    const { name, arg, reason } = parseToolSummary(entry.summary, failed)
    const Icon = TOOL_ICONS[name] ?? Wrench
    return (
      <li className="rounded-lg px-2 py-1">
        <div className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} aria-hidden />
          <span className="shrink-0 font-mono text-[11px] font-medium text-ds-muted">{name}</span>
          {arg ? (
            <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ds-faint" title={arg}>
              {arg}
            </span>
          ) : (
            <span className="flex-1" />
          )}
          {failed ? (
            <X className="h-3.5 w-3.5 shrink-0 text-rose-500/90 dark:text-rose-400/90" />
          ) : (
            <Check className="h-3.5 w-3.5 shrink-0 text-emerald-500/90 dark:text-emerald-400/90" />
          )}
        </div>
        {reason ? (
          <p className="mt-1 break-words pl-[1.375rem] text-[12px] leading-5 text-rose-500/90 dark:text-rose-400/90">
            {reason}
          </p>
        ) : null}
      </li>
    )
  }

  return (
    <li className="flex items-start gap-2 text-[12px] leading-5 text-ds-faint">
      <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-ds-faint/60" aria-hidden />
      <span className="min-w-0 break-words">{entry.summary || entry.kind}</span>
    </li>
  )
}
