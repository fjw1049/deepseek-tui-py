import { describe, expect, it } from 'vitest'
import {
  buildHeatLevelScale,
  buildHeatmapGrid,
  heatLevelFromMaxRatio,
  HEATMAP_DAY_COUNT
} from './usage-heatmap-grid'
import type { UsageDailyPoint } from './usage-ledger'

function dayPoint(day: string, tokens: number): UsageDailyPoint {
  return { day, label: day, totalTokens: tokens, segments: [] }
}

describe('usage-heatmap-grid', () => {
  it('builds a continuous 90-day window with ~13 week columns', () => {
    const daily: UsageDailyPoint[] = []
    const end = new Date('2026-06-24T12:00:00')
    for (let offset = HEATMAP_DAY_COUNT - 1; offset >= 0; offset -= 1) {
      const date = new Date(end)
      date.setDate(end.getDate() - offset)
      const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
      daily.push(dayPoint(day, 0))
    }

    const grid = buildHeatmapGrid(daily, 'zh')
    expect(grid.weekCount).toBeGreaterThanOrEqual(13)
    expect(grid.cells.length).toBe(grid.weekCount * 7)
    expect(grid.cells.filter((cell) => cell.inRange)).toHaveLength(HEATMAP_DAY_COUNT)
  })

  it('maps ratio bands: 0 / 0–20 / 20–50 / 50–90 / 90–100 percent of max', () => {
    const max = 1_000_000
    expect(heatLevelFromMaxRatio(0, max)).toBe(0)
    expect(heatLevelFromMaxRatio(1, max)).toBe(1)
    expect(heatLevelFromMaxRatio(200_000, max)).toBe(1)
    expect(heatLevelFromMaxRatio(200_001, max)).toBe(2)
    expect(heatLevelFromMaxRatio(500_000, max)).toBe(2)
    expect(heatLevelFromMaxRatio(500_001, max)).toBe(3)
    expect(heatLevelFromMaxRatio(900_000, max)).toBe(3)
    expect(heatLevelFromMaxRatio(900_001, max)).toBe(4)
    expect(heatLevelFromMaxRatio(max, max)).toBe(4)
  })

  it('uses the window max when building the scale', () => {
    const levelFor = buildHeatLevelScale([0, 150_000, 400_000, 800_000, 1_000_000])
    expect(levelFor(0)).toBe(0)
    expect(levelFor(150_000)).toBe(1)
    expect(levelFor(400_000)).toBe(2)
    expect(levelFor(800_000)).toBe(3)
    expect(levelFor(1_000_000)).toBe(4)
  })
})
