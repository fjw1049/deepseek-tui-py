import { beforeEach, expect, it, vi } from 'vitest'
import { runInNewContext } from 'node:vm'

const electron = vi.hoisted(() => ({
  app: { getName: () => 'Workbench' },
  ipcMain: { handle: vi.fn() },
  systemPreferences: { getMediaAccessStatus: vi.fn(() => 'not-determined') },
  desktopCapturer: { getSources: vi.fn(async () => []) },
  shell: { showItemInFolder: vi.fn(), openExternal: vi.fn(async () => {}) }
}))
vi.mock('electron', () => electron)
vi.mock('node:os', () => ({ release: () => '25.0.0' }))
const execute = vi.hoisted(() => vi.fn())
vi.mock('node:child_process', () => ({ execFile: execute }))

const { pickPreviewWindow, registerCuaWindowPreviewIpc, resolveCuaPreviewWindow } = await import('./cua-window-preview')

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
it.skipIf(process.platform !== 'darwin').each(['1', 1, '0', '2'])('handles native application count %s', async count => {
  const activate = vi.fn(() => true)
  execute.mockImplementation((_file, args, _options, callback) => {
    const result = runInNewContext(`${args[3]}; run(["com.soda.music"])`, {
      ObjC: { import: () => {} },
      $: { NSRunningApplication: { runningApplicationsWithBundleIdentifier: () => ({
        count, objectAtIndex: () => ({ activateWithOptions: activate })
      }) } }
    })
    callback(null, result)
  })
  registerCuaWindowPreviewIpc(() => true)
  const open = electron.ipcMain.handle.mock.calls.find(c => c[0] === 'cua-preview:open-app')![1]
  expect(await open({}, 'com.soda.music')).toBe(Number(count) === 1)
  expect(activate).toHaveBeenCalledTimes(Number(count) === 1 ? 1 : 0)
})
it.skipIf(process.platform !== 'darwin')('opens only a validated app from a trusted renderer', async () => {
  execute.mockImplementation((_file, _args, _options, callback) => callback(null, 'true'))
  registerCuaWindowPreviewIpc(() => true)
  const open = electron.ipcMain.handle.mock.calls.find(c => c[0] === 'cua-preview:open-app')![1]
  expect(await open({}, 'com.iqiyi.player')).toBe(true)
  expect(execute).toHaveBeenCalledWith('/usr/bin/osascript',
    ['-l', 'JavaScript', '-e', expect.stringContaining('activateWithOptions(2)'), 'com.iqiyi.player'],
    { timeout: 5_000 }, expect.any(Function))
  execute.mockImplementation((_file, _args, _options, callback) => callback(null, 'false'))
  expect(await open({}, 'com.iqiyi.player')).toBe(false)
  execute.mockImplementation((_file, _args, _options, callback) => callback(new Error('activation failed'), ''))
  expect(await open({}, 'com.iqiyi.player')).toBe(false)
  execute.mockClear()
  expect(await open({}, '-a Calculator')).toBe(false)
  expect(execute).not.toHaveBeenCalled()
  electron.ipcMain.handle.mockClear()
  registerCuaWindowPreviewIpc(() => false)
  const untrusted = electron.ipcMain.handle.mock.calls.find(c => c[0] === 'cua-preview:open-app')![1]
  expect(await untrusted({}, 'com.iqiyi.player')).toBe(false)
  expect(execute).not.toHaveBeenCalled()
})
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

it.skipIf(process.platform !== 'darwin').each(['error', 'invalid'])('reports lookup failure for %s instead of a missing window', async mode => {
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  electron.systemPreferences.getMediaAccessStatus.mockReturnValue('granted')
  execute.mockImplementation((_file, _args, _options, callback) =>
    callback(mode === 'error' ? new Error('lookup timed out') : null, 'invalid json'))
  expect(await resolveCuaPreviewWindow('com.soda.music')).toMatchObject({ status: 'lookup-failed' })
  vi.mocked(console.warn).mockRestore()
})

it.skipIf(process.platform !== 'darwin')('distinguishes an empty window list from a capture enumeration error', async () => {
  electron.systemPreferences.getMediaAccessStatus.mockReturnValue('granted')
  execute.mockImplementation((_file, _args, _options, callback) =>
    callback(null, JSON.stringify({ name: 'Music', path: '', windows: [] })))
  expect(await resolveCuaPreviewWindow('com.soda.music')).toMatchObject({ status: 'no-window' })
  execute.mockImplementation((_file, _args, _options, callback) =>
    callback(null, JSON.stringify({ name: 'Music', path: '', windows: [window(99)] })))
  electron.desktopCapturer.getSources.mockRejectedValueOnce(new Error('enumeration failed'))
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => {})
  expect(await resolveCuaPreviewWindow('com.soda.music')).toMatchObject({ status: 'lookup-failed' })
  expect(warning).toHaveBeenCalled()
  warning.mockRestore()
})
