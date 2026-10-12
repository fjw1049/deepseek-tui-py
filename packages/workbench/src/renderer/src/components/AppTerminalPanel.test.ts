// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, expect, it, vi } from 'vitest'
import { AppTerminalPanel } from './AppTerminalPanel'
import { useTerminalSessionStore } from '../store/terminal-session-store'

const mocks = vi.hoisted(() => ({
  terminals: [] as Array<{ dispose: ReturnType<typeof vi.fn>; focus: ReturnType<typeof vi.fn>; write: ReturnType<typeof vi.fn> }>,
  onData: (_event: { sessionId: string; data: string }) => {},
  effectVersion: 0
}))
vi.mock('react', async (importOriginal) => {
  const react = await importOriginal<typeof import('react')>()
  return { ...react, useEffect: (effect: Parameters<typeof react.useEffect>[0], deps?: Parameters<typeof react.useEffect>[1]) =>
    react.useEffect(effect, deps ? [...deps, mocks.effectVersion] : deps) }
})
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../lib/workspace-label', () => ({ terminalLabelFromPath: () => 'workspace' }))
vi.mock('../lib/apply-theme', () => ({ readTerminalFontFamily: () => 'monospace' }))
vi.mock('../lib/apply-appearance', () => ({ getTerminalFontSizePx: () => 14, subscribeAppearance: () => () => {} }))
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }))
vi.mock('@xterm/xterm', () => ({ Terminal: class {
  cols = 80
  rows = 24
  options = {}
  dispose = vi.fn()
  focus = vi.fn()
  constructor() { mocks.terminals.push(this) }
  open(host: HTMLElement) { host.setAttribute('data-xterm', 'mounted') }
  loadAddon() {}
  onData() { return { dispose: vi.fn() } }
  write = vi.fn()
} }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const state = () => useTerminalSessionStore.getState()

beforeEach(() => {
  state().resetSessions()
  state().markInitialSessionStarted()
  mocks.terminals.length = 0
  mocks.effectVersion = 0
  Object.assign(window, { dsGui: {
    createTerminalSession: vi.fn(async () => ({ ok: true, session: { id: `pane-${mocks.terminals.length}`, cwd: '/workspace' } })),
    resizeTerminalSession: vi.fn(), closeTerminalSession: vi.fn(),
    onTerminalData: (callback: typeof mocks.onData) => { mocks.onData = callback; return () => {} }, onTerminalExit: () => () => {}
  } })
})

it.each(['bottom', 'sidebar'] as const)('uses shared split controls on %s without remounting existing terminals', async (mountSurface) => {
  state().addSession({ id: 'a', cwd: '/workspace', status: 'running' })
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(AppTerminalPanel, { workspaceRoot: '/workspace', mountActive: true, mountSurface })))
    const originalHost = host.querySelector('[data-xterm]')
    const originalTerminal = mocks.terminals[0]
    for (const label of ['terminalSplitRight', 'terminalSplitDown']) {
      await act(async () => (host.querySelector(`[aria-label="${label}"]`) as HTMLButtonElement).click())
    }
    expect(host.querySelectorAll('[role="separator"]')).toHaveLength(2)
    expect(host.querySelectorAll('[data-xterm]')).toHaveLength(3)
    expect(host.querySelector('[data-xterm]')).toBe(originalHost)
    expect(originalTerminal.dispose).not.toHaveBeenCalled()
    const layout = state().layouts[0]
    await act(async () => state().setActiveSessionId('a'))
    expect(state().layouts[0]).toBe(layout)
    expect(originalTerminal.focus).toHaveBeenCalled()
    const separator = host.querySelector('[role="separator"]')!
    await act(async () => separator.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
    expect(separator.getAttribute('aria-valuenow')).toBe('55')
    await act(async () => separator.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })))
    expect(separator.getAttribute('aria-valuenow')).toBe('50')
    await act(async () => state().removeSession('pane-2'))
    expect(host.querySelectorAll('[role="separator"]')).toHaveLength(1)
    expect(originalTerminal.dispose).not.toHaveBeenCalled()
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})

it('coalesces split pointer moves and applies the final position on release', async () => {
  state().addSession({ id: 'a', cwd: '/workspace', status: 'running' })
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(AppTerminalPanel, { workspaceRoot: '/workspace', mountActive: true, mountSurface: 'bottom' })))
    await act(async () => (host.querySelector('[aria-label="terminalSplitRight"]') as HTMLButtonElement).click())
    const separator = host.querySelector('[role="separator"]') as HTMLDivElement
    vi.spyOn(separator, 'hasPointerCapture').mockReturnValue(true)
    vi.spyOn(separator.parentElement!, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 100, height: 100 } as DOMRect)
    const frames: FrameRequestCallback[] = []
    const requestFrame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      frames.push(callback)
      return frames.length
    })
    try {
      await act(async () => {
        separator.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 1, clientX: 60 }))
        separator.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, pointerId: 1, clientX: 80 }))
      })
      expect(frames).toHaveLength(1)
      expect(separator.getAttribute('aria-valuenow')).toBe('50')
      await act(async () => separator.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 })))
      expect(separator.getAttribute('aria-valuenow')).toBe('80')
    } finally {
      requestFrame.mockRestore()
    }
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})

it('recreates the terminal after effect cleanup while its host remains mounted', async () => {
  state().addSession({ id: 'a', cwd: '/workspace', status: 'running' })
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  try {
    const render = () => root.render(createElement(AppTerminalPanel, { workspaceRoot: '/workspace', mountActive: true, mountSurface: 'bottom' }))
    await act(async () => render())
    mocks.onData({ sessionId: 'a', data: 'existing terminal output\r\n' })
    expect(mocks.terminals[0].write).toHaveBeenCalledWith('existing terminal output\r\n')
    // Fast Refresh replays effects while preserving the mounted host and refs.
    mocks.effectVersion++
    await act(async () => render())
    expect(mocks.terminals).toHaveLength(2)
    expect(mocks.terminals[0].dispose).toHaveBeenCalledOnce()
    expect(mocks.terminals[1].write).toHaveBeenCalledWith('existing terminal output\r\n')
    expect(mocks.terminals.at(-1)!.dispose).not.toHaveBeenCalled()
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})
