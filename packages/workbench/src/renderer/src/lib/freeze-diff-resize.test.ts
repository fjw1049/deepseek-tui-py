// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { freezeDiffResize } from './freeze-diff-resize'

afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })
function fixture() {
  const root = document.createElement('div')
  root.innerHTML = '<div class="ds-diff-view" data-wrap data-diff-path="a.ts"><div><table class="ds-diff-table"><tbody><tr><td>first</td></tr><tr><td>second</td></tr><tr><td>third</td></tr></tbody></table></div></div>'
  document.body.append(root)
  const view = root.firstElementChild as HTMLElement
  const viewport = view.firstElementChild as HTMLElement
  const table = viewport.firstElementChild as HTMLTableElement
  Object.defineProperty(table, 'offsetWidth', { configurable: true, value: 600 })
  Object.defineProperty(viewport, 'clientHeight', { value: 100 })
  Object.defineProperty(viewport, 'offsetHeight', { value: 100 })
  vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ top: 100, height: 200 } as DOMRect)
  return { root, view, viewport, table }
}

it('fixes width and minimum width, then restores the original inline styles exactly once', () => {
  const { root, viewport, table } = fixture()
  table.style.width = '100%'
  table.style.minWidth = '100%'
  viewport.style.overflowX = 'auto'
  viewport.style.overflowAnchor = 'auto'
  const restore = freezeDiffResize(root)
  expect(table.style.width).toBe('600px')
  expect(table.style.minWidth).toBe('600px')
  expect(table.style.maxWidth).toBe('600px')
  expect(viewport.style.overflowX).toBe('hidden')
  expect(viewport.style.overflowAnchor).toBe('none')
  restore()
  expect(table.style.width).toBe('100%')
  expect(table.style.minWidth).toBe('100%')
  expect(table.style.maxWidth).toBe('')
  expect(viewport.style.overflowX).toBe('auto')
  expect(viewport.style.overflowAnchor).toBe('auto')
  table.style.width = '80%'
  restore()
  expect(table.style.width).toBe('80%')
})

it('keeps the visible source row and fractional offset after wrapping changes, including UI scaling', () => {
  const { root, viewport, table } = fixture()
  viewport.scrollTop = 40
  let released = false
  vi.spyOn(table.rows[0], 'getBoundingClientRect').mockReturnValue({ top: 20, bottom: 60, height: 40 } as DOMRect)
  vi.spyOn(table.rows[1], 'getBoundingClientRect').mockImplementation(() => released
    ? { top: 180, bottom: 300, height: 120 } as DOMRect
    : { top: 60, bottom: 140, height: 80 } as DOMRect)
  const restore = freezeDiffResize(root)
  released = true
  restore()
  expect(viewport.scrollTop).toBe(110)
  restore()
  expect(viewport.scrollTop).toBe(110)
})

it('does not change the scroll position of a newly selected file', () => {
  const { root, view, viewport, table } = fixture()
  const restore = freezeDiffResize(root)
  view.dataset.diffPath = 'b.ts'
  viewport.scrollTop = 90
  restore()
  expect(viewport.scrollTop).toBe(90)
  expect(table.style.width).toBe('')
})

it('skips unwrapped and hidden tables and safely releases detached content', () => {
  const { root, view, table } = fixture()
  view.removeAttribute('data-wrap')
  freezeDiffResize(root)()
  expect(table.style.width).toBe('')
  view.setAttribute('data-wrap', '')
  Object.defineProperty(table, 'offsetWidth', { value: 0 })
  freezeDiffResize(root)()
  expect(table.style.width).toBe('')
  Object.defineProperty(table, 'offsetWidth', { value: 600 })
  const restore = freezeDiffResize(root)
  root.remove()
  expect(() => restore()).not.toThrow()
  expect(table.style.width).toBe('')
})
