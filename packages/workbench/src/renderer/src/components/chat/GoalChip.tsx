import type { ReactElement } from 'react'
import { useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { Target, Pause, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useChatStore } from '../../store/chat-store'
import type { GoalStatusPayload } from '../../agent/types'

type GoalData = NonNullable<GoalStatusPayload['goal']>

function formatSeconds(s: number): string {
  if (s < 60) return `${Math.round(s)}s`
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return sec > 0 ? `${m}m${sec}s` : `${m}m`
}

function progressPercent(goal: GoalData): number | null {
  if (!goal.token_budget) return null
  return Math.min(100, Math.round((goal.tokens_used / goal.token_budget) * 100))
}

const STATUS_CONFIG = {
  active: {
    icon: Target,
    color: 'text-[var(--ds-accent)]',
    bg: 'bg-[var(--ds-accent)]/10',
    border: 'border-[var(--ds-accent)]/20',
    barColor: 'bg-[var(--ds-accent)]'
  },
  paused: {
    icon: Pause,
    color: 'text-[var(--ds-faint)]',
    bg: 'bg-[var(--ds-ink)]/5',
    border: 'border-[var(--ds-border)]',
    barColor: 'bg-[var(--ds-faint)]'
  },
  budget_limited: {
    icon: AlertTriangle,
    color: 'text-amber-500',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/20',
    barColor: 'bg-amber-500'
  },
  complete: {
    icon: CheckCircle2,
    color: 'text-[var(--ds-success)]',
    bg: 'bg-[var(--ds-success)]/10',
    border: 'border-[var(--ds-success)]/20',
    barColor: 'bg-[var(--ds-success)]'
  }
} as const

function GoalPanel({ goal, onClose }: { goal: GoalData; onClose: () => void }): ReactElement {
  const cfg = STATUS_CONFIG[goal.status]
  const pct = progressPercent(goal)

  return (
    <div className="ds-card-strong absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-[18px] border border-ds-border p-4 shadow-[0_18px_52px_rgba(15,23,42,0.18)] backdrop-blur-xl dark:shadow-[0_22px_58px_rgba(0,0,0,0.38)]">
      <div className="mb-3 flex items-center justify-between">
        <span className={`text-[11px] font-semibold uppercase tracking-wide ${cfg.color}`}>
          {goal.status === 'budget_limited' ? 'Budget Reached' : goal.status}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full p-1 text-ds-faint hover:bg-ds-hover hover:text-ds-ink"
          aria-label="Close"
        >
          <svg className="h-3.5 w-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M1 1l12 12M13 1L1 13" />
          </svg>
        </button>
      </div>

      <p className="mb-3 text-[13px] leading-relaxed text-ds-ink">
        {goal.objective}
      </p>

      {pct !== null ? (
        <div className="mb-2">
          <div className="mb-1 flex items-baseline justify-between text-[11px]">
            <span className="text-ds-faint">
              {goal.tokens_used.toLocaleString()} / {goal.token_budget!.toLocaleString()} tokens
            </span>
            <span className={`font-medium ${cfg.color}`}>{pct}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-ds-border/50">
            <div
              className={`h-full rounded-full transition-all duration-500 ${cfg.barColor}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      ) : (
        <div className="mb-2 text-[11px] text-ds-faint">
          {goal.tokens_used.toLocaleString()} tokens · {formatSeconds(goal.active_seconds)}
        </div>
      )}

      <div className="mt-3 flex items-center gap-1.5 text-[11px] text-ds-faint">
        <span className="inline-flex items-center gap-1">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${cfg.barColor}`} />
          {formatSeconds(goal.active_seconds)} active
        </span>
      </div>
    </div>
  )
}

export function GoalChip(): ReactElement | null {
  const goalStatus = useChatStore(useShallow((s) => s.goalStatus))
  const [panelOpen, setPanelOpen] = useState(false)
  const chipRef = useRef<HTMLDivElement>(null)

  if (!goalStatus) return null

  // Fade out completed goals after a moment (still show chip briefly)
  const cfg = STATUS_CONFIG[goalStatus.status]
  const Icon = cfg.icon
  const pct = progressPercent(goalStatus)

  const label =
    goalStatus.objective.length > 28
      ? goalStatus.objective.slice(0, 28) + '…'
      : goalStatus.objective

  const sublabel =
    goalStatus.status === 'paused'
      ? 'paused'
      : goalStatus.status === 'budget_limited'
        ? 'budget reached'
        : goalStatus.status === 'complete'
          ? 'done'
          : pct !== null
            ? `${pct}%`
            : formatSeconds(goalStatus.active_seconds)

  return (
    <div ref={chipRef} className="relative">
      <button
        type="button"
        onClick={() => setPanelOpen((v) => !v)}
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[12px] font-medium transition ${cfg.bg} ${cfg.border} ${cfg.color} hover:opacity-90`}
        aria-expanded={panelOpen}
        aria-label="Goal status"
      >
        <Icon className="h-3.5 w-3.5" strokeWidth={2} />
        <span className="max-w-[140px] truncate">{label}</span>
        <span className="opacity-60">·</span>
        <span className="opacity-75">{sublabel}</span>
      </button>

      {panelOpen ? (
        <GoalPanel goal={goalStatus} onClose={() => setPanelOpen(false)} />
      ) : null}
    </div>
  )
}
