// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
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

    const bar = container.querySelector<HTMLElement>('.group > div')!
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
      const legend = container.querySelector<HTMLButtonElement>('button')!
      const segment = bars[0]!.querySelector<HTMLElement>('span')!
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
    await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())
    expect(container.querySelector('[tabindex="0"]')?.getAttribute('aria-label')).toContain('0 tokens')
  })
})
