import { expect, it, vi } from 'vitest'

vi.mock('electron', () => ({}))

const { pickPreviewWindow } = await import('./cua-window-preview')

const window = (id: number, width = 1200, height = 800, layer = 0, alpha = 1) => ({ id, width, height, layer, alpha })

it('picks the frontmost normal window of the app', () => {
  // CGWindowList order is front to back; strips, palettes and invisible windows are skipped.
  expect(pickPreviewWindow([
    window(1, 1512, 33),
    window(2, 64, 64, 3),
    window(3, 900, 600, 0, 0),
    window(4),
    window(5)
  ])).toBe(4)
  expect(pickPreviewWindow([window(1, 1512, 33)])).toBeNull()
  expect(pickPreviewWindow([])).toBeNull()
})
