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
})
