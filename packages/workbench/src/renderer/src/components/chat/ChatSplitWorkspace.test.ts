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
import { ChatSplitToolbar } from './ChatSplitToolbar'
import { OperationContextDock } from './OperationContextDock'
import { useChatStore } from '../../store/chat-store'
import { resolveChatLayoutKey, useChatLayoutStore } from '../../store/chat-layout-store'
import { CHAT_SPLIT_DRAG_EVENT, finishChatSplitDrag, openThreadInSplit } from '../../lib/chat-split-navigation'
import { disposeChatPaneSessions, getChatPaneSession, peekChatPaneSession, syncChatPaneCatalog } from '../../store/chat-pane-sessions'

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
  return createElement('div', null,
    createElement(ChatSplitToolbar, { project: '/repo', layout, onArrange: () => {}, onAdd: () => {}, onFocus: () => {} }),
    createElement(ChatSplitWorkspace, { project: '/repo', layout, getInitialDraft: id => `draft-${id}`,
      onFocus: () => {}, onOpenFile: () => {}, onOpenDiff: () => {}, renderContext: () => createElement(ContextProbe) } satisfies ComponentProps<typeof ChatSplitWorkspace>))
}

function ContextProbe() {
  const id = useChatStore(state => state.activeThreadId)
  return createElement('span', { 'data-context-thread': id }, id)
}

it('opens the focused task context without replacing its composer and closes on Escape or task switch', async () => {
  await act(async () => root.render(createElement(Harness)))
  const inputs = [...container.querySelectorAll('textarea')]
  const panes = [...container.querySelectorAll<HTMLElement>('[data-chat-pane]')]
  const selected = useChatLayoutStore.getState().layouts['/repo'].focused
  const pane = panes.find(item => item.dataset.chatPane === selected)!
  const trigger = pane.querySelector<HTMLButtonElement>('[aria-label="splitTaskContext"]')!
  await act(async () => trigger.click())
  expect(pane.querySelector('[data-context-thread]')?.getAttribute('data-context-thread')).toBe(pane.dataset.chatThread)
  expect(document.activeElement).toBe(pane.querySelector('[role="region"]'))
  await act(async () => document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  expect(container.querySelector('[role="region"]')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  await act(async () => trigger.click())
  await act(async () => useChatLayoutStore.getState().focus('/repo', panes[0].dataset.chatPane!))
  expect(container.querySelector('[role="region"]')).toBeNull()
  expect([...container.querySelectorAll('textarea')]).toEqual(inputs)
})

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

it('disposes the last pane session when its thread disappears from a ready catalog', async () => {
  const pane = getChatPaneSession('a')
  await pane.loading
  syncChatPaneCatalog({ ...useChatStore.getState(), runtimeConnection: 'offline', threads: [] })
  expect(peekChatPaneSession('a')).toBe(pane)
  syncChatPaneCatalog({ ...useChatStore.getState(), runtimeConnection: 'ready', threads: [] })
  expect(peekChatPaneSession('a')).toBeUndefined()
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


it.each(['grid', 'horizontal', 'vertical', 'tabs'] as const)('keeps the surviving session as the command owner after returning from %s to a single conversation', async arrangement => {
  useChatLayoutStore.getState().arrange('/repo', arrangement)
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
  expect(container.querySelector('[role="tablist"]')).toBeNull()
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
  await act(async () => container.querySelector<HTMLButtonElement>('header .ds-chat-split-task-trigger')!.click())
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
  const trigger = container.querySelector<HTMLButtonElement>('header .ds-chat-split-task-trigger')!
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
      if (target.classList.contains('ds-chat-split-shell')) resize = size => this.callback([{ contentRect: size } as ResizeObserverEntry], this as unknown as ResizeObserver)
    }
    disconnect() {}
  })
  try {
    await act(async () => root.render(createElement(Harness)))
    const inputs = [...container.querySelectorAll('textarea')]
    await act(async () => useChatLayoutStore.getState().arrange('/repo', 'horizontal'))
    await act(async () => resize({ width: 1280, height: 900 }))
    expect(container.querySelector('.ds-chat-split-shell')?.getAttribute('data-presentation')).toBe('grid')
    expect(container.querySelectorAll('.ds-chat-split-tab')).toHaveLength(0)
    expect([...container.querySelectorAll<HTMLElement>('[data-chat-pane]')].filter(p => p.style.display !== 'none')).toHaveLength(4)
    await act(async () => resize({ width: 600, height: 500 }))
    expect(container.querySelectorAll('.ds-chat-split-tab')).toHaveLength(4)
    expect([...container.querySelectorAll<HTMLElement>('[data-chat-pane]')].filter(p => p.style.display !== 'none')).toHaveLength(1)
    await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-tab')!.click())
    expect(container.querySelector('.ds-chat-split-tab')!.getAttribute('aria-selected')).toBe('true')
    await act(async () => resize({ width: 1600, height: 900 }))
    expect(container.querySelector('.ds-chat-split-shell')?.getAttribute('data-presentation')).toBe('horizontal')
    expect(container.querySelectorAll('.ds-chat-split-tab')).toHaveLength(0)
    expect([...container.querySelectorAll('textarea')]).toEqual(inputs)
  } finally { vi.stubGlobal('ResizeObserver', OriginalResizeObserver) }
})


it('switches explicit tabs by arrow keys without reordering panes or intercepting editing', async () => {
  useChatLayoutStore.getState().arrange('/repo', 'tabs')
  await act(async () => root.render(createElement(Harness)))
  const tabs = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  const panes = useChatLayoutStore.getState().layouts['/repo'].panes
  const inputs = [...container.querySelectorAll('textarea')]
  const scroll = vi.spyOn(tabs[0], 'scrollIntoView')
  const key = async (index: number, value: string) => act(async () => {
    tabs[index].dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true }))
  })
  await key(3, 'ArrowRight')
  expect(document.activeElement).toBe(tabs[0])
  expect(tabs[0].getAttribute('aria-selected')).toBe('true')
  expect(tabs.map(tab => tab.tabIndex)).toEqual([0, -1, -1, -1])
  expect(scroll).toHaveBeenCalledWith({ block: 'nearest', inline: 'nearest' })
  await key(0, 'ArrowLeft')
  expect(document.activeElement).toBe(tabs[3])
  await key(3, 'Home')
  expect(document.activeElement).toBe(tabs[0])
  await key(0, 'End')
  expect(document.activeElement).toBe(tabs[3])
  const selected = useChatLayoutStore.getState().layouts['/repo'].focused
  const editKey = new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true })
  await act(async () => { inputs[3].focus(); inputs[3].dispatchEvent(editKey) })
  expect(editKey.defaultPrevented).toBe(false)
  expect(useChatLayoutStore.getState().layouts['/repo'].focused).toBe(selected)
  expect(useChatLayoutStore.getState().layouts['/repo'].panes).toEqual(panes)
  expect([...container.querySelectorAll('textarea')]).toEqual(inputs)
  expect(inputs.map(input => input.value)).toEqual(['draft-a', 'draft-b', 'draft-c', 'draft-d'])
})

it('hides the lone tab while keeping parked tasks available and restores tabs with a second task', async () => {
  const actions = useChatLayoutStore.getState()
  actions.arrange('/repo', 'tabs')
  await act(async () => root.render(createElement(Harness)))
  const input = container.querySelector('textarea')
  for (const pane of actions.layouts['/repo'].panes.filter(p => p.threadId !== 'a')) {
    await act(async () => actions.park('/repo', pane.id))
  }
  expect(container.querySelector('[role="tablist"]')).toBeNull()
  expect(container.querySelectorAll('.ds-chat-split-restore')).toHaveLength(3)
  expect(container.querySelector('textarea')).toBe(input)
  expect(useChatLayoutStore.getState().layouts['/repo'].arrangement).toBe('tabs')
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-restore')!.click())
  expect(container.querySelectorAll('[role="tab"]')).toHaveLength(2)
  expect(container.querySelector('textarea')).toBe(input)
  expect(input?.value).toBe('draft-a')
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
  expect(container.querySelector('.ds-chat-split-shelf')).toBeNull()
  expect(container.querySelector('.ds-chat-split-parked-label')?.textContent).toBe('splitParked')
  expect(container.querySelector('.ds-chat-split-toolbar .ds-chat-split-parked-title')?.textContent).toBe('Task a')
  expect(container.querySelector('.ds-chat-split-parked-status')?.textContent).toBe('splitParkedStatus_running')
  expect(interrupt).not.toHaveBeenCalled()
  await act(async () => session.store.setState({ busy: false, threads: threads.map(t => t.id === 'a' ? { ...t, status: 'completed' } : t) }))
  expect(container.querySelector('.ds-chat-split-parked-status')?.textContent).toBe('splitParkedStatus_completed')
  await act(async () => session.store.setState({ busy: true }))
  await act(async () => session.store.setState({ blocks: [{ kind: 'user_input', id: 'input', requestId: 'req', questions: [], status: 'pending' }] }))
  expect(container.querySelector('.ds-chat-split-parked-status')?.textContent).toBe('splitParkedStatus_waiting')
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-chat-split-restore')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(4)
  expect(container.querySelector('.ds-chat-split-parked-label')).toBeNull()
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
  expect(document.querySelector('.ds-chat-split-restore-targets')).not.toBeNull()
  await act(async () => document.querySelector<HTMLButtonElement>('.ds-chat-split-restore-targets button')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(6)
  expect(container.querySelector('.ds-chat-split-parked-title')?.textContent).toBe('Task b')
  expect(container.querySelector('[data-chat-thread="a"]')).not.toBeNull()
})

it('places tab-mode actions beside the tab list and applies them to the selected task', async () => {
  useChatLayoutStore.getState().arrange('/repo', 'tabs')
  await act(async () => root.render(createElement(Harness)))
  const tabbar = container.querySelector('.ds-chat-split-tabbar')!
  expect(tabbar.querySelectorAll('.ds-chat-split-pane-actions button')).toHaveLength(3)
  expect(container.querySelector('header .ds-chat-split-pane-actions')).toBeNull()
  const tabs = [...tabbar.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  await act(async () => tabs[1].click())
  await act(async () => tabbar.querySelector<HTMLButtonElement>('[aria-label="splitTaskContext"]')!.click())
  expect(container.querySelector('[data-context-thread]')?.getAttribute('data-context-thread')).toBe('b')
  await act(async () => tabbar.querySelector<HTMLButtonElement>('[aria-label="splitPark"]')!.click())
  expect(useChatLayoutStore.getState().layouts['/repo'].parked?.map(pane => pane.threadId)).toEqual(['b'])
  expect(container.querySelectorAll('.ds-chat-split-tabbar [aria-label="splitClose"]')).toHaveLength(1)
})

it('uses the same workspace card in the main rail and split panel, with collapse returning to the panel trigger', async () => {
  const props = { workspaceRoot: '/repo', onOpenFilesSidebar: () => {}, onEnterIdeMode: () => {},
    previewActive: false, previewEnabled: true, onTogglePreview: () => {} }
  await act(async () => root.render(createElement(OperationContextDock, props)))
  const mainCard = container.innerHTML
  const onCollapse = vi.fn()
  await act(async () => root.render(createElement(OperationContextDock, { ...props, onCollapse })))
  expect(container.innerHTML).toBe(mainCard)
  expect(container.querySelector('.ds-operation-dock-topbar__title')?.textContent).toBe('repo')
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-operation-dock-topbar__toggle')!.click())
  expect(onCollapse).toHaveBeenCalledOnce()
  expect(container.querySelector('.ds-operation-dock--compact')).toBeNull()
})

it('merges session tools into the active tab without a second title row and keeps query navigation scoped', async () => {
  useChatLayoutStore.getState().arrange('/repo', 'tabs')
  await act(async () => root.render(createElement(Harness)))
  const inputs = [...container.querySelectorAll('textarea')]
  expect(container.querySelector('.ds-chat-split-title')).toBeNull()
  const session = getChatPaneSession('b')
  const scrollToBlock = vi.fn()
  await act(async () => session.store.setState({ blocks: [{ kind: 'user', id: 'merged-question', text: 'Question for B' }], scrollToBlock }))
  await act(async () => container.querySelectorAll<HTMLButtonElement>('[role="tab"]')[1].click())
  const active = container.querySelector('.ds-chat-split-tab-group[data-active]')!
  expect(active.querySelector('.ds-chat-split-grip')).not.toBeNull()
  expect(active.querySelector('[aria-label="sessionInfoHint"]')).not.toBeNull()
  expect(container.querySelectorAll('[aria-label="sessionQueriesHint"]')).toHaveLength(1)
  await act(async () => active.querySelector<HTMLButtonElement>('[aria-label="sessionQueriesHint"]')!.click())
  await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="sessionQueryCopyHint: Question for B"]')!.click())
  expect(scrollToBlock).toHaveBeenCalledWith('merged-question')
  await act(async () => useChatLayoutStore.getState().arrange('/repo', 'grid'))
  expect(container.querySelectorAll('.ds-chat-split-title')).toHaveLength(4)
  expect([...container.querySelectorAll('textarea')]).toEqual(inputs)
})

it('keeps exactly one bookmark before the active title across repeated tab switches', async () => {
  useChatLayoutStore.getState().arrange('/repo', 'tabs')
  await act(async () => root.render(createElement(Harness)))
  const tabs = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  for (const index of [0, 1, 2, 3, 0, 3, 1, 2]) {
    await act(async () => tabs[index].click())
    const active = container.querySelector('.ds-chat-split-tab-group[data-active]')!
    expect(container.querySelectorAll('.ds-chat-split-tabbar .lucide-bookmark')).toHaveLength(1)
    expect(active.querySelectorAll('[aria-label="sessionInfoHint"]')).toHaveLength(1)
    expect(container.querySelectorAll('.ds-chat-split-tab-group:not([data-active]) .lucide-bookmark')).toHaveLength(0)
    expect(active.querySelector('[aria-label="sessionInfoHint"]')!.compareDocumentPosition(tabs[index]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  }
})
