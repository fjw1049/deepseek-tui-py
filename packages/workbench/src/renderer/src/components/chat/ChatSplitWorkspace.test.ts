// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'

const provider = vi.hoisted(() => ({
  getThreadDetail: vi.fn(async () => ({ blocks: [], latestSeq: 0, threadStatus: 'completed' })),
  subscribeThreadEvents: vi.fn(async () => {}), fetchPendingApprovals: vi.fn(async () => []),
  fetchPendingUserInputs: vi.fn(async () => []), fetchPendingElevations: vi.fn(async () => [])
}))
vi.mock('../../i18n', () => ({ default: { t: (key: string) => key } }))
vi.mock('../../agent/registry', () => ({ getProvider: () => provider }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./MessageTimeline', () => ({ MessageTimeline: () => null }))
vi.mock('./ComposerStage', () => ({ ComposerStage: (props: { input: string; setInput: (text: string) => void }) =>
  createElement('textarea', { value: props.input, onChange: (event: { target: { value: string } }) => props.setInput(event.target.value) })
}))
import { ChatSplitDropZone, ChatSplitWorkspace } from './ChatSplitWorkspace'
import { useChatStore } from '../../store/chat-store'
import { resolveChatLayoutKey, useChatLayoutStore } from '../../store/chat-layout-store'
import { CHAT_SPLIT_DRAG_EVENT, finishChatSplitDrag, openThreadInSplit } from '../../lib/chat-split-navigation'
import { disposeChatPaneSessions, getChatPaneSession } from '../../store/chat-pane-sessions'

const original = useChatStore.getState()
let root: Root, container: HTMLDivElement
const threads = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map(id => ({ id, title: `Task ${id}`, workspace: id === 'a' ? '/repo' : `/repo-${id}`, model: 'test', mode: 'agent', updatedAt: '' }))
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div'); document.body.append(container); root = createRoot(container)
  useChatStore.setState({ ...original, threads, activeThreadId: 'a', workspaceRoot: '/repo', runtimeConnection: 'ready' }, true)
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
  const actions = useChatLayoutStore.getState()
  actions.add('/repo', 'a', 'b'); actions.add('/repo', 'a', 'c'); actions.add('/repo', 'a', 'd')
})
afterEach(() => { act(() => root.unmount()); container.remove(); disposeChatPaneSessions(); useChatStore.setState(original, true); vi.restoreAllMocks() })

function Harness() {
  const layout = useChatLayoutStore(state => state.layouts['/repo'])
  return createElement(ChatSplitWorkspace, { project: '/repo', layout, getInitialDraft: id => `draft-${id}`,
    onFocus: () => {}, onOpenFile: () => {}, onOpenDiff: () => {} } satisfies ComponentProps<typeof ChatSplitWorkspace>)
}

it('renders exactly four independent composers, and preserves the surviving DOM when closing', async () => {
  await act(async () => root.render(createElement(Harness)))
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(4)
  const inputs = [...container.querySelectorAll('textarea')]
  expect(inputs.map(input => input.value)).toEqual(['draft-a', 'draft-b', 'draft-c', 'draft-d'])
  const addButtons = [...container.querySelectorAll<HTMLButtonElement>('button[aria-label="splitAdd"]')]
  expect(addButtons).toHaveLength(0)
  const firstStore = getChatPaneSession('a').store
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="splitClose"]')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(3)
  expect(container.querySelector('textarea')).toBe(inputs[1])
  expect(getChatPaneSession('a').store).toBe(firstStore) // closing a view does not stop its runtime
  expect(getChatPaneSession('a').draft).toBe('draft-a')
})

it('adjusts split ratios by keyboard and keeps task navigation outside the scoped runtime', async () => {
  const selectThread = vi.fn(async () => {})
  const forkThread = vi.fn(async () => {})
  useChatStore.setState({ selectThread, forkThread })
  await act(async () => root.render(createElement(Harness)))
  const separator = container.querySelector('[role="separator"][aria-orientation="vertical"]')!
  await act(async () => separator.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
  expect(useChatLayoutStore.getState().layouts['/repo'].x).toBe(.55)
  const pane = getChatPaneSession('a')
  await pane.store.getState().selectThread('e')
  await pane.store.getState().forkThread('a', 'message-a')
  expect(selectThread).toHaveBeenCalledWith('e')
  expect(forkThread).toHaveBeenCalledWith('a', 'message-a')
  expect(pane.store.getState().activeThreadId).toBe('a')
})


it('keeps the surviving session as the command owner after returning to a single conversation', async () => {
  await act(async () => root.render(createElement(Harness)))
  const session = getChatPaneSession('a')
  const interrupt = vi.fn(async () => { session.store.setState({ busy: false }) })
  const sendMessage = vi.fn(async () => true)
  const queue = [{ id: 'queued-a', text: 'Continue A' }]
  await act(async () => session.store.setState({ busy: true, currentTurnId: 'turn-a', queuedMessages: queue,
    composerModel: 'model-a', interrupt, sendMessage }))
  expect(useChatStore.getState()).toMatchObject({ activeThreadId: 'a', busy: true, queuedMessages: queue, composerModel: 'model-a' })
  const actions = useChatLayoutStore.getState()
  for (const pane of actions.layouts['/repo'].panes.filter(p => p.threadId !== 'a')) {
    await act(async () => actions.close('/repo', pane.id))
  }
  expect(useChatLayoutStore.getState().layouts['/repo'].panes).toHaveLength(1)
  expect(getChatPaneSession('a')).toBe(session)
  expect(session.draft).toBe('draft-a')
  await act(async () => { await useChatStore.getState().interrupt(); await useChatStore.getState().sendMessage('single view') })
  expect(interrupt).toHaveBeenCalledOnce()
  expect(sendMessage).toHaveBeenCalledWith('single view')
  expect(useChatStore.getState().busy).toBe(false)
})


it('keeps cross-project navigation in the same layout and each session in its own workspace', async () => {
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
  useChatStore.setState({ selectThread: async id => { useChatStore.setState({ activeThreadId: id }) } })
  expect(openThreadInSplit('b')).toBe(true)
  expect(resolveChatLayoutKey(useChatLayoutStore.getState(), '/repo-b')).toBe('/repo')
  expect(openThreadInSplit('c')).toBe(true)
  expect(openThreadInSplit('d')).toBe(true)
  expect(openThreadInSplit('e')).toBe(true)
  expect(openThreadInSplit('f')).toBe(true)
  expect(openThreadInSplit('g')).toBe(false)
  await act(async () => root.render(createElement(Harness)))
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(6)
  for (const thread of threads.slice(0, 6)) {
    expect(getChatPaneSession(thread.id).store.getState().workspaceRoot).toBe(thread.workspace)
    expect(container.querySelector('.ds-chat-split-project')).toBeNull()
  }
  const before = useChatLayoutStore.getState().layouts['/repo'].panes
  await act(async () => { expect(openThreadInSplit('a')).toBe(true) })
  expect(useChatLayoutStore.getState().layouts['/repo'].panes).toEqual(before)
  expect(useChatStore.getState().activeThreadId).toBe('a')
  await act(async () => { expect(openThreadInSplit('g', 'right', before[1].id)).toBe(true) })
  expect(useChatLayoutStore.getState().layouts['/repo'].panes.map(p => p.threadId)).toEqual(['a', 'g', 'c', 'd', 'e', 'f'])
  expect(getChatPaneSession('g').store.getState().workspaceRoot).toBe('/repo-g')
})

it('offers tasks from other projects in an empty pane', async () => {
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
  useChatLayoutStore.getState().add('/repo', 'a')
  await act(async () => root.render(createElement(Harness)))
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-task-trigger')!.click())
  const options = [...document.querySelectorAll('[role="option"]')]
  expect(options.some(option => option.textContent?.includes('Task b') && option.textContent?.includes('repo-b'))).toBe(true)
})


it('keeps each pane’s information and question navigation scoped to its session', async () => {
  await act(async () => root.render(createElement(Harness)))
  const session = getChatPaneSession('b')
  const scrollToBlock = vi.fn()
  await act(async () => session.store.setState({ blocks: [{ kind: 'user', id: 'question-b', text: 'Only in B' }], scrollToBlock }))
  const panes = container.querySelectorAll('[data-chat-pane]')
  expect(panes[0].querySelector<HTMLButtonElement>('[aria-label="sessionQueriesHint"]')!.disabled).toBe(true)
  await act(async () => panes[1].querySelector<HTMLButtonElement>('[aria-label="sessionQueriesHint"]')!.click())
  const jump = document.body.querySelector<HTMLButtonElement>('[aria-label="sessionQueryCopyHint: Only in B"]')!
  expect(jump).not.toBeNull()
  await act(async () => jump.click())
  expect(scrollToBlock).toHaveBeenCalledWith('question-b')
  await act(async () => panes[1].querySelector<HTMLButtonElement>('[aria-label="sessionInfoHint"]')!.click())
  expect(document.body.textContent).toContain('/repo-b')
})

it('changes arrangement without remounting composers and places the empty picker at the top', async () => {
  await act(async () => root.render(createElement(Harness)))
  const inputs = [...container.querySelectorAll('textarea')]
  for (const arrangement of ['horizontal', 'vertical', 'grid'] as const) {
    await act(async () => useChatLayoutStore.getState().arrange('/repo', arrangement))
    expect([...container.querySelectorAll('textarea')]).toEqual(inputs)
    expect(container.querySelectorAll('[role="separator"]')).toHaveLength(arrangement === 'grid' ? 2 : 0)
  }
  await act(async () => {
    useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
    useChatLayoutStore.getState().add('/repo', 'a')
  })
  expect(container.querySelector('header .ds-chat-split-task-trigger')).not.toBeNull()
  expect(container.querySelector('select')).toBeNull()
})


it('searches tasks by project and selects with the keyboard without creating duplicate panes', async () => {
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
  const actions = useChatLayoutStore.getState()
  actions.add('/repo', 'a')
  await act(async () => root.render(createElement(Harness)))
  const trigger = container.querySelector<HTMLButtonElement>('.ds-chat-split-task-trigger')!
  await act(async () => trigger.click())
  const input = document.querySelector<HTMLInputElement>('[role="combobox"]')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'repo-b')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(document.querySelectorAll('[role="option"]')).toHaveLength(1)
  await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
  expect(useChatLayoutStore.getState().layouts['/repo'].panes.map(p => p.threadId)).toEqual(['a', 'b'])
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})


it('uses pane tabs when the chosen arrangement cannot fit and preserves its composers', async () => {
  let resize!: (size: { width: number; height: number }) => void
  const OriginalResizeObserver = globalThis.ResizeObserver
  vi.stubGlobal('ResizeObserver', class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) {
      if (target.classList.contains('ds-chat-split-grid')) resize = size => this.callback([{ contentRect: size } as ResizeObserverEntry], this as unknown as ResizeObserver)
    }
    disconnect() {}
  })
  try {
    await act(async () => root.render(createElement(Harness)))
    const inputs = [...container.querySelectorAll('textarea')]
    await act(async () => resize({ width: 600, height: 500 }))
    expect(container.querySelectorAll('.ds-chat-split-tab')).toHaveLength(4)
    expect([...container.querySelectorAll<HTMLElement>('[data-chat-pane]')].filter(p => p.style.display !== 'none')).toHaveLength(1)
    await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-tab')!.click())
    expect(container.querySelector('.ds-chat-split-tab')!.getAttribute('aria-pressed')).toBe('true')
    await act(async () => resize({ width: 1600, height: 900 }))
    expect(container.querySelectorAll('.ds-chat-split-tab')).toHaveLength(0)
    expect([...container.querySelectorAll('textarea')]).toEqual(inputs)
  } finally { vi.stubGlobal('ResizeObserver', OriginalResizeObserver) }
})


it.each([5, 6])('lays out %i panes without overlap and preserves composers across arrangements', async count => {
  const actions = useChatLayoutStore.getState()
  actions.add('/repo', 'a', 'e')
  if (count === 6) actions.add('/repo', 'a', 'f')
  await act(async () => root.render(createElement(Harness)))
  const inputs = [...container.querySelectorAll('textarea')]
  expect(inputs).toHaveLength(count)
  for (const arrangement of ['grid', 'horizontal', 'vertical'] as const) {
    await act(async () => actions.arrange('/repo', arrangement))
    const panes = [...container.querySelectorAll<HTMLElement>('[data-chat-pane]')]
    const coordinate = (value: string): number => value.includes('--split-y') ? 50 : parseFloat(value) || 0
    const boxes = panes.map(pane => ({ left: coordinate(pane.style.left), right: 100 - coordinate(pane.style.right),
      top: coordinate(pane.style.top), bottom: 100 - coordinate(pane.style.bottom) }))
    let area = 0
    for (const [index, box] of boxes.entries()) {
      expect(box.right).toBeGreaterThan(box.left)
      expect(box.bottom).toBeGreaterThan(box.top)
      area += (box.right - box.left) * (box.bottom - box.top)
      for (const other of boxes.slice(index + 1)) {
        const overlapWidth = Math.min(box.right, other.right) - Math.max(box.left, other.left)
        const overlapHeight = Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top)
        expect(overlapWidth < .001 || overlapHeight < .001).toBe(true)
      }
    }
    expect(area).toBeCloseTo(10000)
    expect([...container.querySelectorAll('textarea')]).toEqual(inputs)
    expect(container.querySelectorAll('[role="separator"]')).toHaveLength(arrangement === 'grid' ? 1 : 0)
  }
})


it.each([2, 3, 4, 5, 6])('swaps %i-pane layouts without remounting composers or losing running state', async count => {
  const actions = useChatLayoutStore.getState()
  while (useChatLayoutStore.getState().layouts['/repo'].panes.length > count) {
    actions.close('/repo', useChatLayoutStore.getState().layouts['/repo'].panes.at(-1)!.id)
  }
  if (count >= 5) actions.add('/repo', 'a', 'e')
  if (count === 6) actions.add('/repo', 'a', 'f')
  await act(async () => root.render(createElement(Harness)))
  const before = useChatLayoutStore.getState().layouts['/repo'].panes
  const inputs = [...container.querySelectorAll('textarea')]
  const session = getChatPaneSession('a')
  await act(async () => session.store.setState({ busy: true, liveAssistant: 'Still streaming' }))
  await act(async () => openThreadInSplit('a', 'right', before.at(-1)!.id))
  const after = [...container.querySelectorAll('textarea')]
  expect(after.at(-1)).toBe(inputs[0])
  expect(after[0]).toBe(inputs.at(-1))
  expect(getChatPaneSession('a')).toBe(session)
  expect(session.store.getState()).toMatchObject({ busy: true, liveAssistant: 'Still streaming' })
  expect(session.draft).toBe('draft-a')
})

it('provides keyboard swapping from the drag handle', async () => {
  await act(async () => root.render(createElement(Harness)))
  await act(async () => container.querySelector('.ds-chat-split-grip')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
  expect(useChatLayoutStore.getState().layouts['/repo'].panes.map(p => p.threadId)).toEqual(['b', 'a', 'c', 'd'])
})

it('previews swap and replacement targets, clears cancellation, and drops into the indicated pane', async () => {
  await act(async () => root.render(createElement(ChatSplitDropZone, { canAdd: true, children: createElement(Harness) })))
  const zone = container.querySelector<HTMLElement>('.ds-chat-split-dropzone')!
  vi.spyOn(zone, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 1200, 800))
  const target = container.querySelectorAll<HTMLElement>('[data-chat-pane]')[1]
  vi.spyOn(document, 'elementFromPoint').mockReturnValue(target)
  const before = useChatLayoutStore.getState().layouts['/repo'].panes
  const move = (threadId: string) => window.dispatchEvent(new CustomEvent(CHAT_SPLIT_DRAG_EVENT, { detail: { threadId, x: 700, y: 200 } }))
  await act(async () => { move('a') })
  expect(target.dataset.dropHint).toBe('splitDropSwap')
  expect(document.querySelector('.ds-chat-split-drag-preview')?.textContent).toContain('Task a')
  expect(container.querySelectorAll('.ds-chat-split-drop')).toHaveLength(0)
  await act(async () => window.dispatchEvent(new CustomEvent(CHAT_SPLIT_DRAG_EVENT, { detail: null })))
  expect(target.dataset.dropHint).toBeUndefined()
  expect(useChatLayoutStore.getState().layouts['/repo'].panes).toEqual(before)
  await act(async () => { move('g') })
  expect(target.dataset.dropHint).toBe('splitDropReplace')
  await act(async () => { expect(finishChatSplitDrag('g', 700, 200)).toBe(true) })
  expect(useChatLayoutStore.getState().layouts['/repo'].panes.map(p => p.threadId)).toEqual(['a', 'g', 'c', 'd'])
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
  expect(target.dataset.dropHint).toBeUndefined()
  expect(document.querySelector('.ds-chat-split-drag-preview')).toBeNull()
  vi.mocked(document.elementFromPoint).mockReturnValue(null)
  expect(finishChatSplitDrag('a', -100, -100)).toBe(false)
})


it('stows a running pane, updates its shelf status and restores its draft and session', async () => {
  await act(async () => root.render(createElement(Harness)))
  const session = getChatPaneSession('a')
  const interrupt = vi.fn(async () => {})
  session.scroll.top = 240; session.scroll.atBottom = false
  await act(async () => session.store.setState({ busy: true, interrupt }))
  await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="splitPark"]')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(3)
  expect(container.querySelector('.ds-chat-split-parked-title')?.textContent).toBe('Task a')
  expect(container.querySelector('.ds-chat-split-parked-status')?.textContent).toBe('splitParkedStatus_running')
  expect(interrupt).not.toHaveBeenCalled()
  await act(async () => session.store.setState({ busy: false, threads: threads.map(t => t.id === 'a' ? { ...t, status: 'completed' } : t) }))
  expect(container.querySelector('.ds-chat-split-parked-status')?.textContent).toBe('splitParkedStatus_completed')
  await act(async () => session.store.setState({ busy: true }))
  await act(async () => session.store.setState({ blocks: [{ kind: 'user_input', id: 'input', requestId: 'req', questions: [], status: 'pending' }] }))
  expect(container.querySelector('.ds-chat-split-parked-status')?.textContent).toBe('splitParkedStatus_waiting')
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-restore')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(4)
  expect(container.querySelector('.ds-chat-split-shelf')).toBeNull()
  expect(container.querySelector('textarea')?.value).toBe('draft-a')
  expect(getChatPaneSession('a')).toBe(session)
  expect(session.scroll).toEqual({ top: 240, atBottom: false })
  expect(session.store.getState().busy).toBe(true)
})

it('keeps the shelf available when all panes are stowed and restores into the empty pane', async () => {
  await act(async () => root.render(createElement(Harness)))
  for (let i = 0; i < 4; i++) {
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="splitPark"]')!.click())
  }
  expect(container.querySelectorAll('.ds-chat-split-restore')).toHaveLength(4)
  expect(container.querySelectorAll('textarea')).toHaveLength(0)
  expect(container.querySelector('.ds-chat-split-empty')).not.toBeNull()
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-restore')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(1)
  expect(container.querySelector('textarea')?.value).toBe('draft-a')
})

it('offers a swap at capacity instead of overwriting a visible conversation', async () => {
  const actions = useChatLayoutStore.getState()
  await act(async () => root.render(createElement(Harness)))
  await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="splitPark"]')!.click())
  await act(async () => { for (const id of ['e', 'f', 'g']) actions.add('/repo', 'b', id) })
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-restore')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(6)
  expect(container.querySelector('.ds-chat-split-restore-targets')).not.toBeNull()
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-restore-targets button')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(6)
  expect(container.querySelector('.ds-chat-split-parked-title')?.textContent).toBe('Task b')
  expect(container.querySelector('[data-chat-thread="a"]')).not.toBeNull()
})
