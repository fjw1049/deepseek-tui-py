import { beforeEach, expect, it, vi } from 'vitest'

const electron = vi.hoisted(() => ({
  app: { getName: () => 'Workbench' },
  ipcMain: { handle: vi.fn() },
  systemPreferences: { getMediaAccessStatus: vi.fn(() => 'not-determined') },
  desktopCapturer: { getSources: vi.fn(async () => []) },
  shell: { showItemInFolder: vi.fn(), openExternal: vi.fn(async () => {}) }
}))
vi.mock('electron', () => electron)
vi.mock('node:os', () => ({ release: () => '25.0.0' }))

const { pickPreviewWindow, registerCuaWindowPreviewIpc } = await import('./cua-window-preview')

const window = (id: number, width = 1200, height = 800, layer = 0, alpha = 1) => ({ id, width, height, layer, alpha })

it('captures only an unambiguous normal window of the app', () => {
  // CGWindowList order is front to back; strips, palettes and invisible windows are skipped.
  expect(pickPreviewWindow([
    window(1, 1512, 33),
    window(2, 64, 64, 3),
    window(3, 900, 600, 0, 0),
    window(4)
  ])).toBe(4)
  expect(pickPreviewWindow([window(1, 1512, 33)])).toBeNull()
  expect(pickPreviewWindow([])).toBeNull()
  expect(pickPreviewWindow([window(4), window(5)])).toBeNull()
  expect(pickPreviewWindow([window(5), window(4)])).toBeNull()
})


beforeEach(() => {
  vi.clearAllMocks()
  electron.systemPreferences.getMediaAccessStatus.mockReturnValue('not-determined')
  electron.desktopCapturer.getSources.mockResolvedValue([])
})
function handler(trusted = true) {
  registerCuaWindowPreviewIpc(() => trusted)
  return electron.ipcMain.handle.mock.calls.find(c => c[0] === 'cua-preview:open-screen-settings')![1]
}
it.skipIf(process.platform !== 'darwin')('requests native consent without opening Finder or competing settings on first use', async () => {
  await handler()({})
  expect(electron.desktopCapturer.getSources).toHaveBeenCalledWith({ types: ['screen'], thumbnailSize: { width: 1, height: 1 } })
  expect(electron.shell.openExternal).not.toHaveBeenCalled()
  expect(electron.shell.showItemInFolder).not.toHaveBeenCalled()
})
it('ignores an untrusted renderer', async () => {
  await handler(false)({})
  expect(electron.desktopCapturer.getSources).not.toHaveBeenCalled()
  expect(electron.shell.openExternal).not.toHaveBeenCalled()
})
it.skipIf(process.platform !== 'darwin')('tries native registration even if denied, then opens settings only if still denied', async () => {
  electron.systemPreferences.getMediaAccessStatus.mockReturnValue('denied')
  await handler()({})
  expect(electron.desktopCapturer.getSources).toHaveBeenCalledOnce()
  expect(electron.shell.openExternal).toHaveBeenCalledWith('x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture')
  expect(electron.shell.showItemInFolder).not.toHaveBeenCalled()
})
it.skipIf(process.platform !== 'darwin')('does not open settings when native consent grants access', async () => {
  electron.systemPreferences.getMediaAccessStatus.mockReturnValueOnce('denied').mockReturnValue('granted')
  await handler()({})
  expect(electron.shell.openExternal).not.toHaveBeenCalled()
})
it.skipIf(process.platform !== 'darwin')('reuses existing grants without requesting again', async () => {
  electron.systemPreferences.getMediaAccessStatus.mockReturnValue('granted')
  await handler()({})
  expect(electron.desktopCapturer.getSources).not.toHaveBeenCalled()
  expect(electron.shell.openExternal).not.toHaveBeenCalled()
})
it.skipIf(process.platform !== 'darwin')('opens settings without capturing when restricted', async () => {
  electron.systemPreferences.getMediaAccessStatus.mockReturnValue('restricted')
  await handler()({})
  expect(electron.desktopCapturer.getSources).not.toHaveBeenCalled()
  expect(electron.shell.openExternal).toHaveBeenCalledOnce()
})
it.skipIf(process.platform !== 'darwin')('surfaces a failed native request so the UI can offer retry', async () => {
  electron.desktopCapturer.getSources.mockRejectedValueOnce(new Error('capture failed'))
  await expect(handler()({})).rejects.toThrow('capture failed')
  expect(electron.shell.showItemInFolder).not.toHaveBeenCalled()
})

it.skipIf(process.platform !== 'darwin')('opens the recovery pane when denied capture rejects before enumeration', async () => {
  electron.systemPreferences.getMediaAccessStatus.mockReturnValue('denied')
  electron.desktopCapturer.getSources.mockRejectedValueOnce(new Error('Failed to get sources.'))
  await handler()({})
  expect(electron.shell.openExternal).toHaveBeenCalledWith('x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_ScreenCapture')
})
