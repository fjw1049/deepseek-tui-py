// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { createPanelWidthDrag } from './panel-width-drag'

afterEach(() => {
  document.documentElement.style.removeProperty('--ds-ui-scale')
  vi.restoreAllMocks()
})

it.each([0.83, 0.88, 0.95, 1])('tracks screen movement without jumping at scale %s', scale => {
  document.documentElement.style.setProperty('--ds-ui-scale', String(scale))
  const pane = document.createElement('div')
  vi.spyOn(pane, 'getBoundingClientRect').mockReturnValue({ width: 300 * scale } as DOMRect)
  const move = createPanelWidthDrag(pane, 500, 300, 0, 420, -1)
  expect(move(500)).toBeCloseTo(300)
  expect(move(500 - 40 * scale)).toBeCloseTo(340)
  expect(move(500 - 20 * scale)).toBeCloseTo(320)
})

it.each([0.5, 0.6])('uses the actual parent limit %s and reverses immediately at either edge', fraction => {
  document.documentElement.style.setProperty('--ds-ui-scale', '0.88')
  const parent = document.createElement('div')
  const pane = parent.appendChild(document.createElement('div'))
  vi.spyOn(parent, 'clientWidth', 'get').mockReturnValue(500)
  vi.spyOn(pane, 'getBoundingClientRect').mockReturnValue({ width: 200 * 0.88 } as DOMRect)
  const move = createPanelWidthDrag(pane, 500, 200, 0, 420, 1, fraction)
  expect(move(1000)).toBe(500 * fraction)
  expect(move(991.2)).toBeCloseTo(500 * fraction - 10)
  expect(move(0)).toBe(0)
  expect(move(8.8)).toBeCloseTo(10)
})
