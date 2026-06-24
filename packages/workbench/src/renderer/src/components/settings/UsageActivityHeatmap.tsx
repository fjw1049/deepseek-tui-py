import { useMemo, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { UsageDailyPoint } from '@shared/usage-ledger'
import {
  buildHeatLevelScale,
  buildHeatmapGrid,
  formatHeatmapDayLabel,
  heatFillForLevel,
  HEATMAP_ROWS,
  type HeatmapGridCell
} from '@shared/usage-heatmap-grid'
import { formatCompactNumber } from '../../hooks/use-model-usage'

const WEEKDAY_LABEL_WIDTH = 16
const LEGEND_CELL_PX = 11

type Props = {
  daily: UsageDailyPoint[]
  asOfDay?: string
}

export function UsageActivityHeatmap({ daily, asOfDay }: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const [selectedDay, setSelectedDay] = useState<string | null>(null)

  const referenceDate = useMemo(
    () => (asOfDay ? new Date(`${asOfDay}T12:00:00`) : new Date()),
    [asOfDay]
  )

  const grid = useMemo(
    () => buildHeatmapGrid(daily, i18n.language, undefined, referenceDate),
    [daily, i18n.language, referenceDate]
  )

  const levelFor = useMemo(() => {
    const tokens = grid.cells
      .filter((cell) => cell.inRange)
      .map((cell) => cell.point?.totalTokens ?? 0)
    return buildHeatLevelScale(tokens)
  }, [grid])

  const selectedCell = useMemo(() => {
    if (!selectedDay) return null
    return grid.cells.find((cell) => cell.day === selectedDay) ?? null
  }, [grid.cells, selectedDay])

  if (grid.cells.length === 0) {
    return (
      <div>
        <p className="mb-3 text-[12px] font-medium text-ds-muted">{t('usageHeroActivity')}</p>
      </div>
    )
  }

  return (
    <div className="min-w-0">
      <p className="mb-3 text-[12px] font-medium text-ds-muted">{t('usageHeroActivity')}</p>
      <div className="min-w-0 w-full overflow-hidden">
        <div className="flex w-full min-w-0 items-stretch gap-2">
          <div
            className="flex shrink-0 flex-col"
            style={{ width: WEEKDAY_LABEL_WIDTH }}
          >
            <div className="mb-1.5 h-4 shrink-0" aria-hidden />
            <div className="relative min-h-0 flex-1">
              {grid.weekdayLabels.map((label, index) => (
                <span
                  key={`${label}-${index}`}
                  className="absolute left-0 -translate-y-1/2 text-[10px] leading-none text-ds-faint"
                  style={{ top: `${((index + 0.5) / HEATMAP_ROWS) * 100}%` }}
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
          <div className="min-w-0 flex-1">
            <div className="relative mb-1.5 h-4 w-full">
              {grid.monthLabels.map((marker) => (
                <span
                  key={`${marker.weekIndex}-${marker.label}`}
                  className="absolute top-0 whitespace-nowrap text-[10px] leading-none text-ds-faint"
                  style={{
                    left: `${(marker.weekIndex / Math.max(grid.weekCount, 1)) * 100}%`
                  }}
                >
                  {marker.label}
                </span>
              ))}
            </div>
            <div
              role="group"
              aria-label={t('usageHeroActivity')}
              className="grid w-full max-w-full gap-[3px]"
              style={{
                gridAutoFlow: 'column',
                gridTemplateRows: `repeat(${HEATMAP_ROWS}, auto)`,
                gridTemplateColumns: `repeat(${grid.weekCount}, minmax(0, 1fr))`
              }}
            >
              {grid.cells.map((cell, index) => (
                <HeatCell
                  key={cell.day ?? `cell-${index}`}
                  cell={cell}
                  levelFor={levelFor}
                  selected={cell.day != null && cell.day === selectedDay}
                  onSelect={setSelectedDay}
                  locale={i18n.language}
                  noUsageLabel={t('usageHeroHeatNoUsage')}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className="mt-2 flex w-full min-w-0 gap-2">
        <div className="shrink-0" style={{ width: WEEKDAY_LABEL_WIDTH }} aria-hidden />
        <HeatmapDayDetail
          cell={selectedCell}
          locale={i18n.language}
          hint={t('usageHeroHeatHint')}
          noUsageLabel={t('usageHeroHeatNoUsage')}
        />
      </div>
      <div className="mt-2 flex justify-end">
        <HeatLegend
          lessLabel={t('usageHeroHeatLess')}
          moreLabel={t('usageHeroHeatMore')}
        />
      </div>
    </div>
  )
}

function HeatmapDayDetail({
  cell,
  locale,
  hint,
  noUsageLabel
}: {
  cell: HeatmapGridCell | null
  locale: string
  hint: string
  noUsageLabel: string
}): ReactElement {
  if (!cell?.day) {
    return (
      <p className="min-h-[18px] flex-1 text-center text-[12px] text-ds-faint">{hint}</p>
    )
  }

  const tokens = cell.point?.totalTokens ?? 0
  const dateLabel = formatHeatmapDayLabel(cell.day, locale)
  const tokenLabel =
    tokens > 0 ? `${formatCompactNumber(tokens)} tokens` : noUsageLabel

  return (
    <p className="min-h-[18px] flex-1 text-center text-[12px] tabular-nums text-ds-muted">
      <span className="font-medium text-ds-ink">{dateLabel}</span>
      <span className="mx-1.5 text-ds-faint">·</span>
      <span>{tokenLabel}</span>
    </p>
  )
}

function HeatCell({
  cell,
  levelFor,
  selected,
  onSelect,
  locale,
  noUsageLabel
}: {
  cell: HeatmapGridCell
  levelFor: (tokens: number) => number
  selected: boolean
  onSelect: (day: string) => void
  locale: string
  noUsageLabel: string
}): ReactElement {
  const tokens = cell.inRange ? (cell.point?.totalTokens ?? 0) : 0
  const level = levelFor(tokens)
  const fill = heatFillForLevel(level)

  if (!cell.inRange || !cell.day) {
    return (
      <div
        className="aspect-square w-full min-w-0 rounded-[4px]"
        style={{ backgroundColor: fill }}
        aria-hidden
      />
    )
  }

  const dateLabel = formatHeatmapDayLabel(cell.day, locale)
  const tokenLabel =
    tokens > 0 ? `${formatCompactNumber(tokens)} tokens` : noUsageLabel
  const ariaLabel = `${dateLabel}, ${tokenLabel}`

  return (
    <button
      type="button"
      title={`${dateLabel} · ${tokenLabel}`}
      aria-label={ariaLabel}
      aria-pressed={selected}
      onClick={() => onSelect(cell.day!)}
      className={[
        'aspect-square w-full min-w-0 cursor-pointer rounded-[4px] border-0 p-0 transition',
        'hover:brightness-95',
        selected ? 'ring-2 ring-inset ring-ds-accent' : ''
      ].join(' ')}
      style={{ backgroundColor: fill }}
    />
  )
}

function HeatLegend({
  lessLabel,
  moreLabel
}: {
  lessLabel: string
  moreLabel: string
}): ReactElement {
  return (
    <div className="flex items-center gap-1.5 text-[10px] text-ds-faint">
      <span>{lessLabel}</span>
      <div className="flex gap-[3px]">
        {[0, 1, 2, 3, 4].map((level) => (
          <span
            key={level}
            className="rounded-[3px]"
            style={{
              width: LEGEND_CELL_PX,
              height: LEGEND_CELL_PX,
              backgroundColor: heatFillForLevel(level)
            }}
          />
        ))}
      </div>
      <span>{moreLabel}</span>
    </div>
  )
}
