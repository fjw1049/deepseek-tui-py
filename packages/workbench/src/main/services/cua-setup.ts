import { execFile } from 'node:child_process'
import { ipcMain, type IpcMainInvokeEvent } from 'electron'

const EXTENSION_ID = 'hehggadaopoacecdllhhajmbjkdcmajg'

/**
 * The only pages computer-use setup opens in Chrome: the official ChatGPT extension's store
 * page and its settings. The default browser may not be Chrome, and it cannot open chrome://.
 */
export const CHROME_SETUP_PAGES = {
  store: `https://chromewebstore.google.com/detail/chatgpt/${EXTENSION_ID}`,
  extension: `chrome://extensions/?id=${EXTENSION_ID}`
} as const

export type ChromeSetupPage = keyof typeof CHROME_SETUP_PAGES

export function chromeSetupUrl(page: unknown): string | null {
  return typeof page === 'string' && Object.hasOwn(CHROME_SETUP_PAGES, page)
    ? CHROME_SETUP_PAGES[page as ChromeSetupPage]
    : null
}

export function registerCuaSetupIpc(fromMainWindow: (event: IpcMainInvokeEvent) => boolean): void {
  ipcMain.handle('cua-setup:open-in-chrome', (event, page: unknown) => {
    const url = chromeSetupUrl(page)
    if (!fromMainWindow(event) || process.platform !== 'darwin' || !url) return false
    return new Promise<boolean>((resolve) => {
      execFile('/usr/bin/open', ['-a', 'Google Chrome', url], { timeout: 10_000 }, (error) => resolve(!error))
    })
  })
}
