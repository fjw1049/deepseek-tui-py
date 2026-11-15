import { tmpdir } from 'node:os'
import { afterEach, expect, it, vi } from 'vitest'
import { createTerminalCore } from './terminal-core'

const callbacks = vi.hoisted(() => ({ data: (_data: string) => {}, exit: (_event: {exitCode: number}) => {} }))
const pty = vi.hoisted(() => ({ cols: 80, rows: 24, resize: vi.fn(), write: vi.fn(), kill: vi.fn(),
  onData: vi.fn((callback: (data: string) => void) => { callbacks.data = callback }),
  onExit: vi.fn((callback: (event: {exitCode: number}) => void) => { callbacks.exit = callback })
}))
vi.mock('node-pty', () => ({spawn: () => pty}))
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

it('shares owner-specific data, input, exit and cleanup without Electron', async () => {
  vi.useFakeTimers()
  const send = vi.fn(() => true)
  const service = createTerminalCore<number>({ownerId: sender => sender, expandPath: p => p, send})
  const created = await service.createTerminalSession(17, {cwd: tmpdir()})
  expect(created.ok).toBe(true)
  if (!created.ok) return
  const id = created.session.id
  callbacks.data('output')
  vi.advanceTimersByTime(20)
  expect(send).toHaveBeenCalledWith(17, 'terminal:data', {sessionId: id, data: 'output'})
  service.writeTerminalSession({sessionId: id, data: '\x03'})
  expect(pty.write).toHaveBeenCalledWith('\x03')
  service.disposeTerminalSessionsForWindow(18)
  expect(pty.kill).not.toHaveBeenCalled()
  callbacks.exit({exitCode: 0})
  expect(send).toHaveBeenCalledWith(17, 'terminal:exit', {sessionId: id, exitCode: 0, signal: undefined})
  expect(service.writeTerminalSession({sessionId: id, data: 'no'})).toBe(false)
})

it('kills the PTY when its output transport is gone', async () => {
  vi.useFakeTimers()
  const service = createTerminalCore<number>({ownerId: sender => sender, expandPath: p => p, send: () => false})
  const created = await service.createTerminalSession(3, {cwd: tmpdir()})
  expect(created.ok).toBe(true)
  callbacks.data('output')
  vi.advanceTimersByTime(20)
  expect(pty.kill).toHaveBeenCalledOnce()
})
