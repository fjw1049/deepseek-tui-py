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
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.05em] text-ds-faint">
          {t('usageHeroActivity')}
        </p>
      </div>
    )
  }

  const rootClass = fillHeight
    ? 'flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden'
    : 'min-w-0'

  return (
    <div className={rootClass}>
      <p className="mb-2.5 shrink-0 text-[11px] font-semibold uppercase tracking-[0.05em] text-ds-faint">
        {t('usageHeroActivity')}
      </p>
      <div
        className={[
          fillHeight ? 'flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden' : 'min-w-0 w-full overflow-hidden',
          'rounded-xl border border-ds-border/55 bg-ds-elevated/20 px-2.5 py-2.5'
        ].join(' ')}
      >
        <div className={['flex w-full min-w-0 items-stretch gap-2', fillHeight ? 'min-h-0 flex-1' : ''].join(' ')}>
          <div className="flex shrink-0 flex-col" style={{ width: WEEKDAY_LABEL_WIDTH }}>
            <div className="mb-1.5 h-3.5 shrink-0" aria-hidden />
            <div className="relative min-h-0 flex-1">
              {grid.weekdayLabels.map((label, index) => (
                <span
                  key={`${label}-${index}`}
                  className="absolute left-0 -translate-y-1/2 text-[10px] font-medium leading-none text-ds-faint"
                  style={{ top: `${((index + 0.5) / HEATMAP_ROWS) * 100}%` }}
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="relative mb-1.5 h-3.5 w-full shrink-0">
              {grid.monthLabels.map((marker) => (
                <span
                  key={`${marker.weekIndex}-${marker.label}`}
                  className="absolute top-0 whitespace-nowrap text-[10px] font-medium leading-none text-ds-faint"
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
              className={['grid w-full max-w-full gap-[3px]', fillHeight ? 'min-h-0 flex-1' : ''].join(' ')}
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
      <div
        className={[
          'mt-2.5 flex w-full min-w-0 shrink-0 items-center gap-2 rounded-xl border border-ds-border/65 bg-ds-card/70 px-3 py-2',
          fillHeight ? 'justify-between' : 'flex-col gap-2.5 border-ds-border/55 bg-ds-card/55 py-2.5'
        ].join(' ')}
      >
        {fillHeight ? (
          <>
            <HeatmapDayDetail
              cell={selectedCell}
              locale={i18n.language}
              hint={t('usageHeroHeatHint')}
              noUsageLabel={t('usageHeroHeatNoUsage')}
              compact
              highlighted={Boolean(selectedCell?.day)}
            />
            <HeatLegend lessLabel={t('usageHeroHeatLess')} moreLabel={t('usageHeroHeatMore')} />
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
                highlighted={Boolean(selectedCell?.day)}
              />
            </div>
            <div className="flex w-full min-w-0 gap-2">
              <div className="shrink-0" style={{ width: WEEKDAY_LABEL_WIDTH }} aria-hidden />
              <div className="flex min-w-0 flex-1 justify-end">
                <HeatLegend lessLabel={t('usageHeroHeatLess')} moreLabel={t('usageHeroHeatMore')} />
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
  compact = false,
  highlighted = false
}: {
  cell: HeatmapGridCell | null
  locale: string
  hint: string
  noUsageLabel: string
  compact?: boolean
  highlighted?: boolean
}): ReactElement {
  const textClass = compact
    ? 'min-w-0 flex-1 truncate text-left text-[11px] leading-5'
    : 'min-h-[20px] flex-1 text-center text-[12px] leading-5'

  if (!cell?.day) {
    return <p className={[textClass, 'text-ds-faint'].join(' ')}>{hint}</p>
  }

  const tokens = cell.point?.totalTokens ?? 0
  const dateLabel = formatHeatmapDayLabel(cell.day, locale)
  const tokenLabel = tokens > 0 ? `${formatCompactNumber(tokens)} tokens` : noUsageLabel

  if (compact) {
    return (
      <p
        className={[
          'min-w-0 flex-1 truncate text-left text-[11px] leading-5 tabular-nums',
          highlighted ? 'text-ds-ink' : 'text-ds-muted'
        ].join(' ')}
      >
        <span className="font-semibold">{dateLabel}</span>
        <span className="mx-1.5 text-ds-faint">·</span>
        <span className={tokens > 0 ? 'font-medium text-ds-ink/85' : ''}>{tokenLabel}</span>
      </p>
    )
  }

  return (
    <p
      className={[
        'min-h-[20px] flex-1 text-center text-[12px] leading-5 tabular-nums',
        highlighted ? 'text-ds-ink' : 'text-ds-muted'
      ].join(' ')}
    >
      <span className="font-semibold">{dateLabel}</span>
      <span className="mx-1.5 text-ds-faint">·</span>
      <span className={tokens > 0 ? 'font-medium text-ds-ink/85' : ''}>{tokenLabel}</span>
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
        className={`${sizeClass} rounded-[3px] bg-ds-border/30`}
        aria-hidden
      />
    )
  }

  const dateLabel = formatHeatmapDayLabel(cell.day, locale)
  const tokenLabel = tokens > 0 ? `${formatCompactNumber(tokens)} tokens` : noUsageLabel
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
        'cursor-pointer rounded-[3px] border-0 p-0 transition-[box-shadow,transform,filter] duration-150',
        'hover:z-[1] hover:brightness-[0.97] hover:ring-1 hover:ring-ds-border/80',
        'focus-visible:z-[1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70',
        selected
          ? 'z-[2] ring-2 ring-accent ring-offset-1 ring-offset-ds-card brightness-100'
          : ''
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
    <div className="flex shrink-0 items-center gap-1.5 text-[10px] font-medium text-ds-faint">
      <span>{lessLabel}</span>
      <div className="flex gap-[3px] rounded-md bg-ds-elevated/50 p-1">
        {[0, 1, 2, 3, 4].map((level) => (
          <span
            key={level}
            className="rounded-[3px] ring-1 ring-black/[0.04]"
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
