// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, expect, it, vi } from 'vitest'
import { AppTerminalPanel } from './AppTerminalPanel'
import { useTerminalSessionStore } from '../store/terminal-session-store'

const mocks = vi.hoisted(() => ({ terminals: [] as Array<{ dispose: ReturnType<typeof vi.fn>; focus: ReturnType<typeof vi.fn> }> }))
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
  write() {}
} }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const state = () => useTerminalSessionStore.getState()

beforeEach(() => {
  state().resetSessions()
  state().markInitialSessionStarted()
  mocks.terminals.length = 0
  Object.assign(window, { dsGui: {
    createTerminalSession: vi.fn(async () => ({ ok: true, session: { id: `pane-${mocks.terminals.length}`, cwd: '/workspace' } })),
    resizeTerminalSession: vi.fn(), closeTerminalSession: vi.fn(),
    onTerminalData: () => () => {}, onTerminalExit: () => () => {}
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
