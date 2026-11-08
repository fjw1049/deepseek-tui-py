// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ModelUsageTrendChart } from './ModelUsageTrendChart'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.useRealTimers()
})

describe('ModelUsageTrendChart', () => {
  it.each([[30, 1, 30], [90, 3, 30], [365, 7, 53]])(
    'groups %i days into readable bars without losing usage', async (days, segmentDays, count) => {
      const daily = Array.from({ length: days }, (_, index) => ({
        day: String(index), label: String(index), totalTokens: 10,
        segments: [{ model: 'a', tokens: 10 }]
      }))
      await act(async () => root.render(createElement(ModelUsageTrendChart, {
        daily, segmentDays, composerModelMeta: {}
      })))
      const bars = Array.from(container.querySelectorAll<HTMLElement>('.group'))
      expect(bars).toHaveLength(count)
      const total = bars.reduce((sum, bar) => sum + Number(bar.title.match(/: (\d+) tokens/)![1]), 0)
      expect(total).toBe(days * 10)
    }
  )

  it.each([30, 90, 365])('preserves all %i daily bars when daily granularity is requested', async (days) => {
    const daily = Array.from({ length: days }, (_, index) => ({
      day: String(index), label: String(index), totalTokens: 10,
      segments: [{ model: 'a', tokens: 10 }]
    }))
    await act(async () => root.render(createElement(ModelUsageTrendChart, {
      daily, segmentDays: 1, composerModelMeta: {}
    })))
    expect(container.querySelectorAll('.group')).toHaveLength(days)
  })

  it('rounds only the outer top edge of a stacked bar', async () => {
    await act(async () => {
      root.render(
        createElement(ModelUsageTrendChart, {
          daily: [
            {
              day: '2026-08-31',
              label: '8/31',
              totalTokens: 30,
              segments: [
                { model: 'deepseek/v4-flash', tokens: 20 },
                { model: 'deepseek/v4-pro', tokens: 10 }
              ]
            }
          ],
          composerModelMeta: {}
        })
      )
    })

    const bar = container.querySelector<HTMLElement>('.group > span')!
    expect(bar.className).toContain('rounded-t-[3px]')
    expect(Array.from(bar.children).every((segment) => !segment.className.includes('rounded'))).toBe(
      true
    )
  })

  it('keeps model colors aligned with the legend across ranges and filters hidden usage', async () => {
    const day = {
      day: '2026-08-31', label: '8/31', totalTokens: 30,
      segments: [{ model: 'b', tokens: 20 }, { model: 'a', tokens: 10 }]
    }
    for (const days of [7, 30, 90]) {
      const daily = Array.from({ length: days }, (_, index) => ({ ...day, day: String(index) }))
      await act(async () => root.render(createElement(ModelUsageTrendChart, {
        daily, segmentDays: days === 90 ? 2 : 1, modelOrder: ['a', 'b'], composerModelMeta: {}
      })))
      const bars = container.querySelectorAll<HTMLElement>('.group')
      expect(bars.length).toBe(days === 90 ? 45 : days)
      const legend = container.querySelector<HTMLButtonElement>('button:not(.group)')!
      const segment = bars[0]!.querySelector<HTMLElement>('span > span')!
      expect(segment.style.backgroundColor).toBe(legend.querySelector('span')!.style.backgroundColor)
      await act(async () => legend.click())
      expect(bars[0]!.title).toContain(days === 90 ? '40 tokens' : '20 tokens')
      await act(async () => legend.click())
    }
  })
})

describe('line chart', () => {
  it('handles empty and single-day usage and updates accessible values when filtering', async () => {
    await act(async () => root.render(createElement(ModelUsageTrendChart, {
      daily: [], composerModelMeta: {}, variant: 'line'
    })))
    expect(container.querySelector('svg')).toBeNull()
    await act(async () => root.render(createElement(ModelUsageTrendChart, {
      daily: [{ day: '2026-11-08', label: '11/8', totalTokens: 30,
        segments: [{ model: 'a', tokens: 30 }] }],
      composerModelMeta: {}, variant: 'line'
    })))
    expect(container.querySelector('svg')).not.toBeNull()
    expect(container.querySelector('[tabindex="0"]')?.getAttribute('aria-label')).toContain('30 tokens')
    expect(container.querySelector('svg')?.innerHTML).not.toMatch(/NaN|Infinity/)
    await act(async () => container.querySelector<HTMLButtonElement>('button:not(.group)')!.click())
    expect(container.querySelector('[tabindex="0"]')?.getAttribute('aria-label')).toContain('0 tokens')
  })
})


describe('chart point details', () => {
  it.each(['bar', 'line'] as const)('opens %s bucket details, tracks filtering, and dismisses', async (variant) => {
    const daily = Array.from({ length: 3 }, (_, index) => ({
      day: `2026-11-0${index + 1}`, label: `11/${index + 1}`, totalTokens: 30,
      segments: [{ model: 'a', tokens: 10 }, { model: 'b', tokens: 20 }]
    }))
    const props = { daily, segmentDays: 3, variant, composerModelMeta: {} }
    await act(async () => root.render(createElement(ModelUsageTrendChart, props)))
    const point = container.querySelector<HTMLButtonElement>('button.group')!
    await act(async () => point.click())
    expect(point.getAttribute('aria-expanded')).toBe('true')
    expect(container.querySelector('[role="status"]')?.textContent).toContain('2026-11-01 – 2026-11-03')
    expect(container.querySelector('[role="status"]')?.textContent).toContain('90 tokens')
    expect(container.querySelectorAll('dd')).toHaveLength(2)
    await act(async () => container.querySelector<HTMLButtonElement>('button:not(.group)')!.click())
    expect(container.querySelector('[role="status"]')?.textContent).toContain('60 tokens')
    expect(container.querySelectorAll('dd')).toHaveLength(1)
    await act(async () => point.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(container.querySelector('[role="status"]')).toBeNull()
    await act(async () => point.click())
    await act(async () => point.click())
    expect(container.querySelector('[role="status"]')).toBeNull()
    await act(async () => point.click())
    await act(async () => root.render(createElement(ModelUsageTrendChart, { ...props, segmentDays: 1 })))
    expect(container.querySelector('[role="status"]')).toBeNull()
  })

  it('shows zero usage and clears details when the selected day disappears', async () => {
    await act(async () => root.render(createElement(ModelUsageTrendChart, {
      daily: [{ day: '2026-11-08', label: '11/8', totalTokens: 0, segments: [] }], composerModelMeta: {}
    })))
    await act(async () => container.querySelector<HTMLButtonElement>('button.group')!.click())
    expect(container.querySelector('[role="status"]')?.textContent).toContain('0 tokens')
    await act(async () => root.render(createElement(ModelUsageTrendChart, {daily: [], composerModelMeta: {}})))
    expect(container.querySelector('[role="status"]')).toBeNull()
  })
})


it('dismisses details after three seconds and restarts the timer for a new point', async () => {
  vi.useFakeTimers()
  await act(async () => root.render(createElement(ModelUsageTrendChart, {
    daily: [1, 2].map(day => ({ day: `2026-11-0${day}`, label: `11/${day}`, totalTokens: 10, segments: [{model: 'a', tokens: 10}] })),
    composerModelMeta: {}
  })))
  const points = container.querySelectorAll<HTMLButtonElement>('button.group')
  await act(async () => points[0]!.click())
  await act(async () => vi.advanceTimersByTime(2000))
  expect(container.querySelector('[role="status"]')).not.toBeNull()
  await act(async () => points[1]!.click())
  await act(async () => vi.advanceTimersByTime(2999))
  expect(container.querySelector('[role="status"]')?.textContent).toContain('2026-11-02')
  await act(async () => vi.advanceTimersByTime(1))
  expect(container.querySelector('[role="status"]')).toBeNull()
  expect(points[1]!.getAttribute('aria-expanded')).toBe('false')
})


it.each(['bar', 'line'] as const)('clears the %s point highlight with its detail', async (variant) => {
  vi.useFakeTimers()
  await act(async () => root.render(createElement(ModelUsageTrendChart, {
    daily: [{day: '2026-11-08', label: '11/8', totalTokens: 10, segments: [{model: 'a', tokens: 10}]}],
    variant, composerModelMeta: {}, colorScheme: 'purple'
  })))
  const segment = container.querySelector<HTMLElement>('button.group > span > span')!
  const originalColor = segment.style.backgroundColor
  await act(async () => container.querySelector<HTMLButtonElement>('button.group')!.click())
  if (variant === 'line') {
    expect(container.querySelector('[data-chart-selection="line"]')).not.toBeNull()
  } else {
    expect(segment.style.backgroundColor).not.toBe(originalColor)
  }
  await act(async () => vi.advanceTimersByTime(3000))
  expect(container.querySelector('[data-chart-selection="line"]')).toBeNull()
  expect(segment.style.backgroundColor).toBe(originalColor)
})


describe('idle usage presentation', () => {
  it.each([
    {values: [10, 0, 0, 0, 20], expected: ['active', 'idle', 'active']},
    {values: [0, 0, 0], expected: ['idle']},
    {values: [10, 0, 20], expected: ['active']},
    {values: [0], expected: ['idle']},
    {values: [10], expected: ['active']},
    {values: [], expected: []}
  ])('renders $values without coloring idle spans as usage', async ({values, expected}) => {
    await act(async () => root.render(createElement(ModelUsageTrendChart, {
      daily: values.map((tokens, index) => ({day: String(index), label: String(index), totalTokens: tokens, segments: [{model: 'a', tokens}]})),
      variant: 'line', composerModelMeta: {}
    })))
    const strokes = Array.from(container.querySelectorAll('[data-usage-stroke]'))
    expect(strokes.map(path => path.getAttribute('data-usage-stroke'))).toEqual(expected)
    if (values.length > 1) {
      for (const path of strokes) {
        expect(path.getAttribute('stroke-dasharray')).toBe(path.getAttribute('data-usage-stroke') === 'idle' ? '4 4' : null)
      }
    }
  })

  it('turns the line into an idle baseline when all models are hidden', async () => {
    await act(async () => root.render(createElement(ModelUsageTrendChart, {
      daily: [1, 2].map(day => ({day: String(day), label: String(day), totalTokens: 10, segments: [{model: 'a', tokens: 10}]})),
      variant: 'line', composerModelMeta: {}
    })))
    await act(async () => container.querySelector<HTMLButtonElement>('button:not(.group)')!.click())
    expect(container.querySelector('[data-usage-stroke="active"]')).toBeNull()
    expect(container.querySelector('[data-usage-stroke="idle"]')).not.toBeNull()
  })
})
