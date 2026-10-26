// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { TaskItemView } from '../../lib/extract-tasks-from-blocks'
import type { DockSubagentItem } from '../../lib/extract-subagents-from-blocks'
import type { TodoItemView } from '../../lib/extract-todos-from-blocks'

const activity = vi.hoisted(() => ({
  tasks: [] as TaskItemView[], agents: [] as DockSubagentItem[], todos: [] as TodoItemView[], dirty: 0
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../i18n', () => ({ default: { t: (key: string) => key } }))
vi.mock('../ide/IdeWorkspaceLayout', () => ({ preloadIdeWorkspace: () => {} }))
vi.mock('./GitBranchPicker', () => ({ GitBranchPicker: () => null }))
vi.mock('./TaskActivity', () => ({ TaskActivity: () => null }))
vi.mock('../../hooks/use-thread-tasks', () => ({ useLiveTasks: () => activity.tasks }))
vi.mock('../../lib/extract-tasks-from-blocks', () => ({ extractTasksFromBlocks: () => activity.tasks }))
vi.mock('../../lib/extract-subagents-from-blocks', () => ({ extractSubagentsFromBlocks: () => activity.agents }))
vi.mock('../../lib/extract-todos-from-blocks', () => ({ extractTodosFromBlocks: () => ({ items: activity.todos }) }))
vi.mock('../../hooks/use-git-branches', () => ({ useGitBranches: () => ({ result: { ok: true, dirtyCount: activity.dirty }, reload: () => {} }) }))
vi.mock('../../hooks/use-git-working-changes', () => ({
  useGitBranchCompareBase: () => [], useGitWorkingChanges: () => ({ result: null, reload: () => {} })
}))
vi.mock('../../hooks/use-workspace-dirty-git-refresh', () => ({ useWorkspaceDirtyGitRefresh: () => {} }))
import { OperationContextDock } from './OperationContextDock'
import { useChatStore } from '../../store/chat-store'

const original = useChatStore.getState()
let root: Root, container: HTMLDivElement
const props = { workspaceRoot: '/repo', onOpenFilesSidebar: () => {}, previewActive: false,
  previewEnabled: true, onTogglePreview: () => {} }
const compact = () => !!container.querySelector('.ds-operation-dock--compact')
async function refresh() {
  await act(async () => { useChatStore.setState({ blocks: [] }); root.render(createElement(OperationContextDock, props)) })
}
async function close() {
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-operation-dock-topbar__toggle')!.click())
  expect(compact()).toBe(true)
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  activity.tasks = []; activity.agents = []; activity.todos = []; activity.dirty = 0
  localStorage.clear()
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
  useChatStore.setState({ activeThreadId: 'a', threads: [], blocks: [] })
  container = document.createElement('div'); root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  useChatStore.setState(original, true)
  localStorage.clear()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

it('keeps each session independent and restores its choice after remount', async () => {
  await refresh()
  await close()
  await act(async () => { useChatStore.setState({ activeThreadId: 'b' }) })
  expect(compact()).toBe(false)
  await act(async () => { useChatStore.setState({ activeThreadId: 'a' }) })
  expect(compact()).toBe(true)
  await act(async () => root.render(null))
  await refresh()
  expect(compact()).toBe(true)
})

it('does not reopen a dismissed card for saved activity loaded without a running turn', async () => {
  await refresh()
  await close()
  activity.tasks = [{ id: 'one', status: 'running', prompt: 'First' }]
  activity.todos = [{ id: '1', content: 'Implement', status: 'pending' }]
  activity.dirty = 1
  await refresh()
  expect(compact()).toBe(true)
  await act(async () => root.render(null))
  await refresh()
  expect(compact()).toBe(true)
})

it('reopens for new tasks, agents, todos and changes from a running turn, not for progress', async () => {
  await refresh()
  await close()
  await act(async () => { useChatStore.setState({ busy: true }) })
  activity.tasks = [{ id: 'one', status: 'running', prompt: 'First' }]
  await refresh()
  expect(compact()).toBe(false)
  await close()
  activity.tasks = [{ ...activity.tasks[0]!, status: 'completed' }]
  await refresh()
  expect(compact()).toBe(true)
  activity.agents = [{ id: 'block', agentId: 'agent-one', agentType: 'worker', status: 'running' }]
  await refresh()
  expect(compact()).toBe(false)
  await close()
  activity.todos = [{ id: '1', content: 'Implement', status: 'pending' }]
  await refresh()
  expect(compact()).toBe(false)
  expect(container.querySelector('ul')?.textContent).toContain('Implement')
  await close()
  activity.todos = [{ ...activity.todos[0]!, status: 'completed' }]
  await refresh()
  expect(compact()).toBe(true)
  activity.dirty = 1
  await refresh()
  expect(compact()).toBe(false)
  expect(container.querySelector('[title="operationDockOpenChanges"]')).not.toBeNull()
  // The reopened card is the session's choice now, and survives a remount.
  await act(async () => root.render(null))
  await refresh()
  expect(compact()).toBe(false)
})

it('expands at full width without waiting for animation frames or timers', async () => {
  vi.useFakeTimers()
  vi.mocked(window.matchMedia).mockReturnValue({ matches: false } as MediaQueryList)
  vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(1)
  await refresh()
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-operation-dock-topbar__toggle')!.click())
  await act(async () => { vi.advanceTimersByTime(220) })
  await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())
  expect(compact()).toBe(false)
  expect(container.querySelector('.ds-operation-dock')?.getAttribute('data-compact')).toBe('false')
  expect(container.querySelector('.ds-operation-dock')?.getAttribute('data-phase')).toBe('expanded')
})

it('temporarily compacts for the sidebar without changing the session preference', async () => {
  await refresh()
  await act(async () => root.render(createElement(OperationContextDock, { ...props, forceCompact: true })))
  expect(compact()).toBe(true)
  await refresh()
  expect(compact()).toBe(false)
})

it('requests sidebar closure when expanding the compact rail', async () => {
  const onExpandRequested = vi.fn()
  await act(async () => root.render(createElement(OperationContextDock, { ...props, forceCompact: true, onExpandRequested })))
  await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())
  expect(onExpandRequested).toHaveBeenCalledOnce()
  await refresh()
  expect(compact()).toBe(false)
})

it('keeps simultaneously mounted layouts in sync', async () => {
  await act(async () => root.render(createElement('div', null,
    createElement(OperationContextDock, props), createElement(OperationContextDock, props))))
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-operation-dock-topbar__toggle')!.click())
  expect(container.querySelectorAll('.ds-operation-dock--compact')).toHaveLength(2)
})

it('does not carry the draft choice into a new session', async () => {
  await act(async () => { useChatStore.setState({ activeThreadId: null }) })
  await refresh()
  await close()
  await act(async () => { useChatStore.setState({ activeThreadId: 'new' }) })
  expect(compact()).toBe(false)
})

it('keeps the toggle usable when saving is blocked', async () => {
  await act(async () => { useChatStore.setState({ activeThreadId: 'storage-blocked' }) })
  const save = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
  await refresh()
  await close()
  await act(async () => root.render(null))
  await refresh()
  expect(compact()).toBe(true)
  save.mockRestore()
  await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())
  expect(compact()).toBe(false)
})

it('still displays loaded activity when the user opens the card', async () => {
  await refresh()
  await close()
  activity.todos = [{ id: '1', content: 'Implement', status: 'pending' }]
  activity.dirty = 1
  await refresh()
  await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())
  expect(container.querySelector('ul')?.textContent).toContain('Implement')
  expect(container.querySelector('[title="operationDockOpenChanges"]')).not.toBeNull()
})
