// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CuaPreview } from './CuaPreview'
import { noteCuaTurnEnded, useCuaPreviewStore, type CuaPreviewSession } from '../../store/cua-preview-store'

const t = (key: string) => key
const capture = vi.hoisted(() => ({ enabled: false }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }))
vi.mock('./use-cua-window-stream', () => ({ useCuaWindowStream: (input: { enabled: boolean }) => {
  capture.enabled = input.enabled
  return { status: 'permission', hasFrame: false, frameSize: null, appName: null, icon: null }
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
  useCuaPreviewStore.setState({ sessions: {} }); vi.useRealTimers()
})

it('starts compact without live capture or preview errors and keeps controls after closing', async () => {
  expect(capture.enabled).toBe(false)
  expect(document.body.textContent).toContain('Fill shipping address')
  expect(document.body.textContent).not.toContain('cuaPreviewPermission')
  expect(document.body.textContent).not.toContain('cuaControlAgent')
  const takeover = find('cuaControlTakeover')
  expect(takeover).toBeTruthy()
  await expand()
  expect(capture.enabled).toBe(true)
  expect(document.body.textContent).toContain('cuaPreviewPermission')
  await collapse()
  expect(capture.enabled).toBe(false)
  expect(find('cuaControlTakeover')).toBe(takeover)
  expect(request.mock.calls.filter(call => call[1] === 'POST')).toHaveLength(0)
  await act(async () => { takeover.click() })
  expect(document.body.textContent).toContain('cuaControlHuman')
  expect(find('cuaControlContinue')).toBeTruthy()
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
  expect(capture.enabled).toBe(false)
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
