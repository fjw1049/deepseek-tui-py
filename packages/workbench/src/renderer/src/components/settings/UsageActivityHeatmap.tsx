import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement
} from 'react'
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
const SQUARE_GAP = 3
const MONTH_ROW_HEIGHT = 14
const MONTH_ROW_GAP = 6
const COLUMN_GAP = 8
// Target cell size in fill mode: small enough to read like a GitHub graph,
// capped so a short panel packs more weeks instead of inflating each square.
const IDEAL_CELL_PX = 13
const MIN_CELL_PX = 3

type Props = {
  daily: UsageDailyPoint[]
  asOfDay?: string
  fillHeight?: boolean
}

export function UsageActivityHeatmap({ daily, asOfDay, fillHeight = false }: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const [selectedDay, setSelectedDay] = useState<string | null>(null)
  const plotRef = useRef<HTMLDivElement>(null)
  const [plotBox, setPlotBox] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0
  })

  useLayoutEffect(() => {
    if (!fillHeight) return
    const el = plotRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect) setPlotBox({ width: rect.width, height: rect.height })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [fillHeight])

  const referenceDate = useMemo(
    () => (asOfDay ? new Date(`${asOfDay}T12:00:00`) : new Date()),
    [asOfDay]
  )

  // In fill mode, prefer small, GitHub-style cells and pack as many weekly
  // columns as the width allows, filling the panel edge-to-edge. Height only
  // caps the cell so extra height becomes breathing room, not chunky blocks;
  // dataless lead-in days render as faint empty squares (heat-0), so the grid
  // reads like a GitHub contribution graph rather than a black slab.
  const layout = useMemo(() => {
    if (!fillHeight || plotBox.width <= 0 || plotBox.height <= 0) {
      return { dayCount: undefined as number | undefined, cellPx: 0 }
    }
    const gridHeight = plotBox.height - MONTH_ROW_HEIGHT - MONTH_ROW_GAP
    const gridWidth = plotBox.width - WEEKDAY_LABEL_WIDTH - COLUMN_GAP
    const maxByHeight = (gridHeight - (HEATMAP_ROWS - 1) * SQUARE_GAP) / HEATMAP_ROWS
    const side = Math.max(MIN_CELL_PX, Math.min(IDEAL_CELL_PX, maxByHeight))
    const weeks = Math.min(
      53,
      Math.max(1, Math.floor((gridWidth + SQUARE_GAP) / (side + SQUARE_GAP)))
    )
    return { dayCount: weeks * HEATMAP_ROWS, cellPx: side }
  }, [fillHeight, plotBox.width, plotBox.height])

  const grid = useMemo(
    () => buildHeatmapGrid(daily, i18n.language, layout.dayCount, referenceDate),
    [daily, i18n.language, layout.dayCount, referenceDate]
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

  // Turn the measured square side into CSS vars the grid and labels align to.
  // Before the first measurement we letterbox via container-query units so the
  // grid never overflows on the initial paint.
  const cellSizing = useMemo<CSSProperties>(() => {
    const wc = Math.max(grid.weekCount, 1)
    if (layout.cellPx <= 0) {
      const widthBudget = WEEKDAY_LABEL_WIDTH + COLUMN_GAP + (wc - 1) * SQUARE_GAP
      const heightBudget = MONTH_ROW_HEIGHT + MONTH_ROW_GAP + (HEATMAP_ROWS - 1) * SQUARE_GAP
      const cell = `min((100cqw - ${widthBudget}px) / ${wc}, (100cqh - ${heightBudget}px) / ${HEATMAP_ROWS})`
      return {
        '--hm-cell': `max(3px, ${cell})`,
        '--hm-grid-w': `calc(${wc} * var(--hm-cell) + ${(wc - 1) * SQUARE_GAP}px)`,
        '--hm-grid-h': `calc(${HEATMAP_ROWS} * var(--hm-cell) + ${(HEATMAP_ROWS - 1) * SQUARE_GAP}px)`
      } as CSSProperties
    }
    return {
      '--hm-cell': `${layout.cellPx}px`,
      '--hm-grid-w': `${wc * layout.cellPx + (wc - 1) * SQUARE_GAP}px`,
      '--hm-grid-h': `${HEATMAP_ROWS * layout.cellPx + (HEATMAP_ROWS - 1) * SQUARE_GAP}px`
    } as CSSProperties
  }, [grid.weekCount, layout.cellPx])

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
        <div
          ref={plotRef}
          className={[
            'flex w-full min-w-0 gap-2',
            fillHeight ? 'min-h-0 flex-1 items-center [container-type:size]' : 'items-stretch'
          ].join(' ')}
          style={fillHeight ? cellSizing : undefined}
        >
          <div className="flex shrink-0 flex-col" style={{ width: WEEKDAY_LABEL_WIDTH }}>
            <div className="mb-1.5 h-3.5 shrink-0" aria-hidden />
            <div
              className={fillHeight ? 'relative shrink-0' : 'relative min-h-0 flex-1'}
              style={fillHeight ? { height: 'var(--hm-grid-h)' } : undefined}
            >
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
            <div
              className={['relative mb-1.5 h-3.5 shrink-0', fillHeight ? '' : 'w-full'].join(' ')}
              style={fillHeight ? { width: 'var(--hm-grid-w)', maxWidth: '100%' } : undefined}
            >
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
              className={['grid max-w-full gap-[3px]', fillHeight ? 'shrink-0' : 'w-full'].join(' ')}
              style={
                fillHeight
                  ? {
                      gridAutoFlow: 'column',
                      width: 'var(--hm-grid-w)',
                      gridTemplateRows: `repeat(${HEATMAP_ROWS}, var(--hm-cell))`,
                      gridTemplateColumns: `repeat(${grid.weekCount}, var(--hm-cell))`
                    }
                  : {
                      gridAutoFlow: 'column',
                      gridTemplateRows: `repeat(${HEATMAP_ROWS}, auto)`,
                      gridTemplateColumns: `repeat(${grid.weekCount}, minmax(0, 1fr))`
                    }
              }
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
  // The cell fills its grid track; the swatch is sized to the track's smaller
  // edge via container-query units, so it stays a true square (never stretched
  // into a rectangle) with even breathing room on every side.
  // Grid tracks are already exact squares, so the swatch simply fills its cell;
  // the uniform grid gap becomes the only spacing between squares.
  const cellClass = fillHeight ? 'h-full w-full' : 'aspect-square w-full min-w-0'

  if (!cell.inRange || !cell.day) {
    return (
      <div
        className={`${cellClass} rounded-[3px]`}
        style={{ backgroundColor: heatFillForLevel(0) }}
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
        cellClass,
        'cursor-pointer rounded-[3px] border-0 p-0 transition-[transform,filter,box-shadow] duration-150',
        'hover:z-[1] hover:scale-110 hover:brightness-110',
        'focus-visible:z-[1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70',
        selected ? 'z-[2] scale-110 ring-2 ring-accent ring-offset-1 ring-offset-ds-card' : ''
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
