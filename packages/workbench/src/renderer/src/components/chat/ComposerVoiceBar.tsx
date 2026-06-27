import { Loader2, X } from 'lucide-react'
import type { ReactElement } from 'react'
import { formatVoiceDuration } from '../../hooks/use-audio-recorder'

export type ComposerVoicePhase = 'idle' | 'recording' | 'transcribing'

const TRACK_HEIGHT = 28
const MIN_BAR_HEIGHT = 2.5

type Props = {
  phase: ComposerVoicePhase
  levels: number[]
  elapsedMs: number
  maxDurationMs: number
  onCancel: () => void
  labels: {
    recording: string
    transcribing: string
    cancel: string
  }
}

export function ComposerVoiceBar({
  phase,
  levels,
  elapsedMs,
  maxDurationMs,
  onCancel,
  labels
}: Props): ReactElement | null {
  if (phase === 'idle') return null

  const timerLabel = `${formatVoiceDuration(elapsedMs)} / ${formatVoiceDuration(maxDurationMs)}`
  const active = phase === 'recording'

  return (
    <div className="mx-1 mb-1 flex items-center gap-3 rounded-2xl border border-ds-border-muted bg-ds-main/70 px-3 py-2">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <div
          className="flex min-w-0 flex-1 items-center justify-between overflow-hidden"
          style={{ height: TRACK_HEIGHT }}
          aria-hidden
        >
          {levels.map((level, index) => (
            <span
              key={index}
              className={`w-[2px] shrink-0 rounded-full transition-[height] duration-[60ms] ease-linear ${
                active ? 'bg-red-500/90' : 'bg-ds-faint/55'
              }`}
              style={{
                height: `${Math.max(MIN_BAR_HEIGHT, level * TRACK_HEIGHT)}px`
              }}
            />
          ))}
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[12px] font-medium text-ds-ink">
            {phase === 'transcribing' ? labels.transcribing : labels.recording}
          </p>
          {active ? (
            <p className="text-[11px] tabular-nums text-ds-faint">{timerLabel}</p>
          ) : null}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={onCancel}
          disabled={phase === 'transcribing'}
          className="ds-no-drag flex h-8 w-8 items-center justify-center rounded-full border border-ds-border bg-ds-card text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-50"
          aria-label={labels.cancel}
          title={labels.cancel}
        >
          <X className="h-4 w-4" strokeWidth={2} />
        </button>

        {phase === 'transcribing' ? (
          <div
            className="flex h-8 w-8 items-center justify-center rounded-full border border-ds-border bg-ds-card text-ds-muted"
            aria-hidden
          >
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
          </div>
        ) : null}
      </div>
    </div>
  )
}
