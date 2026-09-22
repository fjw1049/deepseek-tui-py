import { tmpdir } from 'node:os'
import { expect, it, vi } from 'vitest'
import { createTerminalService } from './terminal-service'

const pty = vi.hoisted(() => ({ cols: 80, rows: 24, resize: vi.fn(), onData: vi.fn(), onExit: vi.fn(), kill: vi.fn() }))
vi.mock('node-pty', () => ({ spawn: () => pty }))
vi.mock('electron', () => ({ BrowserWindow: { fromWebContents: () => ({ id: 1 }) } }))
vi.mock('./workspace-service', () => ({ expandHomePath: (path: string) => path }))

it('resizes a short split pane to its actual row count', async () => {
  const service = createTerminalService()
  const result = await service.createTerminalSession({} as Electron.WebContents, { cwd: tmpdir(), cols: 80, rows: 8 })
  expect(result.ok).toBe(true)
  if (!result.ok) return
  service.resizeTerminalSession({ sessionId: result.session.id, cols: 40, rows: 6 })
  expect(pty.resize).toHaveBeenLastCalledWith(40, 6)
  service.closeTerminalSession({ sessionId: result.session.id })
})
