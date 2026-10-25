// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CuaPreview, CuaPreviewRailSlot } from './CuaPreview'
import { noteCuaTurnEnded, useCuaPreviewStore, type CuaPreviewSession } from '../../store/cua-preview-store'

const t = (key: string) => key
const capture = vi.hoisted(() => ({ enabled: false, hasFrame: false }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }))
vi.mock('./use-cua-window-stream', () => ({ useCuaWindowStream: (input: { enabled: boolean }) => {
  capture.enabled = input.enabled
  return { status: capture.hasFrame ? 'ok' : 'permission', hasFrame: capture.hasFrame, frameSize: null, appName: null, icon: null }
} }))
vi.mock('./use-cua-still-frame', () => ({ useCuaStillFrame: () => ({ status: 'idle', frameSize: null }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot>
let host: HTMLDivElement
let request: ReturnType<typeof vi.fn>
let session: CuaPreviewSession
const find = (text: string) => [...document.querySelectorAll('button')].find(button => button.textContent === text)!
const expand = () => act(async () => { (document.querySelector('[aria-expanded="false"]') as HTMLElement).click() })
const collapse = () => act(async () => { (document.querySelector('[aria-label="cuaPreviewCollapse"]') as HTMLElement).click() })

beforeEach(async () => {
  vi.useFakeTimers()
  capture.hasFrame = false
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  session = { phase: 'live', turnId: 'turn', appId: 'A', surface: 'app', label: 'Fill shipping address', still: null, revision: 0 }
  useCuaPreviewStore.setState({ sessions: { thread: session } })
  request = vi.fn(async (_path: string, method: string) => ({ ok: true, body: JSON.stringify({
    used: true, active: true, available: true, turn_id: 'turn', revision: 1,
    owner: method === 'POST' ? 'user' : 'assistant', waiting: false, paused: false, unresolved: null
  }) }))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    platform: 'darwin', getSettings: async () => ({ cuaWindowPreview: true }), runtimeRequest: request
  } })
  await act(async () => root.render(createElement(CuaPreview, { threadId: 'thread' })))
})
afterEach(async () => {
  await act(async () => root.unmount()); host.remove()
  useCuaPreviewStore.setState({ sessions: {} }); vi.useRealTimers(); vi.restoreAllMocks()
})

it('waits for a frame while capturing and keeps controls after a manual collapse', async () => {
  expect(capture.enabled).toBe(true)
  expect(document.body.textContent).toContain('cuaPreviewWorking')
  expect(document.body.textContent).not.toContain('Fill shipping address')
  expect(document.querySelector('[title="Fill shipping address"]')).not.toBeNull()
  expect(document.body.textContent).not.toContain('cuaPreviewPermission')
  expect(document.body.textContent).not.toContain('cuaControlAgent')
  const takeover = find('cuaControlTakeover')
  expect(takeover).toBeTruthy()
  await expand()
  expect(capture.enabled).toBe(true)
  expect(document.body.textContent).not.toContain('cuaPreviewWorking')
  expect(document.body.textContent).toContain('cuaPreviewPermission')
  await collapse()
  expect(capture.enabled).toBe(false)
  expect(find('cuaControlTakeover')).toBe(takeover)
  expect(request.mock.calls.filter(call => call[1] === 'POST')).toHaveLength(0)
  await act(async () => { takeover.click() })
  expect(document.body.textContent).toContain('cuaControlHuman')
  expect(find('cuaControlContinue')).toBeTruthy()
})

it('opens the bound app without transferring desktop control and reports launch failures', async () => {
  const openApp = vi.fn().mockResolvedValueOnce(true).mockResolvedValueOnce(false)
  window.dsGui.openCuaApp = openApp
  await expand()
  const button = document.querySelector('[aria-label="cuaPreviewOpenApp"]') as HTMLButtonElement
  // Usable while the assistant works; the host makes its next call observe first.
  expect(button.disabled).toBe(false)
  await act(async () => button.click())
  expect(openApp).toHaveBeenCalledWith('A')
  const posts = request.mock.calls.filter(call => call[1] === 'POST').map(call => call[0])
  expect(posts).toEqual(['/v1/threads/thread/cua/raised'])
  await act(async () => button.click())
  const notice = document.querySelector('[role="status"][title="cuaPreviewOpenAppFailed"]')!
  expect(notice.textContent).toBe('cuaPreviewOpenAppFailedShort')
  expect(notice.parentElement?.parentElement).toBe(button.parentElement)
  expect(document.querySelector('[role="alert"]')).toBeNull()
  openApp.mockResolvedValueOnce(true)
  await act(async () => button.click())
  expect(document.querySelector('[title="cuaPreviewOpenAppFailed"]')).toBeNull()
})

it('keeps viewing and controls stable across targets, and preserves the ended viewer until closed', async () => {
  await expand()
  const takeover = find('cuaControlTakeover')
  await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, appId: 'B' } } }))
  expect(document.querySelector('[aria-label="cuaPreviewCollapse"]')).not.toBeNull()
  expect(find('cuaControlTakeover')).toBe(takeover)
  await act(async () => noteCuaTurnEnded('thread'))
  expect(capture.enabled).toBe(false)
  expect(document.querySelector('[aria-label="cuaPreviewCollapse"]')).not.toBeNull()
  await collapse()
  expect(document.body.textContent).toContain('cuaPreviewEnded')
  expect(useCuaPreviewStore.getState().sessions.thread?.phase).toBe('ended')
  await expand()
  expect(capture.enabled).toBe(false)
})

it('collapses with Escape and starts the next turn compact', async () => {
  await expand()
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
  expect(document.querySelector('[aria-expanded="false"]')).not.toBeNull()
  await expand()
  await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, turnId: 'next' } } }))
  expect(document.querySelector('[aria-expanded="false"]')).not.toBeNull()
  expect(capture.enabled).toBe(true)
})


it('keeps controls available when preview is disabled', async () => {
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    platform: 'darwin', getSettings: async () => ({ cuaWindowPreview: false }), runtimeRequest: request
  } })
  await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, appId: 'disabled-target' } } }))
  await expand()
  expect(capture.enabled).toBe(false)
  expect(document.body.textContent).toContain('cuaPreviewDisabled')
  expect(find('cuaControlTakeover')).toBeTruthy()
  await collapse()
  expect(find('cuaControlStop')).toBeTruthy()
})

it('closes an ended card only once nothing on it awaits review', async () => {
  const dismiss = () => document.querySelector('[aria-label="cuaPreviewDismiss"]') as HTMLElement | null
  expect(dismiss()).toBeNull()
  let unresolved: { call_id: string; turn_id: string } | null = { call_id: 'submit', turn_id: 'turn' }
  request.mockImplementation(async () => ({ ok: true, body: JSON.stringify({
    used: true, active: false, available: true, turn_id: 'turn', revision: 2,
    owner: 'idle', waiting: false, paused: false, unresolved
  }) }))
  await act(async () => { noteCuaTurnEnded('thread') })
  await act(async () => { await vi.advanceTimersByTimeAsync(1100) })
  expect(dismiss()).toBeNull()
  unresolved = null
  await act(async () => { await vi.advanceTimersByTimeAsync(1100) })
  await act(async () => { dismiss()!.click() })
  expect(useCuaPreviewStore.getState().sessions.thread).toBeUndefined()
})


it('opens on the first frame, stays collapsed after user choice, and re-arms for a new turn', async () => {
  capture.hasFrame = true
  await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, revision: 1 } } }))
  expect(document.querySelector('[aria-label="cuaPreviewCollapse"]')).not.toBeNull()
  await collapse()
  expect(capture.enabled).toBe(false)
  await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, revision: 2 } } }))
  expect(document.querySelector('[aria-expanded="false"]')).not.toBeNull()
  await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, turnId: 'new-turn' } } }))
  expect(document.querySelector('[aria-label="cuaPreviewCollapse"]')).not.toBeNull()
})

it('shows verified success briefly, then collapses once and permits reopening', async () => {
  await expand()
  request.mockResolvedValue({ ok: true, body: JSON.stringify({ used: true, active: false, available: true, turn_id: 'turn', unresolved: null }) })
  await act(async () => noteCuaTurnEnded('thread', 'completed'))
  expect(document.body.textContent).toContain('cuaPreviewDone')
  expect(document.querySelector('.text-emerald-600')).not.toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
  expect(document.querySelector('[aria-expanded="false"]')).not.toBeNull()
  await expand()
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  expect(document.querySelector('[aria-label="cuaPreviewCollapse"]')).not.toBeNull()
})

it('keeps an unresolved result open without a success check', async () => {
  await expand()
  request.mockResolvedValue({ ok: true, body: JSON.stringify({ used: true, active: false, available: true, turn_id: 'turn', unresolved: { call_id: 'unknown', turn_id: 'turn' } }) })
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  await act(async () => noteCuaTurnEnded('thread', 'completed'))
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  expect(document.querySelector('[aria-label="cuaPreviewCollapse"]')).not.toBeNull()
  expect(document.querySelector('.text-emerald-600')).toBeNull()
})

it('expands inside the same rail slot instead of moving to a fixed overlay', async () => {
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', { configurable: true, get: () => document.body })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(320)
  await act(async () => root.render(createElement('div', null,
    createElement(CuaPreviewRailSlot), createElement(CuaPreview, { threadId: 'thread' }))))
  const card = document.querySelector('[data-cua-preview]')!
  const parent = card.parentElement
  expect(parent?.classList.contains('ds-cua-preview-slot')).toBe(true)
  await expand()
  expect(document.querySelector('[data-cua-preview]')).toBe(card)
  expect(card.parentElement).toBe(parent)
  expect(card.classList.contains('fixed')).toBe(false)
  expect(card.classList.contains('w-full')).toBe(true)
  expect(card.classList.contains('max-w-80')).toBe(false)
  Reflect.deleteProperty(HTMLElement.prototype, 'offsetParent')
})

it('measures layout height without applying UI zoom twice and follows control-bar growth', async () => {
  const observers: Array<() => void> = []
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { observers.push(callback) }
    observe() {}
    disconnect() {}
  })
  try {
    await act(async () => root.render(createElement(CuaPreview, { key: 'zoom-test', threadId: 'thread' })))
    const card = document.querySelector('[data-cua-preview]') as HTMLElement
    const content = card.firstElementChild as HTMLElement
    let layoutHeight = 128
    Object.defineProperty(content, 'offsetHeight', { configurable: true, get: () => layoutHeight })
    const bounds = vi.spyOn(content, 'getBoundingClientRect')
    for (const zoom of [0.8, 1, 1.25]) {
      bounds.mockReturnValue({ height: layoutHeight * zoom } as DOMRect)
      await act(async () => observers.forEach(measure => measure()))
      expect(card.style.height).toBe('130px')
    }
    layoutHeight = 176
    await act(async () => observers.forEach(measure => measure()))
    expect(card.style.height).toBe('178px')
  } finally { vi.unstubAllGlobals() }
})

it('keeps the fallback inside the conversation rather than covering sibling panels', async () => {
  const card = host.querySelector('[data-cua-preview]')!
  expect(card.closest('[data-cua-conversation-preview]')).not.toBeNull()
  expect(card.classList.contains('fixed')).toBe(false)
  await expand()
  expect(host.querySelector('[data-cua-preview]')).toBe(card)
  expect(card.classList.contains('fixed')).toBe(false)
  expect(request.mock.calls.filter(call => call[1] === 'POST')).toHaveLength(0)
})

it('returns to the conversation when the operation rail hides and docks again without transferring control', async () => {
  let visible = true
  const observers: Array<() => void> = []
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { observers.push(callback) }
    observe() {}
    disconnect() {}
  })
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', { configurable: true, get: () => visible ? document.body : null })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(320)
  try {
    await act(async () => root.render(createElement('div', null,
      createElement(CuaPreviewRailSlot), createElement(CuaPreview, { threadId: 'thread' }))))
    expect(host.querySelector('.ds-cua-preview-slot [data-cua-preview]')).not.toBeNull()
    visible = false
    await act(async () => [...observers].forEach(update => update()))
    expect(host.querySelector('[data-cua-conversation-preview] [data-cua-preview]')).not.toBeNull()
    expect(document.body.querySelectorAll('[data-cua-preview]')).toHaveLength(1)
    visible = true
    await act(async () => [...observers].forEach(update => update()))
    expect(host.querySelector('.ds-cua-preview-slot [data-cua-preview]')).not.toBeNull()
    expect(request.mock.calls.filter(call => call[1] === 'POST')).toHaveLength(0)
    expect(useCuaPreviewStore.getState().sessions.thread?.phase).toBe('live')
  } finally {
    Reflect.deleteProperty(HTMLElement.prototype, 'offsetParent')
    vi.unstubAllGlobals()
  }
})


it('keeps an icon in the compact rail and peeks without transferring control', async () => {
  let width = 320
  const observers: Array<() => void> = []
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { observers.push(callback) }
    observe() {}
    disconnect() {}
  })
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', { configurable: true, get: () => document.body })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width)
  try {
    await act(async () => root.render(createElement('div', null,
      createElement(CuaPreviewRailSlot), createElement(CuaPreview, { threadId: 'thread' }))))
    await expand()
    width = 36
    await act(async () => [...observers].forEach(update => update()))
    const icon = host.querySelector<HTMLButtonElement>('.ds-cua-preview-slot button')!
    expect(icon).not.toBeNull()
    expect(host.querySelector('[data-cua-conversation-preview]')).toBeNull()
    const card = () => document.querySelector<HTMLElement>('[data-cua-preview]')!
    expect(card().hidden).toBe(true)
    await act(async () => icon.click())
    expect(card().hidden).toBe(false)
    expect(icon.getAttribute('aria-expanded')).toBe('true')
    await act(async () => document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })))
    expect(card().hidden).toBe(true)
    await act(async () => icon.click())
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(card().hidden).toBe(true)
    width = 320
    await act(async () => [...observers].forEach(update => update()))
    expect(host.querySelector('.ds-cua-preview-slot [data-cua-preview]')).not.toBeNull()
    expect(document.querySelectorAll('[data-cua-preview]')).toHaveLength(1)
    expect(request.mock.calls.filter(call => call[1] === 'POST')).toHaveLength(0)
    expect(useCuaPreviewStore.getState().sessions.thread?.phase).toBe('live')
  } finally {
    Reflect.deleteProperty(HTMLElement.prototype, 'offsetParent')
    vi.unstubAllGlobals()
  }
})

it('auto-opens the compact preview on the first frame and respects manual dismissal for the turn', async () => {
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', { configurable: true, get: () => document.body })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(36)
  try {
    await act(async () => root.render(createElement('div', null,
      createElement(CuaPreviewRailSlot), createElement(CuaPreview, { threadId: 'thread' }))))
    const card = () => document.querySelector<HTMLElement>('[data-cua-preview]')!
    expect(capture.enabled).toBe(true)
    expect(card().hidden).toBe(true)
    capture.hasFrame = true
    await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, revision: 2 } } }))
    expect(card().hidden).toBe(false)
    await act(async () => document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })))
    expect(card().hidden).toBe(true)
    expect(capture.enabled).toBe(false)
    await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, revision: 3 } } }))
    expect(card().hidden).toBe(true)
    await act(async () => useCuaPreviewStore.setState({ sessions: { thread: { ...session, turnId: 'next-turn' } } }))
    expect(card().hidden).toBe(false)
    expect(request.mock.calls.filter(call => call[1] === 'POST')).toHaveLength(0)
  } finally {
    Reflect.deleteProperty(HTMLElement.prototype, 'offsetParent')
  }
})
