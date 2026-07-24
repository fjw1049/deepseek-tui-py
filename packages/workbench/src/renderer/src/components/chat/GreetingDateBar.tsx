import { useEffect, useId, useMemo, useState, type ReactElement } from 'react'
import { Clock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { UsageDailyPoint } from '@shared/usage-ledger'
import { useChatStore } from '../../store/chat-store'
import { formatCompactNumber } from '../../hooks/use-model-usage'
import {
  dayPartFor,
  greetingFlairKeyForDayPart,
  greetingKeyForDayPart,
  type DayPart
} from '../../lib/daypart'

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

type DayPalette = {
  diskA: string
  diskB: string
  rim: string
  ray: string
  halo: string
  sheen: string
  drop: string
}

const DAY_PALETTE: Record<Exclude<DayPart, 'evening' | 'night'>, DayPalette> = {
  // 上午：柔和晨光，偏暖金
  morning: {
    diskA: '#FFF7D6',
    diskB: '#FBBF24',
    rim: '#F59E0B',
    ray: '#FCD34D',
    halo: '#FDE68A',
    sheen: '#FFFBEB',
    drop: 'rgba(251, 191, 36, 0.42)'
  },
  // 中午：最亮的正黄日光
  noon: {
    diskA: '#FEF9C3',
    diskB: '#F59E0B',
    rim: '#EA580C',
    ray: '#FACC15',
    halo: '#FDE047',
    sheen: '#FFFFFF',
    drop: 'rgba(250, 204, 21, 0.48)'
  },
  // 下午：仍是白天太阳，略收光、偏琥珀（不是日落）
  afternoon: {
    diskA: '#FEF3C7',
    diskB: '#D97706',
    rim: '#B45309',
    ray: '#F59E0B',
    halo: '#FCD34D',
    sheen: '#FFFBEB',
    drop: 'rgba(217, 119, 6, 0.38)'
  },
  // 傍晚：真正的日落橙红
  dusk: {
    diskA: '#FFEDD5',
    diskB: '#EA580C',
    rim: '#C2410C',
    ray: '#FB923C',
    halo: '#FDBA74',
    sheen: '#FFF7ED',
    drop: 'rgba(249, 115, 22, 0.42)'
  }
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

  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), TICK_MS)
    return () => window.clearInterval(id)
  }, [])

  const locale = i18n.language || 'en'
  const dateLabel = useMemo(() => formatDateTime(now, locale), [now, locale])
  const dayPart = dayPartFor(now.getHours())
  const greetingKey = greetingKeyForDayPart(dayPart)
  const flairKey = greetingFlairKeyForDayPart(dayPart)

  const activeDays = useMemo(
    () => daily.filter((point) => point.totalTokens > 0).length,
    [daily]
  )

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
        <div className="flex min-w-0 items-center gap-2.5">
          <h2 className="min-w-0 text-[22px] font-semibold leading-tight tracking-[-0.02em] text-ds-ink sm:text-[24px]">
            {t(greetingKey)}
            <span className="text-ds-faint">,</span>{' '}
            <span className="text-accent">{t(flairKey)}</span>
          </h2>
          <span className="relative -ml-3 -mt-7 inline-flex shrink-0 self-start">
            <WeatherSkyIcon period={dayPart} />
          </span>
        </div>
      </div>

      <div className="hidden shrink-0 items-end gap-6 md:flex">
        <Stat label={t('dateBarStatsThreads')} value={String(threads.length)} />
        <Stat label={t('dateBarStatsActiveDays')} value={String(activeDays)} />
        <Stat label={t('dateBarStatsTodayTokens')} value={todayLabel} />
      </div>
    </div>
  )
}

/** Weather-forecast glyph: day suns + evening/night moons. */
function WeatherSkyIcon({ period }: { period: DayPart }): ReactElement {
  const uid = useId().replace(/:/g, '')
  const diskGrad = `ws-disk-${uid}`
  const haloGrad = `ws-halo-${uid}`
  const rimGrad = `ws-rim-${uid}`

  if (period === 'evening' || period === 'night') {
    const evening = period === 'evening'
    return (
      <span
        className="ds-weather-sky"
        aria-hidden
        style={{
          filter: `drop-shadow(0 2px 6px ${evening ? 'rgba(167,139,250,0.4)' : 'rgba(96,165,250,0.38)'})`
        }}
      >
        <svg viewBox="0 0 24 24" className="ds-weather-sky__svg" fill="none">
          <defs>
            <radialGradient id={haloGrad} cx="42%" cy="40%" r="58%">
              <stop offset="0%" stopColor={evening ? '#DDD6FE' : '#BFDBFE'} stopOpacity="0.7" />
              <stop offset="55%" stopColor={evening ? '#A78BFA' : '#60A5FA'} stopOpacity="0.22" />
              <stop offset="100%" stopColor={evening ? '#5B21B6' : '#1E3A8A'} stopOpacity="0" />
            </radialGradient>
            <linearGradient id={diskGrad} x1="18%" y1="12%" x2="88%" y2="92%">
              <stop offset="0%" stopColor={evening ? '#F5F3FF' : '#EFF6FF'} />
              <stop offset="45%" stopColor={evening ? '#C4B5FD' : '#93C5FD'} />
              <stop offset="100%" stopColor={evening ? '#8B5CF6' : '#3B82F6'} />
            </linearGradient>
          </defs>
          <circle cx="12" cy="12" r="11" fill={`url(#${haloGrad})`} />
          <path
            d="M14.8 5.1a6.9 6.9 0 1 0 3.9 12.2 5.55 5.55 0 1 1-3.9-12.2z"
            fill={`url(#${diskGrad})`}
          />
          <circle cx="10.2" cy="11.4" r="0.85" fill={evening ? '#7C3AED' : '#2563EB'} opacity="0.18" />
          <circle cx="11.6" cy="14.2" r="0.55" fill={evening ? '#6D28D9' : '#1D4ED8'} opacity="0.14" />
          <circle
            cx="9.4"
            cy="13.1"
            r="1.15"
            fill={evening ? '#EDE9FE' : '#DBEAFE'}
            opacity="0.22"
          />
          {!evening ? (
            <>
              <circle cx="18.6" cy="5.8" r="0.9" fill="#E0F2FE" opacity="0.9" />
              <circle cx="20" cy="11.2" r="0.55" fill="#BFDBFE" opacity="0.8" />
              <circle cx="6.4" cy="17.6" r="0.65" fill="#DBEAFE" opacity="0.75" />
            </>
          ) : (
            <circle cx="19.2" cy="7.2" r="0.55" fill="#EDE9FE" opacity="0.75" />
          )}
        </svg>
      </span>
    )
  }

  const p = DAY_PALETTE[period]
  const rayCount = period === 'noon' ? 12 : period === 'afternoon' ? 8 : 8
  const rayOuter =
    period === 'noon' ? 11.1 : period === 'morning' ? 10.35 : period === 'afternoon' ? 10.2 : 10.55
  const rayInner = period === 'noon' ? 7.35 : period === 'afternoon' ? 7.15 : 7.05
  const diskR = period === 'noon' ? 4.75 : period === 'dusk' ? 4.35 : 4.45
  const rayOpacity = period === 'afternoon' ? 0.82 : period === 'dusk' ? 0.9 : 0.95
  const rays = Array.from({ length: rayCount }, (_, i) => {
    const angle = (i * (Math.PI * 2)) / rayCount - Math.PI / 2
    const cos = Math.cos(angle)
    const sin = Math.sin(angle)
    const outer = i % 2 === 0 ? rayOuter : rayOuter - 0.85
    const inner = i % 2 === 0 ? rayInner : rayInner + 0.15
    return {
      x1: 12 + cos * inner,
      y1: 12 + sin * inner,
      x2: 12 + cos * outer,
      y2: 12 + sin * outer,
      wide: i % 2 === 0
    }
  })

  return (
    <span
      className="ds-weather-sky"
      aria-hidden
      style={{ filter: `drop-shadow(0 2px 7px ${p.drop})` }}
    >
      <svg viewBox="0 0 24 24" className="ds-weather-sky__svg" fill="none">
        <defs>
          <radialGradient id={haloGrad} cx="45%" cy="40%" r="60%">
            <stop offset="0%" stopColor={p.halo} stopOpacity="0.75" />
            <stop offset="50%" stopColor={p.ray} stopOpacity="0.28" />
            <stop offset="100%" stopColor={p.diskB} stopOpacity="0" />
          </radialGradient>
          <radialGradient id={diskGrad} cx="35%" cy="30%" r="70%">
            <stop offset="0%" stopColor={p.diskA} />
            <stop offset="55%" stopColor={p.ray} />
            <stop offset="100%" stopColor={p.diskB} />
          </radialGradient>
          <linearGradient id={rimGrad} x1="20%" y1="0%" x2="80%" y2="100%">
            <stop offset="0%" stopColor={p.sheen} stopOpacity="0.65" />
            <stop offset="100%" stopColor={p.rim} stopOpacity="0.35" />
          </linearGradient>
        </defs>

        <circle cx="12" cy="12" r="11.2" fill={`url(#${haloGrad})`} />

        {rays.map((ray, i) => (
          <line
            key={i}
            x1={ray.x1}
            y1={ray.y1}
            x2={ray.x2}
            y2={ray.y2}
            stroke={p.ray}
            strokeWidth={ray.wide ? (period === 'noon' ? 1.9 : 1.7) : 1.25}
            strokeLinecap="round"
            opacity={ray.wide ? rayOpacity : rayOpacity * 0.75}
          />
        ))}

        <circle cx="12" cy="12" r={diskR + 0.55} fill={`url(#${rimGrad})`} opacity="0.55" />
        <circle cx="12" cy="12" r={diskR} fill={`url(#${diskGrad})`} />
        <circle cx="10.35" cy="10.1" r={diskR * 0.32} fill={p.sheen} opacity="0.7" />
        <circle cx="13.6" cy="13.4" r={diskR * 0.14} fill={p.rim} opacity="0.18" />
      </svg>
    </span>
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
