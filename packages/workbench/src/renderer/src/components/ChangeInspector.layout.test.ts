// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useChatStore } from '../store/chat-store'
import { ChangeInspector } from './ChangeInspector'
import { useGitWorkingChanges } from '../hooks/use-git-working-changes'
import type { GitFileDiffResult, GitFileDiffTarget } from '@shared/git-working-changes'

vi.mock('./chat/FileChip', () => ({ FileChip: () => null, FileTypeIcon: () => null }))
vi.mock('react-i18next', async (importOriginal) => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../hooks/use-git-working-changes', () => {
  const reload = vi.fn()
  const result = { ok: true, files: [
    { path: 'src/a.ts', stage: 'unstaged', status: 'modified', patch: '@@ -1 +1 @@\n-old\n+new', additions: 1, deletions: 1 },
    { path: 'src/b.ts', stage: 'unstaged', status: 'modified', patch: '@@ -1 +1 @@\n-old\n+next', additions: 1, deletions: 1 }
  ] }
  return {
    useGitWorkingChanges: vi.fn(() => ({ result, loading: false, reload })),
    useGitBranchCompareBase: () => ['main', reload]
  }
})
vi.mock('../hooks/use-git-branches', () => {
  const reload = vi.fn()
  return { useGitBranches: () => ({ result: null, reload }) }
})
vi.mock('../hooks/use-github-repository', () => ({ useGitHubRepository: () => ({ result: null }) }))
vi.mock('../hooks/use-workspace-dirty-git-refresh', () => ({ useWorkspaceDirtyGitRefresh: () => {} }))

let container: HTMLDivElement
let root: Root
const initial = useChatStore.getState()
const button = (label: string): HTMLButtonElement => container.querySelector(`[aria-label="${label}"]`)!
const separator = (): HTMLDivElement => container.querySelector('[aria-orientation="horizontal"]')!
const listPane = (): HTMLElement => container.querySelector('ul')!.parentElement!.parentElement!.parentElement!.parentElement!

beforeEach(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  useChatStore.setState({ workspaceRoot: '/repo', activeThreadId: null, inspectorSelectedId: null })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  await act(async () => root.render(createElement(ChangeInspector)))
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  useChatStore.setState(initial, true)
})

it('expands with files on the right, preserves selection, and restores height and collapse behavior', () => {
  const pane = listPane()
  const height = pane.style.height
  const selected = useChatStore.getState().inspectorSelectedId
  act(() => button('inspectorExpandDiff').click())
  expect(pane.classList.contains('order-2')).toBe(true)
  expect(separator().hidden).toBe(true)
  expect(useChatStore.getState().inspectorSelectedId).toBe(selected)
  act(() => container.querySelector<HTMLButtonElement>('ul button[title]:not([aria-current="true"])')!.click())
  const nextSelected = useChatStore.getState().inspectorSelectedId
  expect(nextSelected).not.toBe(selected)
  expect(pane.classList.contains('order-2')).toBe(true)
  act(() => button('inspectorRestoreDiff').click())
  expect(useChatStore.getState().inspectorSelectedId).toBe(nextSelected)
  expect(pane.classList.contains('order-2')).toBe(false)
  expect(pane.style.height).toBe(height)
  expect(separator().hidden).toBe(false)
  act(() => button('inspectorCollapseDiff').click())
  expect(container.querySelector('[aria-orientation="horizontal"]')).toBeNull()
})

it('defaults to full files, ignores stale responses, resets on selection and keeps changes accessible after a load failure', async () => {
  let resolveFirst!: (result: GitFileDiffResult) => void
  const first = new Promise<GitFileDiffResult>((resolve) => { resolveFirst = resolve })
  const getGitFileDiff = vi.fn((target: GitFileDiffTarget) => target.path === 'src/a.ts'
    ? first : Promise.resolve({ ok: true as const, patch: '@@ -1,2 +1,2 @@\n-old\n+next\n second-tail' }))
  vi.stubGlobal('dsGui', { getGitFileDiff })
  try {
    await act(async () => {
      useChatStore.getState().selectInspectorItem('git:branch:unstaged:src/a.ts')
      root.render(createElement(ChangeInspector, { key: 'full-context' }))
    })
    expect(container.textContent).toContain('diffLoadingFullFile')
    expect(getGitFileDiff).toHaveBeenCalledWith(expect.objectContaining({
      workspaceRoot: '/repo', path: 'src/a.ts', scope: 'branch', baseRef: 'main'
    }))
    await act(async () => container.querySelector<HTMLButtonElement>('ul button[title]:not([aria-current="true"])')!.click())
    expect(container.textContent).toContain('second-tail')
    await act(async () => resolveFirst({ ok: true, patch: '@@ -1,2 +1,2 @@\n-old\n+new\n first-tail' }))
    expect(container.textContent).not.toContain('first-tail')
    await act(async () => button('diffShowChangesOnly').click())
    expect(container.textContent).not.toContain('second-tail')
    expect(button('diffShowFullFile').getAttribute('aria-pressed')).toBe('true')
    await act(async () => container.querySelector<HTMLButtonElement>('ul button[title]:not([aria-current="true"])')!.click())
    expect(button('diffShowChangesOnly').getAttribute('aria-pressed')).toBe('false')
    expect(container.textContent).toContain('first-tail')
    getGitFileDiff.mockRejectedValueOnce(new Error('unavailable'))
    await act(async () => container.querySelector<HTMLButtonElement>('ul button[title]:not([aria-current="true"])')!.click())
    expect(container.textContent).toContain('diffFullFileUnavailable')
    expect(container.textContent).toContain('next')
    await act(async () => button('diffShowChangesOnly').click())
    expect(container.textContent).not.toContain('diffFullFileUnavailable')
  } finally {
    vi.unstubAllGlobals()
  }
})

it('snaps at the top on release, restores the previous height, and does not expand on cancellation', () => {
  const pane = listPane()
  const height = pane.style.height
  const handle = separator()
  handle.setPointerCapture = vi.fn()
  handle.releasePointerCapture = vi.fn()
  const drag = (type: string, clientY: number): void => {
    act(() => { handle.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: 1, clientY })) })
  }
  drag('pointerdown', 220)
  drag('pointermove', 10)
  expect(pane.style.height).toBe('10px')
  drag('pointercancel', 10)
  expect(pane.style.height).toBe(height)
  expect(button('inspectorRestoreDiff')).toBeNull()
  drag('pointerdown', 220)
  drag('pointermove', 10)
  drag('pointerup', 10)
  expect(button('inspectorRestoreDiff')).not.toBeNull()
  act(() => button('inspectorRestoreDiff').click())
  expect(pane.style.height).toBe(height)
})

it('supports keyboard resizing within bounds and resetting the horizontal split', () => {
  const handle = separator()
  const pane = listPane()
  expect(handle.tabIndex).toBe(0)
  expect(handle.title).toBe('inspectorResizeSplitHint')
  const key = (value: string, shiftKey = false): void => {
    act(() => { handle.dispatchEvent(new KeyboardEvent('keydown', { key: value, shiftKey, bubbles: true })) })
  }
  key('ArrowDown')
  expect(pane.style.height).toBe('236px')
  key('ArrowUp', true)
  expect(pane.style.height).toBe('204px')
  key('Home')
  key('ArrowUp')
  expect(handle.getAttribute('aria-valuenow')).toBe('120')
  key('End')
  key('ArrowDown')
  expect(handle.getAttribute('aria-valuenow')).toBe('420')
  key('Enter')
  expect(pane.style.height).toBe('220px')
  key('ArrowDown')
  act(() => { handle.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })) })
  expect(pane.style.height).toBe('220px')
  expect(button('inspectorRestoreDiff')).toBeNull()
})

it.each(['lostpointercapture', 'pointermove'])('cancels horizontal dragging after %s without continuing to follow the mouse', (interruption) => {
  const handle = separator()
  const pane = listPane()
  handle.setPointerCapture = vi.fn()
  const pointer = (type: string, clientY: number, buttons: number, pointerId = 1, button = 0): void => {
    act(() => { handle.dispatchEvent(new PointerEvent(type, {
      bubbles: true, pointerType: 'mouse', pointerId, button, clientY, buttons
    })) })
  }
  pointer('pointerdown', 220, 2, 1, 2)
  expect(handle.hasAttribute('data-resizing')).toBe(false)
  pointer('pointerdown', 220, 1)
  expect(handle.hasAttribute('data-resizing')).toBe(true)
  pointer('pointermove', 400, 1, 2)
  expect(pane.style.height).toBe('220px')
  pointer('pointerup', 400, 0, 2)
  expect(handle.hasAttribute('data-resizing')).toBe(true)
  pointer('pointermove', 10, 1)
  expect(pane.style.height).toBe('10px')
  pointer(interruption, 10, 0)
  expect(pane.style.height).toBe('220px')
  expect(handle.hasAttribute('data-resizing')).toBe(false)
  pointer('pointermove', 300, 1)
  expect(pane.style.height).toBe('220px')
  expect(button('inspectorRestoreDiff')).toBeNull()
})

it('tracks horizontal dragging in layout pixels at a larger UI scale', () => {
  const handle = separator()
  handle.setPointerCapture = vi.fn()
  document.documentElement.style.setProperty('--ds-ui-scale', '1.5')
  try {
    for (const [type, clientY] of [['pointerdown', 330], ['pointermove', 390], ['pointerup', 390]] as const) {
      act(() => { handle.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: 1, clientY })) })
    }
    expect(listPane().style.height).toBe('260px')
    expect(handle.hasAttribute('data-resizing')).toBe(false)
  } finally {
    document.documentElement.style.removeProperty('--ds-ui-scale')
  }
})

it('keeps the diff visible in short panels and restores the preferred height when space returns', async () => {
  let resize!: (height: number) => void
  const disconnect = vi.fn()
  vi.stubGlobal('ResizeObserver', class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(): void {
      resize = height => this.callback([{ contentRect: { height } } as ResizeObserverEntry], this as unknown as ResizeObserver)
    }
    disconnect = disconnect
  })
  try {
    await act(async () => root.render(createElement(ChangeInspector, { key: 'short-panel' })))
    const handle = separator()
    act(() => resize(320))
    expect(listPane().style.height).toBe('168px')
    expect(handle.getAttribute('aria-valuemax')).toBe('168')
    act(() => resize(240))
    expect(listPane().style.height).toBe('88px')
    expect(handle.getAttribute('aria-valuemin')).toBe('88')
    act(() => { handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })) })
    expect(listPane().style.height).toBe('88px')
    act(() => { handle.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })) })
    act(() => resize(700))
    expect(listPane().style.height).toBe('220px')
    act(() => resize(0))
    expect(listPane().style.height).toBe('220px')
    await act(async () => root.render(createElement(ChangeInspector, { variant: 'list', key: 'short-panel' })))
    expect(disconnect).toHaveBeenCalledOnce()
  } finally {
    vi.unstubAllGlobals()
  }
})

it('resizes the fullscreen directory to zero width and restores the last width', () => {
  expect(container.querySelector('[aria-label="inspectorResizeFileList"]')).toBeNull()
  act(() => button('inspectorExpandDiff').click())
  const pane = listPane()
  const handle = container.querySelector<HTMLDivElement>('[aria-label="inspectorResizeFileList"]')!
  handle.setPointerCapture = vi.fn()
  handle.releasePointerCapture = vi.fn()
  vi.spyOn(pane, 'getBoundingClientRect').mockImplementation(() => ({ width: parseFloat(pane.style.width) }) as DOMRect)
  const drag = (type: string, clientX: number): void => {
    act(() => { handle.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: 1, clientX })) })
  }
  drag('pointerdown', 500)
  drag('pointermove', 460)
  drag('pointerup', 460)
  expect(pane.style.width).toBe('320px')
  drag('pointerdown', 500)
  drag('pointermove', 700)
  expect(pane.style.width).toBe('120px')
  drag('pointermove', 760)
  expect(pane.style.width).toBe('60px')
  expect(parseFloat(container.querySelector<HTMLElement>('[data-change-file-list]')!.style.opacity)).toBeLessThan(1)
  expect(parseFloat(button('inspectorExpandFileList').style.opacity)).toBeGreaterThan(0)
  drag('pointermove', 840)
  drag('pointerup', 840)
  expect(pane.style.width).toBe('0px')
  expect(pane.classList.contains('border-l')).toBe(false)
  expect(pane.contains(button('inspectorExpandFileList'))).toBe(false)
  expect(handle.querySelector('span')?.classList.contains('opacity-0')).toBe(true)
  expect(container.querySelector('ul')!.closest('.hidden')).not.toBeNull()
  act(() => button('inspectorExpandFileList').click())
  expect(pane.style.width).toBe('320px')
  expect(container.querySelector('ul')!.closest('.hidden')).toBeNull()
  drag('pointerdown', 500)
  drag('pointermove', 760)
  drag('pointerup', 760)
  expect(pane.style.width).toBe('60px')
  act(() => button('inspectorExpandFileList').click())
  expect(pane.style.width).toBe('320px')
  drag('pointerdown', 500)
  drag('pointermove', 840)
  drag('pointerup', 840)
  drag('pointerdown', 500)
  drag('pointermove', 300)
  drag('pointerup', 300)
  expect(pane.style.width).toBe('200px')
  drag('pointerdown', 500)
  drag('pointermove', 800)
  drag('pointercancel', 800)
  expect(pane.style.width).toBe('200px')
  act(() => button('inspectorRestoreDiff').click())
  expect(pane.style.height).toBe('220px')
  expect(container.querySelector('[aria-label="inspectorResizeFileList"]')).toBeNull()
})

it('supports keyboard resizing and toggling the fullscreen directory', () => {
  act(() => button('inspectorExpandDiff').click())
  const handle = container.querySelector<HTMLDivElement>('[aria-label="inspectorResizeFileList"]')!
  const key = (value: string): void => {
    act(() => { handle.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true })) })
  }
  key('ArrowLeft')
  expect(handle.getAttribute('aria-valuenow')).toBe('312')
  key('Enter')
  expect(handle.getAttribute('aria-valuenow')).toBe('0')
  act(() => button('inspectorExpandFileList').click())
  expect(handle.getAttribute('aria-valuenow')).toBe('312')
  key('ArrowRight')
  expect(handle.getAttribute('aria-valuenow')).toBe('280')
  for (let i = 0; i < 9; i++) key('ArrowRight')
  expect(handle.getAttribute('aria-valuenow')).toBe('0')
  act(() => button('inspectorExpandFileList').click())
  expect(handle.getAttribute('aria-valuenow')).toBe('184')
})

it('uses the file pane width when dragging again beside the expand icon', () => {
  act(() => button('inspectorExpandDiff').click())
  const pane = listPane()
  const handle = container.querySelector<HTMLDivElement>('[aria-label="inspectorResizeFileList"]')!
  handle.setPointerCapture = vi.fn()
  handle.releasePointerCapture = vi.fn()
  vi.spyOn(pane, 'getBoundingClientRect').mockImplementation(() => ({ width: parseFloat(pane.style.width) }) as DOMRect)
  const drag = (type: string, clientX: number): void => {
    act(() => { handle.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: 1, clientX })) })
  }

  drag('pointerdown', 500)
  drag('pointermove', 720)
  drag('pointerup', 720)
  expect(pane.style.width).toBe('60px')
  vi.spyOn(button('inspectorExpandFileList'), 'getBoundingClientRect').mockReturnValue({ width: 28 } as DOMRect)

  drag('pointerdown', 500)
  drag('pointermove', 480)
  expect(pane.style.width).toBe('80px')
  drag('pointerup', 480)
  drag('pointermove', 440)
  expect(pane.style.width).toBe('80px')
})

it.each([
  { name: 'pointer capture is lost', loseCapture: true },
  { name: 'pointer-up is missed', loseCapture: false }
])('does not keep dragging after $name and the list reopens', ({ loseCapture }) => {
  act(() => button('inspectorExpandDiff').click())
  const pane = listPane()
  const handle = container.querySelector<HTMLDivElement>('[aria-label="inspectorResizeFileList"]')!
  handle.setPointerCapture = vi.fn()
  handle.releasePointerCapture = vi.fn()
  vi.spyOn(pane, 'getBoundingClientRect').mockImplementation(() => ({ width: parseFloat(pane.style.width) }) as DOMRect)
  const pointer = (type: string, clientX: number, buttons: number): void => {
    act(() => {
      handle.dispatchEvent(new PointerEvent(type, {
        bubbles: true, pointerId: 1, pointerType: 'mouse', clientX, buttons
      }))
    })
  }

  pointer('pointerdown', 500, 1)
  pointer('pointermove', 800, 1)
  expect(pane.style.width).toBe('0px')
  if (loseCapture) pointer('lostpointercapture', 800, 0)
  act(() => button('inspectorExpandFileList').click())
  expect(pane.style.width).toBe('280px')
  pointer('pointermove', 490, 0)
  expect(pane.style.width).toBe('280px')
})


it('revalidates a retained view on activation without remounting its content', async () => {
  const reload = vi.mocked(useGitWorkingChanges('/repo').reload)
  reload.mockClear()
  const frame = container.querySelector('.ds-change-inspector')
  await act(async () => root.render(createElement(ChangeInspector, { active: false })))
  expect(reload).not.toHaveBeenCalled()
  await act(async () => root.render(createElement(ChangeInspector, { active: true })))
  expect(reload).toHaveBeenCalledTimes(2)
  expect(container.querySelector('.ds-change-inspector')).toBe(frame)
})

it('preserves the selected file when refresh inserts a file earlier in the list', async () => {
  const hook = vi.mocked(useGitWorkingChanges)
  const snapshot = hook('/repo')
  if (!snapshot.result?.ok) throw new Error('Expected change fixture')
  act(() => container.querySelector<HTMLButtonElement>('ul button[title]:not([aria-current="true"])')!.click())
  const selected = useChatStore.getState().inspectorSelectedId
  const selectedText = container.querySelector('[aria-current="true"]')?.textContent
  hook.mockReturnValue({
    ...snapshot,
    result: {
      ...snapshot.result,
      files: [{ ...snapshot.result.files[0]!, path: 'src/0.ts' }, ...snapshot.result.files]
    }
  })
  try {
    await act(async () => root.render(createElement(ChangeInspector)))
    expect(useChatStore.getState().inspectorSelectedId).toBe(selected)
    expect(container.querySelector('[aria-current="true"]')?.textContent).toBe(selectedText)
  } finally {
    hook.mockReturnValue(snapshot)
  }
})
