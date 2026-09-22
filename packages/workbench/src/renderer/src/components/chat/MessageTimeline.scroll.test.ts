// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MessageTimeline } from './MessageTimeline'
import { useChatStore } from '../../store/chat-store'
import type { ChatBlock } from '../../agent/types'

vi.mock('./StreamdownAssistant', () => ({
  StreamdownAssistant: ({ text }: { text: string }) => createElement('p', null, text)
}))

const initial = useChatStore.getState()
const observers = new Set<() => void>()
let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
let turnHeight = 200
let now = 1000
const blocks: ChatBlock[] = [
  { kind: 'user', id: 'user', text: '分析消息展示流程' },
  { kind: 'assistant', id: 'progress', text: '正在等待子代理。', agentSegment: 'mid_turn_preface' }
]

function viewport(): HTMLElement {
  return container.querySelector('.ds-scroll-surface') as HTMLElement
}

function spacerHeight(): number {
  return parseFloat((container.querySelector('.ds-tail-anchor-spacer') as HTMLElement | null)?.style.height ?? '0')
}

async function resize(): Promise<void> {
  await act(async () => {
    for (const notify of [...observers]) notify()
  })
}

async function render(): Promise<void> {
  await act(async () => root.render(createElement(MessageTimeline, {
    blocks: [...blocks], liveReasoning: '', live: '', activeThreadId: 'scroll-review',
    runtimeConnection: 'ready', onRetryConnection: () => {},
    onOpenSettings: () => {}, onOpenDiagnostics: () => {}
  })))
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  turnHeight = 200
  now = 1000
  vi.spyOn(performance, 'now').mockImplementation(() => now)
  vi.stubGlobal('ResizeObserver', class {
    private notify: () => void
    constructor(callback: () => void) { this.notify = callback; observers.add(callback) }
    observe(): void {}
    unobserve(): void {}
    disconnect(): void { observers.delete(this.notify) }
  })
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(800)
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return this.classList.contains('ds-scroll-surface') ? 100 + turnHeight + spacerHeight() + 120 : 800
  })
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const scrollTop = container?.querySelector('.ds-scroll-surface')?.scrollTop ?? 0
    const isUser = this.id === 'block-user'
    const isTurn = this.classList.contains('ds-message-turn')
    return new DOMRect(0, isUser || isTurn ? 100 - scrollTop : 0, 600, isUser ? 40 : isTurn ? turnHeight : 800)
  })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  useChatStore.setState({ busy: true, currentTurnUserId: 'user', blocks, activeThreadId: 'scroll-review', workspaceRoot: '' })
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  observers.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  useChatStore.setState(initial, true)
})

it.each([false, true])('does not recreate blank space when a long turn collapses (completed: %s)', async (completed) => {
  await render()
  expect(spacerHeight()).toBeGreaterThan(500)
  turnHeight = 1100
  await resize()
  expect(spacerHeight()).toBe(0)
  turnHeight = 200
  if (completed) await act(async () => useChatStore.setState({ busy: false, currentTurnUserId: null }))
  await resize()
  expect(spacerHeight()).toBe(0)
})

it.each(['wheel', 'touchmove', 'keydown'])('respects %s scrolling when an update arrives after the cooldown', async (eventType) => {
  await render()
  await resize()
  viewport().dispatchEvent(eventType === 'keydown' ? new KeyboardEvent('keydown', { key: 'PageUp' }) : new Event(eventType))
  viewport().scrollTop = 20
  viewport().dispatchEvent(new Event('scroll'))
  now += 1000
  turnHeight = 300
  await resize()
  expect(viewport().scrollTop).toBe(20)
})
