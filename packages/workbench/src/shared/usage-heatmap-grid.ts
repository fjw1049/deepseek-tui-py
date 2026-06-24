import type { UsageDailyPoint } from './usage-ledger'

export const HEATMAP_ROWS = 7
export const HEATMAP_GAP_PX = 3
export const HEATMAP_DAY_COUNT = 90

export type HeatmapGridCell = {
  day: string | null
  point: UsageDailyPoint | null
  inRange: boolean
}

export type HeatmapGrid = {
  cells: HeatmapGridCell[]
  weekCount: number
  monthLabels: Array<{ weekIndex: number; label: string }>
  weekdayLabels: string[]
}

/** Five visible steps: neutral gray → full accent blue. */
export const HEAT_FILL = [
  'var(--ds-heat-0)',
  'var(--ds-heat-1)',
  'var(--ds-heat-2)',
  'var(--ds-heat-3)',
  'var(--ds-heat-4)'
]

function formatLocalDay(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function mondayRowIndex(date: Date): number {
  const weekday = date.getDay()
  return weekday === 0 ? 6 : weekday - 1
}

function startOfWeekMonday(date: Date): Date {
  const next = new Date(date)
  next.setDate(next.getDate() - mondayRowIndex(next))
  return next
}

function endOfWeekSunday(date: Date): Date {
  const next = new Date(date)
  const weekday = next.getDay()
  next.setDate(next.getDate() + (weekday === 0 ? 0 : 7 - weekday))
  return next
}

function formatMonthLabel(date: Date, locale: string): string {
  if (locale.startsWith('zh')) {
    return `${date.getMonth() + 1}月`
  }
  return date.toLocaleDateString(locale, { month: 'short' })
}

function buildWeekdayLabels(locale: string): string[] {
  const anchor = new Date('2026-06-02T12:00:00')
  return Array.from({ length: HEATMAP_ROWS }, (_, index) => {
    const date = new Date(anchor)
    date.setDate(anchor.getDate() + index)
    return date.toLocaleDateString(locale, { weekday: 'narrow' })
  })
}

export function buildHeatmapGrid(
  daily: UsageDailyPoint[],
  locale: string,
  dayCount = HEATMAP_DAY_COUNT,
  referenceDate = new Date()
): HeatmapGrid {
  const weekdayLabels = buildWeekdayLabels(locale)
  const byDay = new Map(daily.map((point) => [point.day, point]))

  const rangeEnd = new Date(referenceDate)
  rangeEnd.setHours(12, 0, 0, 0)
  const rangeStart = new Date(rangeEnd)
  rangeStart.setDate(rangeEnd.getDate() - (dayCount - 1))

  const gridStart = startOfWeekMonday(rangeStart)
  const gridEnd = endOfWeekSunday(rangeEnd)

  const cells: HeatmapGridCell[] = []
  const monthLabels: Array<{ weekIndex: number; label: string }> = []
  const seenMonths = new Set<string>()

  const cursor = new Date(gridStart)
  while (cursor <= gridEnd) {
    const dayKey = formatLocalDay(cursor)
    const inRange = cursor >= rangeStart && cursor <= rangeEnd
    cells.push({
      day: inRange ? dayKey : null,
      point: inRange ? (byDay.get(dayKey) ?? null) : null,
      inRange
    })

    if (inRange && cursor.getDate() === 1) {
      const col = Math.floor((cells.length - 1) / HEATMAP_ROWS)
      const monthKey = `${cursor.getFullYear()}-${cursor.getMonth()}`
      if (!seenMonths.has(monthKey)) {
        seenMonths.add(monthKey)
        monthLabels.push({ weekIndex: col, label: formatMonthLabel(cursor, locale) })
      }
    }

    cursor.setDate(cursor.getDate() + 1)
  }

  return {
    cells,
    weekCount: Math.ceil(cells.length / HEATMAP_ROWS),
    monthLabels,
    weekdayLabels
  }
}

/** Ratio of daily tokens vs the 90-day max → five fixed tiers. */
export function heatLevelFromMaxRatio(tokens: number, maxTokens: number): number {
  if (tokens <= 0) return 0
  if (maxTokens <= 0) return 1
  const ratio = Math.min(1, tokens / maxTokens)
  if (ratio <= 0.2) return 1
  if (ratio <= 0.5) return 2
  if (ratio <= 0.9) return 3
  return 4
}

/** Build a level mapper using the highest daily total in the window as 100%. */
export function buildHeatLevelScale(dailyTokens: number[]): (tokens: number) => number {
  const maxTokens = Math.max(0, ...dailyTokens)
  return (tokens) => heatLevelFromMaxRatio(tokens, maxTokens)
}

export function formatHeatmapDayLabel(day: string, locale: string): string {
  const [year, month, dayNum] = day.split('-').map(Number)
  const date = new Date(year!, month! - 1, dayNum!, 12, 0, 0)
  if (locale.startsWith('zh')) {
    const weekday = date.toLocaleDateString('zh-CN', { weekday: 'short' })
    return `${year}年${month}月${dayNum}日 ${weekday}`
  }
  return date.toLocaleDateString(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    weekday: 'short'
  })
}

export function heatFillForLevel(level: number): string {
  return HEAT_FILL[Math.max(0, Math.min(4, level))] ?? HEAT_FILL[0]!
}
