import { ipcMain, screen, type BrowserWindow } from 'electron'

export function registerStartupWindowDrag(getWindow: () => BrowserWindow | null): void {
  let gesture: { window: BrowserWindow; x: number; y: number; cursorX: number; cursorY: number } | undefined
  const end = (): void => {
    gesture?.window.removeListener('blur', end)
    gesture?.window.removeListener('closed', end)
    gesture = undefined
  }
  ipcMain.on('window:startup-drag', (event, action: unknown) => {
    const win = getWindow()
    if (!win || win.isDestroyed() || event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame) return
    if (action === 'end') { end(); return }
    if (action !== 'start' && action !== 'move') return
    if (!win.isFocused() || win.isMaximized() || win.isFullScreen()) { end(); return }
    const cursor = screen.getCursorScreenPoint()
    if (action === 'start') {
      end()
      const [x, y] = win.getPosition()
      gesture = { window: win, x, y, cursorX: cursor.x, cursorY: cursor.y }
      win.once('blur', end)
      win.once('closed', end)
    } else if (gesture?.window === win) {
      win.setPosition(
        Math.round(gesture.x + cursor.x - gesture.cursorX),
        Math.round(gesture.y + cursor.y - gesture.cursorY)
      )
    }
  })
}
