import { beforeEach, expect, it, vi } from 'vitest'
import { buildPreviewPickerCleanupScript, buildPreviewPickerInjectScript } from '../../shared/preview-picker-scripts'
import { runDevBrowserPicker } from './dev-browser-picker'

const fromId = vi.hoisted(() => vi.fn())
vi.mock('electron', () => ({ webContents: { fromId }, clipboard: {}, nativeImage: {} }))

const mainWindow = { isDestroyed: () => false, webContents: { id: 1 } } as never
const executeJavaScript = vi.fn(async () => undefined)
function guest(frame: unknown = { isDestroyed: () => false, executeJavaScript }) {
  return { id: 42, isDestroyed: () => false, getType: () => 'webview', hostWebContents: { id: 1, isDestroyed: () => false }, mainFrame: frame }
}
beforeEach(() => vi.clearAllMocks())

it('runs the picker scripts in the main frame instead of waiting for the page to finish loading', async () => {
  fromId.mockReturnValue(guest())
  expect(await runDevBrowserPicker(mainWindow, 42, 'arm', 1)).toEqual({ ok: true })
  expect(executeJavaScript).toHaveBeenLastCalledWith(buildPreviewPickerInjectScript())
  expect(await runDevBrowserPicker(mainWindow, 42, 'disarm', 1)).toEqual({ ok: true })
  expect(executeJavaScript).toHaveBeenLastCalledWith(buildPreviewPickerCleanupScript())
})

it('refuses targets outside the requesting window and reports script failures', async () => {
  fromId.mockReturnValue(guest())
  expect((await runDevBrowserPicker(mainWindow, 42, 'arm', 2)).ok).toBe(false)
  expect(executeJavaScript).not.toHaveBeenCalled()
  fromId.mockReturnValue(guest({ isDestroyed: () => true, executeJavaScript }))
  expect(await runDevBrowserPicker(mainWindow, 42, 'arm', 1)).toEqual({ ok: false, message: 'Browser tab is not ready.' })
  fromId.mockReturnValue(guest({ isDestroyed: () => false, executeJavaScript: vi.fn(async () => { throw new Error('Script failed to execute') }) }))
  expect(await runDevBrowserPicker(mainWindow, 42, 'arm', 1)).toEqual({ ok: false, message: 'Script failed to execute' })
})
