import { EventEmitter } from 'node:events'
import { expect, it, vi } from 'vitest'
const electron = vi.hoisted(() => ({ on: vi.fn(), cursor: vi.fn() }))
vi.mock('electron', () => ({ ipcMain: { on: electron.on }, screen: { getCursorScreenPoint: electron.cursor } }))
import { registerStartupWindowDrag } from './startup-window-drag'

it('moves from the original screen offset and stops on release, blur or fullscreen', () => {
  const win = Object.assign(new EventEmitter(), {
    webContents: { mainFrame: {} }, isDestroyed: () => false, isFocused: () => true,
    isMaximized: () => false, isFullScreen: vi.fn(() => false),
    getPosition: () => [100, 200], setPosition: vi.fn()
  })
  registerStartupWindowDrag(() => win as never)
  const handler = electron.on.mock.calls[0][1]
  const event = { sender: win.webContents, senderFrame: win.webContents.mainFrame }
  electron.cursor.mockReturnValue({ x: 400, y: 450 })
  handler(event, 'move')
  expect(win.setPosition).not.toHaveBeenCalled()
  handler({ ...event, senderFrame: {} }, 'start')
  handler(event, 'move')
  expect(win.setPosition).not.toHaveBeenCalled()
  handler(event, 'start')
  electron.cursor.mockReturnValue({ x: 430, y: 490 })
  handler(event, 'move')
  expect(win.setPosition).toHaveBeenLastCalledWith(130, 240)
  electron.cursor.mockReturnValue({ x: 460, y: 470 })
  handler(event, 'move')
  expect(win.setPosition).toHaveBeenLastCalledWith(160, 220)
  handler(event, 'end')
  win.setPosition.mockClear()
  handler(event, 'move')
  expect(win.setPosition).not.toHaveBeenCalled()
  handler(event, 'start')
  win.emit('blur')
  handler(event, 'move')
  expect(win.setPosition).not.toHaveBeenCalled()
  expect(win.listenerCount('closed')).toBe(0)
  win.isFullScreen.mockReturnValue(true)
  handler(event, 'start')
  handler(event, 'move')
  expect(win.setPosition).not.toHaveBeenCalled()
})
