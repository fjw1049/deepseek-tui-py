import { useEffect, useMemo, useState, type ReactElement } from 'react'
import { Clock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { UsageDailyPoint } from '@shared/usage-ledger'
import { useChatStore } from '../../store/chat-store'
import { formatCompactNumber } from '../../hooks/use-model-usage'

type Props = {
  daily: UsageDailyPoint[]
  asOfDay?: string
  loading: boolean
}

const TICK_MS = 30_000

function todayLocalKey(): string {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function greetingKeyFor(hour: number): string {
  if (hour < 6) return 'greetingNight'
  if (hour < 12) return 'greetingMorning'
  if (hour < 18) return 'greetingAfternoon'
  return 'greetingEvening'
}

function formatDateTime(date: Date, locale: string): string {
  const time = date.toLocaleTimeString(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
  const weekdayMonthDay = date.toLocaleDateString(locale, {
    weekday: 'long',
    month: 'long',
    day: 'numeric'
  })
  return `${time}, ${weekdayMonthDay}`
}

export function GreetingDateBar({ daily, asOfDay, loading }: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const threads = useChatStore((s) => s.threads)
  const busy = useChatStore((s) => s.busy)
  const blocks = useChatStore((s) => s.blocks)

  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), TICK_MS)
    return () => window.clearInterval(id)
  }, [])

  const locale = i18n.language || 'en'
  const dateLabel = useMemo(() => formatDateTime(now, locale), [now, locale])
  const greetingKey = greetingKeyFor(now.getHours())

  const runningCount = useMemo(() => {
    let count = 0
    for (const block of blocks) {
      const status = (block as { status?: string }).status
      if (status === 'running' || status === 'pending') count += 1
    }
    if (busy && count === 0) return 1
    return count
  }, [blocks, busy])

  const todayTokens = useMemo(() => {
    const key = asOfDay ?? todayLocalKey()
    const point = daily.find((p) => p.day === key)
    return point?.totalTokens ?? 0
  }, [daily, asOfDay])

  const todayLabel = loading && todayTokens === 0 ? '—' : formatCompactNumber(todayTokens)

  return (
    <div className="ds-glass ds-content-card--interactive flex w-full items-center justify-between gap-4 rounded-[14px] px-5 py-4 sm:px-6 sm:py-5">
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex items-center gap-2 text-[12.5px] font-medium text-ds-faint">
          <Clock className="h-4 w-4 shrink-0" strokeWidth={1.85} aria-hidden />
          <span className="tabular-nums">{dateLabel}</span>
        </div>
        <div className="flex items-center gap-2.5">
          <h2 className="text-[22px] font-semibold leading-tight tracking-[-0.02em] text-ds-ink sm:text-[24px]">
            {t(greetingKey)}
            <span className="text-ds-faint">,</span>{' '}
            <span className="text-accent">{t('greetingFlair')}</span>
          </h2>
          <span
            aria-hidden
            className="h-5 w-5 shrink-0 rounded-full bg-gradient-to-br from-sky-400 via-emerald-400 to-amber-300 shadow-[0_1px_3px_rgba(0,0,0,0.12)]"
          />
        </div>
      </div>

      <div className="hidden shrink-0 items-end gap-6 md:flex">
        <Stat label={t('dateBarStatsThreads')} value={String(threads.length)} />
        <Stat label={t('dateBarStatsRunning')} value={String(runningCount)} />
        <Stat label={t('dateBarStatsTodayTokens')} value={todayLabel} />
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <div className="flex min-w-0 flex-col items-end gap-0.5 border-l border-ds-border-muted pl-6 first:border-l-0 first:pl-0">
      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-ds-faint">
        {label}
      </span>
      <span className="text-[20px] font-semibold tabular-nums leading-none text-ds-ink">
        {value}
      </span>
    </div>
  )
}
