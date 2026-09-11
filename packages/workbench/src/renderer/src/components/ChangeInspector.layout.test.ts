// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useChatStore } from '../store/chat-store'
import { ChangeInspector } from './ChangeInspector'

vi.mock('./chat/FileChip', () => ({ FileChip: () => null, FileTypeIcon: () => null }))
vi.mock('react-i18next', async (importOriginal) => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../hooks/use-git-working-changes', () => {
  const reload = vi.fn()
  const result = { ok: true, files: [
    { path: 'src/a.ts', stage: 'unstaged', status: 'modified', patch: '@@ -1 +1 @@\n-old\n+new', additions: 1, deletions: 1 },
    { path: 'src/b.ts', stage: 'unstaged', status: 'modified', patch: '@@ -1 +1 @@\n-old\n+next', additions: 1, deletions: 1 }
  ] }
  return {
    useGitWorkingChanges: () => ({ result, loading: false, reload }),
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

it('resizes the fullscreen directory, leaves a rail when collapsed, and restores the last width', () => {
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
  drag('pointermove', 800)
  drag('pointerup', 800)
  expect(pane.style.width).toBe('32px')
  expect(container.querySelector('ul')!.closest('.hidden')).not.toBeNull()
  act(() => button('inspectorExpandFileList').click())
  expect(pane.style.width).toBe('320px')
  expect(container.querySelector('ul')!.closest('.hidden')).toBeNull()
  drag('pointerdown', 500)
  drag('pointermove', 800)
  drag('pointerup', 800)
  drag('pointerdown', 500)
  drag('pointermove', 300)
  drag('pointerup', 300)
  expect(pane.style.width).toBe('232px')
  drag('pointerdown', 500)
  drag('pointermove', 800)
  drag('pointercancel', 800)
  expect(pane.style.width).toBe('232px')
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
  expect(handle.getAttribute('aria-valuenow')).toBe('32')
  key('ArrowLeft')
  expect(handle.getAttribute('aria-valuenow')).toBe('312')
  for (let i = 0; i < 6; i++) key('ArrowRight')
  expect(handle.getAttribute('aria-valuenow')).toBe('32')
})
