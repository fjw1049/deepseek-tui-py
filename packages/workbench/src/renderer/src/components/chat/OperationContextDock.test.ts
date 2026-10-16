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
  localStorage.setItem('deepseekgui.operationDock.compact', 'true')
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
  useChatStore.setState({ activeThreadId: 'a', threads: [], blocks: [] })
  container = document.createElement('div'); root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  useChatStore.setState(original, true)
  localStorage.removeItem('deepseekgui.operationDock.compact')
  vi.restoreAllMocks()
  vi.useRealTimers()
})

it('opens for new tasks and agents but respects dismissal during status updates', async () => {
  await refresh()
  expect(compact()).toBe(true)
  activity.tasks = [{ id: 'one', status: 'running', prompt: 'First' }]
  await refresh()
  expect(compact()).toBe(false)
  await close()
  activity.tasks = [{ ...activity.tasks[0], status: 'completed' }]
  await refresh()
  expect(compact()).toBe(true)
  activity.tasks = [...activity.tasks, { id: 'two', status: 'running', prompt: 'Second' }]
  await refresh()
  expect(compact()).toBe(false)
  await close()
  activity.agents = [{ id: 'block', agentId: 'agent-one', agentType: 'worker', status: 'running' }]
  await refresh()
  expect(compact()).toBe(false)
  await close()
  activity.agents = [{ ...activity.agents[0], status: 'completed' }]
  await refresh()
  expect(compact()).toBe(true)
})

it('reveals todos and changes without reopening on progress or diff refresh', async () => {
  await refresh()
  activity.todos = [{ id: '1', content: 'Implement', status: 'pending' }]
  await refresh()
  expect(compact()).toBe(false)
  expect(container.querySelector('ul')?.textContent).toContain('Implement')
  await close()
  activity.todos = [{ ...activity.todos[0], status: 'completed' }]
  await refresh()
  expect(compact()).toBe(true)
  activity.todos = [{ id: '1', content: 'New plan', status: 'pending' }]
  await refresh()
  expect(compact()).toBe(false)
  await close()
  activity.dirty = 1
  await refresh()
  expect(compact()).toBe(false)
  expect(container.querySelector('[title="operationDockOpenChanges"]')).not.toBeNull()
  await close()
  activity.dirty = 2
  await refresh()
  expect(compact()).toBe(true)
  activity.dirty = 0
  await refresh()
  activity.dirty = 1
  await refresh()
  expect(compact()).toBe(true)
})

it('discovers existing content and scopes seen activity to the conversation', async () => {
  activity.tasks = [{ id: 'one', status: 'running', prompt: 'First' }]
  await refresh()
  expect(compact()).toBe(false)
  await close()
  await act(async () => { useChatStore.setState({ activeThreadId: 'b' }) })
  expect(compact()).toBe(false)
  await close()
  await act(async () => { useChatStore.setState({ activeThreadId: 'a' }) })
  expect(compact()).toBe(true)
})

it('finishes expanding at full width even when animation frames are delayed', async () => {
  vi.useFakeTimers()
  vi.mocked(window.matchMedia).mockReturnValue({ matches: false } as MediaQueryList)
  vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(1)
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
  await refresh()
  activity.tasks = [{ id: 'one', status: 'running', prompt: 'First' }]
  await refresh()
  expect(container.querySelector('.ds-operation-dock')?.getAttribute('data-phase')).toBe('expanding')
  await act(async () => { vi.advanceTimersByTime(220) })
  expect(container.querySelector('.ds-operation-dock')?.getAttribute('data-phase')).toBe('expanded')
  expect(container.querySelector('.ds-operation-dock')?.getAttribute('data-compact')).toBe('false')
})
