import { BrowserWindow } from 'electron'
import { createTerminalCore } from './terminal-core'
import { expandHomePath } from './workspace-service'

// Electron owns windows; the PTY lifecycle is shared with the mobile Companion.
export function createTerminalService() {
  return createTerminalCore<Electron.WebContents>({
    ownerId: sender => BrowserWindow.fromWebContents(sender)?.id,
    expandPath: expandHomePath,
    send: (windowId, channel, payload) => {
      const window = BrowserWindow.fromId(windowId)
      if (!window || window.isDestroyed() || window.webContents.isDestroyed()) return false
      try {
        window.webContents.send(channel, payload)
        return true
      } catch {
        return false
      }
    }
  })
}
