import { app, desktopCapturer, ipcMain, shell, systemPreferences, type IpcMainInvokeEvent } from 'electron'
import { release } from 'node:os'
import { execFile } from 'node:child_process'
import type { CuaPreviewWindowResult } from '../../shared/ds-gui-api'

/**
 * Finds the window the computer-use preview should show for one app.
 *
 * The runtime names the app it touched (bundle id) but not its window, so this picks
 * the app's only normal on-screen window. Only that one window is ever offered
 * for capture: an app without a capturable window yields no source, never the desktop.
 */

const BUNDLE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$/
/** Smaller layer-0 windows are title strips, palettes and popovers, not the app's content. */
const MIN_WINDOW_SIDE = 100
// Darwin 22 is macOS 13, which introduced the Settings extension routes.
const privacyPane = Number.parseInt(release(), 10) >= 22
  ? 'com.apple.settings.PrivacySecurity.extension'
  : 'com.apple.preference.security'
const SCREEN_SETTINGS = `x-apple.systempreferences:${privacyPane}?Privacy_ScreenCapture`

// Activate an existing process without sending an open/reopen event or launching it.
const ACTIVATE_APP = `ObjC.import('AppKit')
function run(argv) {
  const apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(argv[0])
  if (Number(apps.count) !== 1) return 'false'
  return apps.objectAtIndex(0).activateWithOptions(2) ? 'true' : 'false'
}`

// 17 = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements; the
// list is ordered front to back. Windows on other Spaces are not on screen and
// cannot be captured, so they are left out.
const LIST_APP_WINDOWS = `ObjC.import('AppKit')
ObjC.import('CoreGraphics')
function run(argv) {
  const apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(argv[0])
  const pids = []
  let name = ''
  let path = ''
  for (let i = 0; i < apps.count; i++) {
    const app = apps.objectAtIndex(i)
    pids.push(app.processIdentifier)
    name = name || ObjC.unwrap(app.localizedName) || ''
    path = path || ObjC.unwrap(app.bundleURL.path) || ''
  }
  const all = pids.length ? ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(17, 0))) : []
  const windows = all.filter(w => pids.includes(w.kCGWindowOwnerPID)).map(w => ({
    id: w.kCGWindowNumber, layer: w.kCGWindowLayer, alpha: w.kCGWindowAlpha,
    width: w.kCGWindowBounds.Width, height: w.kCGWindowBounds.Height
  }))
  return JSON.stringify({ name, path, windows })
}`

export type AppWindow = { id: number; layer: number; alpha: number; width: number; height: number }
type AppWindows = { name: string; path: string; windows: AppWindow[] }

/** Never guess which of an app's windows belongs to the task. */
export function pickPreviewWindow(windows: AppWindow[]): number | null {
  const candidates = windows.filter(
    (w) => w.layer === 0 && w.alpha > 0 && w.width >= MIN_WINDOW_SIDE && w.height >= MIN_WINDOW_SIDE
  )
  return candidates.length === 1 ? candidates[0].id : null
}

function listAppWindows(bundleId: string): Promise<AppWindows | null> {
  return new Promise((resolve) => {
    execFile(
      '/usr/bin/osascript',
      ['-l', 'JavaScript', '-e', LIST_APP_WINDOWS, bundleId],
      { timeout: 5_000 },
      (error, stdout) => {
        if (error) return resolve(null)
        try {
          resolve(JSON.parse(stdout) as AppWindows)
        } catch {
          resolve(null)
        }
      }
    )
  })
}

const icons = new Map<string, string | null>()
let listed: { windowId: number; sourceId: string } | null = null

async function appIcon(path: string): Promise<string | null> {
  if (!path) return null
  if (!icons.has(path)) {
    const icon = await app.getFileIcon(path, { size: 'normal' }).catch(() => null)
    icons.set(path, icon && !icon.isEmpty() ? icon.toDataURL() : null)
  }
  return icons.get(path) ?? null
}

export async function resolveCuaPreviewWindow(bundleId: string): Promise<CuaPreviewWindowResult> {
  if (process.platform !== 'darwin' || !BUNDLE_ID.test(bundleId)) return { status: 'unsupported' }
  const access = systemPreferences.getMediaAccessStatus('screen')
  const found = await listAppWindows(bundleId)
  const identity = { appName: found?.name || undefined, icon: found ? await appIcon(found.path) : null }
  if (access === 'denied' || access === 'restricted') return { status: 'permission', ...identity }
  const windowId = found ? pickPreviewWindow(found.windows) : null
  if (windowId === null) return { status: found?.windows.some(w => w.layer === 0 && w.alpha > 0 && w.width >= MIN_WINDOW_SIDE && w.height >= MIN_WINDOW_SIDE) ? 'ambiguous' : 'no-window', ...identity }
  // Every call re-checks the window; only a different window needs the capturer's list.
  if (listed?.windowId === windowId) return { status: 'ok', sourceId: listed.sourceId, windowId, ...identity }
  // Capture accepts only a source id the capturer itself lists; listing also raises the
  // system's first-use Screen Recording prompt.
  const sources = await desktopCapturer
    .getSources({ types: ['window'], thumbnailSize: { width: 0, height: 0 } })
    .catch(() => [])
  const source = sources.find((s) => s.id.startsWith(`window:${windowId}:`))
  if (!source) return { status: access === 'granted' ? 'no-window' : 'permission', ...identity }
  listed = { windowId, sourceId: source.id }
  return { status: 'ok', sourceId: source.id, windowId, ...identity }
}

export function registerCuaWindowPreviewIpc(fromMainWindow: (event: IpcMainInvokeEvent) => boolean): void {
  ipcMain.handle('cua-preview:open-app', (event, bundleId: unknown) => {
    if (!fromMainWindow(event) || process.platform !== 'darwin' || typeof bundleId !== 'string' || !BUNDLE_ID.test(bundleId)) return false
    return new Promise<boolean>((resolve) => {
      execFile('/usr/bin/osascript', ['-l', 'JavaScript', '-e', ACTIVATE_APP, bundleId],
        { timeout: 5_000 }, (error, stdout) => resolve(!error && stdout.trim() === 'true'))
    })
  })
  ipcMain.handle('cua-preview:resolve-window', (event, bundleId: unknown) =>
    fromMainWindow(event) && typeof bundleId === 'string'
      ? resolveCuaPreviewWindow(bundleId)
      : { status: 'unsupported' }
  )
  ipcMain.handle('cua-preview:screen-permission', (event) => {
    if (!fromMainWindow(event) || process.platform !== 'darwin') return { status: 'unsupported', appName: app.getName() }
    // Development builds appear in macOS privacy settings as Electron.
    const appName = process.execPath.match(/([^/]+)\.app\/Contents\//)?.[1] ?? app.getName()
    return { status: systemPreferences.getMediaAccessStatus('screen'), appName, appId: process.execPath }
  })
  ipcMain.handle('cua-preview:open-screen-settings', async (event) => {
    if (process.platform !== 'darwin' || !fromMainWindow(event)) return
    const before = systemPreferences.getMediaAccessStatus('screen')
    if (before === 'granted') return
    if (before === 'restricted') {
      await shell.openExternal(SCREEN_SETTINGS)
      return
    }
    // Request a real thumbnail: window enumeration with zero-sized thumbnails
    // does not reliably trigger macOS consent. Never retain or send this image.
    // Try even when reported denied: an unregistered development app can report
    // denied before its first native request.
    try {
      await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 1, height: 1 } })
    } catch (error) {
      // A denied capture can reject before enumeration completes. Still provide
      // the system recovery page, instead of silently abandoning authorization.
      const current = systemPreferences.getMediaAccessStatus('screen')
      if (current === 'denied' || current === 'restricted') {
        await shell.openExternal(SCREEN_SETTINGS)
        return
      }
      throw error
    }
    // Let the first-use native dialog handle consent. Previously denied access
    // may require the user to change the existing switch in System Settings.
    if (before === 'denied' && systemPreferences.getMediaAccessStatus('screen') === 'denied') {
      await shell.openExternal(SCREEN_SETTINGS)
    }
  })
}
