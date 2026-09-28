// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { DiffView, highlightChangedText } from './DiffView'
vi.mock('./chat/FileChip', () => ({ FileChip: () => null }))
vi.mock('../lib/use-code-highlights', () => ({ useCodeHighlights: () => null }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, values?: { count: number }) => values ? `${key}:${values.count}` : key }) }))

it('wraps by default when switching into split view and preserves an explicit no-wrap choice', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const patch = '@@ -1 +1 @@\n-old\n+new'
  try {
    await act(async () => root.render(createElement(DiffView, { patch, showStyleToggle: true })))
    expect(container.querySelector('[data-wrap]')).not.toBeNull()
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="Split diff"]')!.click())
    expect(container.querySelector('[data-wrap]')).not.toBeNull()
    expect(container.querySelectorAll('col')).toHaveLength(4)
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="diffWrapLines"]')!.click())
    expect(container.querySelector('[data-wrap]')).toBeNull()
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="Unified diff"]')!.click())
    expect(container.querySelector('[data-wrap]')).toBeNull()
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="diffWrapLines"]')!.click())
    expect(container.querySelector('[data-wrap]')).not.toBeNull()
    await act(async () => root.render(createElement(DiffView, { patch, diffStyle: 'split' })))
    expect(container.querySelector('[data-wrap]')).not.toBeNull()
  } finally {
    act(() => root.unmount())
    container.remove()
  }
})

it('marks only the changed range without losing syntax colors or interpreting source as HTML', () => {
  const html = highlightChangedText('return next()', '<span style="color:red">return</span> next()', 'return first()')
  expect(html).toContain('<span style="color:red">return</span> ')
  expect(html).toContain('<mark class="ds-diff-inline-change">nex</mark>t()')
  expect(highlightChangedText('<script>&', undefined, null)).toContain('&lt;script&gt;&amp;')
  expect(highlightChangedText('unchanged', undefined, 'unchanged')).toBe('unchanged')
})

it('preserves source prefixes, ignores metadata, folds both views, and resets for another patch', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const patch = ['diff --git a/a.ts b/a.ts', '--- a/a.ts', '+++ b/a.ts', '@@ -1,16 +1,16 @@', '--- old', '+++ new', '\\ No newline at end of file', ...Array.from({length:14}, (_, i) => ` context${i}`), '-end', '+finish', ''].join('\n')
  try {
    await act(async () => root.render(createElement(DiffView, { patch, diffStyle: 'split', filePath: 'a.ts' })))
    expect(container.textContent).toContain('-- old')
    expect(container.textContent).not.toContain('No newline at end')
    expect(container.querySelectorAll('tbody tr')).toHaveLength(10)
    expect(container.textContent).toContain('diffUnmodifiedLines:8')
    await act(async () => container.querySelector<HTMLButtonElement>('.ds-diff-fold button')!.click())
    expect(container.querySelectorAll('tbody tr')).toHaveLength(17)
    const last = container.querySelector('tbody tr:last-child')!
    expect(last.children[0].textContent).toBe('16')
    expect(last.children[2].textContent).toBe('16')
    await act(async () => root.render(createElement(DiffView, { patch: patch.replace('finish', 'done'), diffStyle: 'split' })))
    expect(container.querySelector('.ds-diff-fold')).not.toBeNull()
    await act(async () => root.render(createElement(DiffView, { patch, diffStyle: 'unified' })))
    expect(container.textContent).toContain('diffUnmodifiedLines:8')
    expect(container.querySelector('mark')).not.toBeNull()
  } finally {
    act(() => root.unmount())
    container.remove()
  }
})


it('navigates between hunks and keeps bare patches readable', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(DiffView, { patch: '@@ -1 +1 @@\n-a\n+b\n@@ -9 +9 @@\n-c\n+d', diffStyle: 'split' })))
    expect(container.querySelector('[data-wrap]')).not.toBeNull()
    const hunks = container.querySelectorAll<HTMLElement>('[data-diff-hunk]')
    const first = hunks[0]!.scrollIntoView = vi.fn()
    const second = hunks[1]!.scrollIntoView = vi.fn()
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="diffNextChange"]')!.click())
    expect(second).toHaveBeenCalledWith({ block: 'start' })
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="diffNextChange"]')!.click())
    expect(first).toHaveBeenCalled()
    await act(async () => root.render(createElement(DiffView, { patch: '-old\n+new\n', diffStyle: 'split' })))
    expect(container.textContent).toContain('old')
    expect(container.textContent).toContain('new')
    expect(container.querySelector<HTMLButtonElement>('[aria-label="diffNextChange"]')!.disabled).toBe(true)
  } finally {
    act(() => root.unmount())
    container.remove()
  }
})
