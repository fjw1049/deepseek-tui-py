// @vitest-environment happy-dom
import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { DiffView, highlightChangedText } from './DiffView'
vi.mock('./chat/FileChip', () => ({ FileChip: () => null }))
vi.mock('../lib/use-code-highlights', () => ({ useCodeHighlights: () => null }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, values?: { count: number }) => values ? `${key}:${values.count}` : key }) }))

it.each(['unified', 'split'] as const)('keeps changes visible while full context loads in %s view', async (diffStyle) => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(DiffView, {
      patch: '@@ -1 +1 @@\n-old-value\n+current-value',
      showFullFile: true, fullFilePending: true, diffStyle
    })))
    expect(host.textContent).toContain('diffLoadingFullFile')
    expect(host.querySelector('tbody')?.textContent).toContain('current-value')
    expect(host.querySelector<HTMLButtonElement>('[aria-label="diffNextChange"]')?.disabled).toBe(false)
  } finally { await act(async () => root.unmount()); host.remove() }
})

it('wraps by default when switching into split view and preserves an explicit no-wrap choice', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const patch = '@@ -1 +1 @@\n-old\n+new'
  try {
    await act(async () => root.render(createElement(DiffView, { patch, showStyleToggle: true })))
    expect(container.querySelector('[data-wrap]')).not.toBeNull()
    expect(container.querySelectorAll('[aria-label^="diffSwitchTo"]')).toHaveLength(1)
    const layoutIcon = container.querySelector('[aria-label="diffSwitchToSplit"] svg')!.innerHTML
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="diffSwitchToSplit"]')!.click())
    expect(container.querySelectorAll('[aria-label^="diffSwitchTo"]')).toHaveLength(1)
    expect(container.querySelector('[aria-label="diffSwitchToUnified"] svg')!.innerHTML).not.toBe(layoutIcon)
    expect(container.querySelector('[data-wrap]')).not.toBeNull()
    expect(container.querySelectorAll('col')).toHaveLength(4)
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="diffWrapLines"]')!.click())
    expect(container.querySelector('[data-wrap]')).toBeNull()
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="diffSwitchToUnified"]')!.click())
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


it.each(['unified', 'split'] as const)('navigates from the visible position in %s view and confines scrolling to the diff', async (diffStyle) => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(DiffView, {
      patch: '@@ -20 +20 @@\n-a\n+b\n@@ -60 +60 @@\n-c\n+d', diffStyle
    })))
    const viewport = host.querySelector<HTMLElement>('.ds-change-inspector__code')!
    Object.defineProperty(viewport, 'offsetHeight', { value: 500 })
    viewport.getBoundingClientRect = () => ({ top: 40, height: 750 }) as DOMRect
    const scrollTo = viewport.scrollTo = vi.fn((options?: ScrollToOptions | number, y?: number) => { viewport.scrollTop = typeof options === 'number' ? y ?? 0 : options?.top ?? 0 })
    const hunks = host.querySelectorAll<HTMLElement>('[data-diff-hunk]')
    hunks.forEach((row, i) => {
      row.getBoundingClientRect = () => ({ top: 40 + ([200, 600][i]! - viewport.scrollTop) * 1.5 }) as DOMRect
      row.scrollIntoView = vi.fn()
    })
    const click = (label: string) => act(() => host.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!.click())
    click('diffNextChange')
    expect(viewport.scrollTop).toBe(200)
    click('diffNextChange')
    expect(viewport.scrollTop).toBe(600)
    click('diffNextChange')
    expect(viewport.scrollTop).toBe(200)
    viewport.scrollTop = 500
    click('diffPreviousChange')
    expect(viewport.scrollTop).toBe(200)
    viewport.scrollTop = 100
    click('diffNextChange')
    expect(viewport.scrollTop).toBe(200)
    click('diffPreviousChange')
    expect(viewport.scrollTop).toBe(600)
    expect(scrollTo).toHaveBeenCalled()
    hunks.forEach(row => expect(row.scrollIntoView).not.toHaveBeenCalled())
  } finally { await act(async () => root.unmount()); host.remove() }
})

it('toggles full context beside expand/collapse and navigates changes in both layouts', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const patch = '@@ -12 +12 @@\n-old\n+new\n@@ -29 +29 @@\n-end\n+finish'
  const fullFilePatch = ['@@ -1,40 +1,40 @@', ...Array.from({ length: 11 }, (_, i) => ` leading${i}`),
    '-old', '+new', ...Array.from({ length: 16 }, (_, i) => ` middle${i}`), '-end', '+finish',
    ...Array.from({ length: 11 }, (_, i) => ` trailing${i}`)].join('\n')
  function Harness() {
    const [showFullFile, setShowFullFile] = useState(true)
    return createElement(DiffView, {
      patch, fullFilePatch, showFullFile, showStyleToggle: true,
      onToggleFullFile: () => setShowFullFile((value) => !value),
      onToggleExpand: vi.fn(), onCollapse: vi.fn()
    })
  }
  const click = async (label: string) => act(async () => container.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!.click())
  try {
    await act(async () => root.render(createElement(Harness)))
    for (const style of ['unified', 'split']) {
      if (style === 'split') await click('diffSwitchToSplit')
      expect(container.textContent).toContain('leading0')
      expect(container.textContent).toContain('middle8')
      expect(container.textContent).toContain('trailing10')
      expect(container.textContent).not.toContain('@@')
      expect(container.querySelector('.ds-diff-meta-sticky')).toBeNull()
      expect(container.querySelector('tbody tr td')?.textContent).toBe('1')
      expect(container.querySelector('[title="diffExpandContext"]')).toBeNull()
      expect(container.querySelectorAll('mark').length).toBeGreaterThan(0)
      const hunks = container.querySelectorAll<HTMLElement>('[data-diff-hunk]')
      expect(hunks).toHaveLength(2)
      const viewport = container.querySelector<HTMLElement>('.ds-change-inspector__code')!
      viewport.getBoundingClientRect = () => ({ top: 0, height: 500 }) as DOMRect
      Object.defineProperty(viewport, 'offsetHeight', { value: 500, configurable: true })
      hunks[0]!.getBoundingClientRect = () => ({ top: 200 }) as DOMRect
      hunks[1]!.getBoundingClientRect = () => ({ top: 600 }) as DOMRect
      const scrollTo = viewport.scrollTo = vi.fn()
      await click('diffNextChange')
      expect(scrollTo).toHaveBeenCalledWith({ top: 200 })
      const toggle = container.querySelector('[aria-label="diffShowChangesOnly"]')!
      expect(toggle.getAttribute('aria-pressed')).toBe('false')
      expect(toggle.parentElement?.nextElementSibling?.querySelector('button')?.getAttribute('aria-label')).toBe('inspectorExpandDiff')
      await click('diffShowChangesOnly')
      expect(container.textContent).not.toContain('leading0')
      expect(container.textContent).not.toContain('middle8')
      expect(container.textContent).not.toContain('trailing10')
      expect(container.textContent).toContain('finish')
      expect(container.textContent).toContain('@@ -12 +12 @@')
      expect(container.querySelector('[aria-label="diffShowFullFile"]')?.getAttribute('aria-pressed')).toBe('true')
      await click('diffShowFullFile')
    }
  } finally {
    act(() => root.unmount())
    container.remove()
  }
})

it('falls back to changed hunks instead of rendering an oversized full file', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(DiffView, {
      patch: '@@ -9000 +9000 @@\n-old-value\n+updated-value',
      fullFilePatch: '@@ -1,10000 +1,10000 @@\n' + ' context\n'.repeat(9999) + '+updated-value',
      showFullFile: true
    })))
    expect(host.textContent).toContain('updated-value')
    expect(host.textContent).toContain('diffPreviewLimited')
    expect(host.querySelectorAll('tbody tr').length).toBeLessThan(20)
  } finally { await act(async () => root.unmount()); host.remove() }
})


it('does not reset scrolling when full context arrives, but resets for another file', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const patch = '@@ -40 +40 @@\n-old-value\n+current-value'
  try {
    await act(async () => root.render(createElement(DiffView, {
      patch, filePath: 'a.ts', showFullFile: true, fullFilePending: true
    })))
    const viewport = host.querySelector<HTMLElement>('.ds-change-inspector__code')!
    const scrollTo = vi.fn()
    viewport.scrollTo = scrollTo
    viewport.scrollTop = 180
    await act(async () => root.render(createElement(DiffView, {
      patch, filePath: 'a.ts', showFullFile: true,
      fullFilePatch: '@@ -1,40 +1,40 @@\n' + ' context\n'.repeat(39) + '-old-value\n+current-value'
    })))
    expect(host.querySelector('.ds-change-inspector__code')).toBe(viewport)
    expect(scrollTo).not.toHaveBeenCalled()
    expect(viewport.scrollTop).toBe(180)
    await act(async () => root.render(createElement(DiffView, {
      patch, filePath: 'b.ts', showFullFile: true, fullFilePending: true
    })))
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, left: 0 })
  } finally { await act(async () => root.unmount()); host.remove() }
})
