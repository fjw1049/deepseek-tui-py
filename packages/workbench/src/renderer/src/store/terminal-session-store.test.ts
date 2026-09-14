// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { terminalLayoutRects, terminalPaneIds } from '../lib/terminal-layout'
import { createTerminalSessionForWorkspace, splitTerminalSession, useTerminalSessionStore } from './terminal-session-store'

const state = () => useTerminalSessionStore.getState()
const add = (id: string) => state().addSession({ id, cwd: '/workspace', status: 'running' })

beforeEach(() => state().resetSessions())

describe('shared terminal splits', () => {
  it('preserves siblings on focus, mixes directions, restores groups and collapses closed panes', () => {
    add('a')
    state().addSession({ id: 'b', cwd: '/workspace', status: 'running' }, { targetId: 'a', direction: 'right' })
    state().addSession({ id: 'c', cwd: '/workspace', status: 'running' }, { targetId: 'b', direction: 'down' })
    const layout = state().layouts[0]
    state().setActiveSessionId('a')
    expect(state().layouts[0]).toBe(layout)
    expect(terminalLayoutRects(layout).panes).toEqual({
      a: { left: 0, top: 0, width: 50, height: 100 },
      b: { left: 50, top: 0, width: 50, height: 50 },
      c: { left: 50, top: 50, width: 50, height: 50 }
    })
    state().resizeSplit('split-b', 0.6)
    add('d')
    expect(state().layouts).toHaveLength(2)
    state().setActiveSessionId('c')
    expect(terminalLayoutRects(state().layouts[0]).panes.a.width).toBe(60)
    state().removeSession('c')
    expect(terminalPaneIds(state().layouts[0])).toEqual(['a', 'b'])
    expect(terminalLayoutRects(state().layouts[0]).panes.b.height).toBe(100)
    state().removeSession('a')
    expect(state().activeSessionId).toBe('b')
    expect(state().layouts[0]).toEqual({ type: 'pane', id: 'b' })
    state().removeSession('b')
    state().removeSession('d')
    expect(state().layouts).toEqual([])
    expect(state().activeSessionId).toBeNull()
  })

  it('does not change layout on failed creation and targets the originally focused pane during async creation', async () => {
    add('a')
    add('b')
    state().setActiveSessionId('a')
    const bridge = { createTerminalSession: vi.fn().mockResolvedValue({ ok: false, message: 'failed' }) }
    Object.assign(window, { dsGui: bridge })
    const layouts = state().layouts
    await splitTerminalSession('/workspace', 'right')
    expect(state().layouts).toBe(layouts)
    expect(state().createError).toBe('failed')
    let resolve!: (value: unknown) => void
    bridge.createTerminalSession.mockImplementation(() => new Promise((done) => { resolve = done }))
    const pending = splitTerminalSession('/workspace', 'down')
    state().setActiveSessionId('b')
    expect(await createTerminalSessionForWorkspace('/workspace')).toBe(false)
    resolve({ ok: true, session: { id: 'c', cwd: '/workspace' } })
    await pending
    expect(terminalPaneIds(state().layouts[0])).toEqual(['a', 'c'])
    expect(terminalPaneIds(state().layouts[1])).toEqual(['b'])
    expect(state().creatingSession).toBe(false)
  })
})
