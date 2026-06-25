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
  fillHeight?: boolean
}

export function UsageActivityHeatmap({ daily, asOfDay, fillHeight = false }: Props): ReactElement {
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
      <div className={fillHeight ? 'flex min-h-0 flex-1 flex-col' : undefined}>
        <p className="mb-2 text-[12px] font-medium text-ds-muted">{t('usageHeroActivity')}</p>
      </div>
    )
  }

  const rootClass = fillHeight
    ? 'flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden'
    : 'min-w-0'

  return (
    <div className={rootClass}>
      <p className="mb-2 shrink-0 text-[12px] font-medium text-ds-muted">{t('usageHeroActivity')}</p>
      <div className={fillHeight ? 'flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden' : 'min-w-0 w-full overflow-hidden'}>
        <div className={['flex w-full min-w-0 items-stretch gap-2', fillHeight ? 'min-h-0 flex-1' : ''].join(' ')}>
          <div
            className="flex shrink-0 flex-col"
            style={{ width: WEEKDAY_LABEL_WIDTH }}
          >
            <div className="mb-1 h-3.5 shrink-0" aria-hidden />
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
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="relative mb-1 h-3.5 w-full shrink-0">
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
              className={[
                'grid w-full max-w-full gap-[3px]',
                fillHeight ? 'min-h-0 flex-1' : ''
              ].join(' ')}
              style={{
                gridAutoFlow: 'column',
                gridTemplateRows: fillHeight
                  ? `repeat(${HEATMAP_ROWS}, minmax(0, 1fr))`
                  : `repeat(${HEATMAP_ROWS}, auto)`,
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
                  fillHeight={fillHeight}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className={['mt-2 flex w-full min-w-0 shrink-0 items-center gap-2', fillHeight ? 'justify-between' : 'flex-col gap-2.5'].join(' ')}>
        {fillHeight ? (
          <>
            <HeatmapDayDetail
              cell={selectedCell}
              locale={i18n.language}
              hint={t('usageHeroHeatHint')}
              noUsageLabel={t('usageHeroHeatNoUsage')}
              compact
            />
            <HeatLegend
              lessLabel={t('usageHeroHeatLess')}
              moreLabel={t('usageHeroHeatMore')}
            />
          </>
        ) : (
          <>
            <div className="flex w-full min-w-0 gap-2">
              <div className="shrink-0" style={{ width: WEEKDAY_LABEL_WIDTH }} aria-hidden />
              <HeatmapDayDetail
                cell={selectedCell}
                locale={i18n.language}
                hint={t('usageHeroHeatHint')}
                noUsageLabel={t('usageHeroHeatNoUsage')}
              />
            </div>
            <div className="flex w-full min-w-0 gap-2">
              <div className="shrink-0" style={{ width: WEEKDAY_LABEL_WIDTH }} aria-hidden />
              <div className="flex min-w-0 flex-1 justify-end">
                <HeatLegend
                  lessLabel={t('usageHeroHeatLess')}
                  moreLabel={t('usageHeroHeatMore')}
                />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function HeatmapDayDetail({
  cell,
  locale,
  hint,
  noUsageLabel,
  compact = false
}: {
  cell: HeatmapGridCell | null
  locale: string
  hint: string
  noUsageLabel: string
  compact?: boolean
}): ReactElement {
  const textClass = compact
    ? 'min-w-0 flex-1 truncate text-left text-[11px] leading-5 text-ds-faint'
    : 'min-h-[20px] flex-1 text-center text-[12px] leading-5 text-ds-faint'

  if (!cell?.day) {
    return <p className={textClass}>{hint}</p>
  }

  const tokens = cell.point?.totalTokens ?? 0
  const dateLabel = formatHeatmapDayLabel(cell.day, locale)
  const tokenLabel =
    tokens > 0 ? `${formatCompactNumber(tokens)} tokens` : noUsageLabel

  if (compact) {
    return (
      <p className="min-w-0 flex-1 truncate text-left text-[11px] leading-5 tabular-nums text-ds-muted">
        <span className="font-medium text-ds-ink">{dateLabel}</span>
        <span className="mx-1 text-ds-faint">·</span>
        <span>{tokenLabel}</span>
      </p>
    )
  }

  return (
    <p className="min-h-[20px] flex-1 text-center text-[12px] leading-5 tabular-nums text-ds-muted">
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
  noUsageLabel,
  fillHeight = false
}: {
  cell: HeatmapGridCell
  levelFor: (tokens: number) => number
  selected: boolean
  onSelect: (day: string) => void
  locale: string
  noUsageLabel: string
  fillHeight?: boolean
}): ReactElement {
  const tokens = cell.inRange ? (cell.point?.totalTokens ?? 0) : 0
  const level = levelFor(tokens)
  const fill = heatFillForLevel(level)
  const sizeClass = fillHeight
    ? 'h-full w-full min-h-0 min-w-0'
    : 'aspect-square w-full min-w-0'

  if (!cell.inRange || !cell.day) {
    return (
      <div
        className={`${sizeClass} rounded-[4px]`}
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
        sizeClass,
        'cursor-pointer rounded-[4px] border-0 p-0 transition',
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
