import type { BrowserWindow } from 'electron'
import { buildPreviewPickerCleanupScript, buildPreviewPickerInjectScript } from '../../shared/preview-picker-scripts'
import { resolveDevBrowserGuestWebContents } from './dev-browser-screenshot'

export type DevBrowserPickerAction = 'arm' | 'disarm'

/**
 * Arms or disarms the element picker in a browser tab. Runs in the main frame directly:
 * `webview.executeJavaScript` waits for loading to stop, which on busy pages may be never.
 */
export async function runDevBrowserPicker(
  mainWindow: BrowserWindow | null,
  webContentsId: number,
  action: DevBrowserPickerAction,
  senderWebContentsId?: number
): Promise<{ ok: true } | { ok: false; message: string }> {
  const resolved = resolveDevBrowserGuestWebContents(mainWindow, webContentsId, senderWebContentsId)
  if (!resolved.ok) return resolved
  const frame = resolved.guest.mainFrame
  if (!frame || frame.isDestroyed()) return { ok: false, message: 'Browser tab is not ready.' }
  try {
    await frame.executeJavaScript(action === 'arm' ? buildPreviewPickerInjectScript() : buildPreviewPickerCleanupScript())
    return { ok: true }
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : String(error) }
  }
}
