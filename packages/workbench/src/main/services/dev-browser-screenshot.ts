import { clipboard, nativeImage, webContents, type BrowserWindow } from 'electron'

export type DevBrowserScreenshotResult =
  | { ok: true }
  | { ok: false; message: string }

export function resolveDevBrowserGuestWebContents(
  mainWindow: BrowserWindow | null,
  webContentsId: number,
  senderWebContentsId?: number
): { ok: true; guest: Electron.WebContents } | { ok: false; message: string } {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return { ok: false, message: 'Main window unavailable.' }
  }

  if (
    typeof senderWebContentsId === 'number' &&
    senderWebContentsId !== mainWindow.webContents.id
  ) {
    return { ok: false, message: 'Screenshot request came from an unexpected window.' }
  }

  const guest = webContents.fromId(webContentsId)
  if (!guest || guest.isDestroyed()) {
    return { ok: false, message: 'Browser tab is not ready.' }
  }

  // Never capture the shell renderer itself.
  if (guest.id === mainWindow.webContents.id) {
    return { ok: false, message: 'Invalid browser target.' }
  }

  const host = guest.hostWebContents
  if (host && !host.isDestroyed()) {
    if (host.id !== mainWindow.webContents.id) {
      return { ok: false, message: 'Browser tab belongs to another window.' }
    }
    return { ok: true, guest }
  }

  // Some Electron builds omit hostWebContents on webview guests. Allow capture
  // when the IPC sender is the main renderer window.
  if (typeof senderWebContentsId === 'number') {
    return { ok: true, guest }
  }

  return { ok: false, message: 'Browser tab is not attached.' }
}

async function captureGuestImage(
  guest: Electron.WebContents
): Promise<Electron.NativeImage> {
  try {
    const image = await guest.capturePage()
    if (!image.isEmpty()) {
      return image
    }
  } catch {
    /* fall through to CDP */
  }

  const debuggerSession = guest.debugger
  const wasAttached = debuggerSession.isAttached()
  if (!wasAttached) {
    debuggerSession.attach('1.3')
  }

  try {
    const response = (await debuggerSession.sendCommand('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true
    })) as { data?: string }
    if (typeof response.data !== 'string' || response.data.length === 0) {
      throw new Error('Screenshot capture returned no image data.')
    }
    const image = nativeImage.createFromBuffer(Buffer.from(response.data, 'base64'))
    if (image.isEmpty()) {
      throw new Error('Screenshot image is empty.')
    }
    return image
  } finally {
    if (!wasAttached && debuggerSession.isAttached()) {
      debuggerSession.detach()
    }
  }
}

export async function copyDevBrowserScreenshotToClipboard(
  mainWindow: BrowserWindow | null,
  webContentsId: number,
  senderWebContentsId?: number
): Promise<DevBrowserScreenshotResult> {
  const resolved = resolveDevBrowserGuestWebContents(
    mainWindow,
    webContentsId,
    senderWebContentsId
  )
  if (!resolved.ok) return resolved

  const captureTimeoutMs = 12_000
  try {
    const image = await Promise.race([
      captureGuestImage(resolved.guest),
      new Promise<never>((_, reject) => {
        setTimeout(() => reject(new Error('Screenshot timed out.')), captureTimeoutMs)
      })
    ])
    if (image.isEmpty()) {
      return { ok: false, message: 'Screenshot is empty.' }
    }
    clipboard.writeImage(image)
    return { ok: true }
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : String(error)
    }
  }
}
