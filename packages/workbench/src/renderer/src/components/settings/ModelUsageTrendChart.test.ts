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
