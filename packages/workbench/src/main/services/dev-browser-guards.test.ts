import { EventEmitter } from 'node:events'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installDevPreviewWebviewGuards } from './dev-browser-guards'

const mocks = vi.hoisted(() => ({
  on: vi.fn(), logWarn: vi.fn(),
  setPermissionCheckHandler: vi.fn(), setPermissionRequestHandler: vi.fn()
}))
vi.mock('electron', () => ({
  app: { on: mocks.on },
  session: { fromPartition: () => mocks }
}))
vi.mock('../logger', () => ({ logWarn: mocks.logWarn }))

function createContents(type = 'webview') {
  const contents = Object.assign(new EventEmitter(), {
    getType: () => type,
    loadURL: vi.fn(async (_url: string) => {}),
    setWindowOpenHandler: vi.fn()
  })
  const created = mocks.on.mock.calls[0]![1] as (
    event: unknown, contents: Electron.WebContents
  ) => void
  created({}, contents as unknown as Electron.WebContents)
  return contents
}

describe('dev browser guards', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    installDevPreviewWebviewGuards()
  })

  it('denies privileged web permissions in both permission handlers', () => {
    const check = mocks.setPermissionCheckHandler.mock.calls[0]![0] as (
      contents: unknown, permission: string
    ) => boolean
    const request = mocks.setPermissionRequestHandler.mock.calls[0]![0] as (
      contents: unknown, permission: string, callback: (allowed: boolean) => void
    ) => void
    for (const permission of ['media', 'geolocation', 'clipboard-read', 'notifications', 'openExternal']) {
      expect(check(null, permission)).toBe(false)
      const callback = vi.fn()
      request(null, permission, callback)
      expect(callback).toHaveBeenCalledWith(false)
    }
    expect(check(null, 'fullscreen')).toBe(true)
    expect(check(null, 'clipboard-sanitized-write')).toBe(true)
  })

  it('strips preload and forces isolated guest preferences', () => {
    const contents = createContents('window')
    const event = { preventDefault: vi.fn() }
    const preferences = {
      preload: '/evil.js', preloadURL: 'file:///evil.js', nodeIntegration: true,
      nodeIntegrationInSubFrames: true, nodeIntegrationInWorker: true, webviewTag: true
    }
    contents.emit('will-attach-webview', event, preferences, {
      src: 'https://example.com/', partition: 'persist:deepseek-dev-browser'
    })
    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(preferences).toEqual({
      nodeIntegration: false, nodeIntegrationInSubFrames: false, nodeIntegrationInWorker: false,
      webviewTag: false, contextIsolation: true, sandbox: true, webSecurity: true,
      allowRunningInsecureContent: false
    })
  })

  it('attaches blank tabs that agent-opened pages start from', () => {
    const contents = createContents('window')
    const event = { preventDefault: vi.fn() }
    contents.emit('will-attach-webview', event, {}, { src: 'about:blank', partition: 'persist:deepseek-dev-browser' })
    expect(event.preventDefault).not.toHaveBeenCalled()
  })

  it('rejects unsupported guest URLs and other session partitions', () => {
    const contents = createContents('window')
    for (const params of [
      { src: 'file:///tmp/a.html', partition: 'persist:deepseek-dev-browser' },
      { src: 'https://example.com/', partition: 'persist:untrusted' }
    ]) {
      const event = { preventDefault: vi.fn() }
      contents.emit('will-attach-webview', event, {}, params)
      expect(event.preventDefault).toHaveBeenCalledOnce()
    }
  })

  it('applies the same policy to main-frame navigation and redirects', () => {
    const contents = createContents()
    for (const name of ['will-navigate', 'will-redirect']) {
      const blocked = { preventDefault: vi.fn() }
      contents.emit(name, blocked, 'file:///etc/passwd', false, true)
      expect(blocked.preventDefault).toHaveBeenCalledOnce()
      // Public http is never loaded in cleartext; the same page is tried over https instead.
      const upgraded = { preventDefault: vi.fn() }
      contents.emit(name, upgraded, 'http://public.example/', false, true)
      expect(upgraded.preventDefault).toHaveBeenCalledOnce()
      expect(contents.loadURL).toHaveBeenLastCalledWith('https://public.example/')
      const allowed = { preventDefault: vi.fn() }
      contents.emit(name, allowed, 'http://localhost:5173/', false, true)
      expect(allowed.preventDefault).not.toHaveBeenCalled()
    }
    const subframe = { preventDefault: vi.fn() }
    contents.emit('will-redirect', subframe, 'about:blank', false, false)
    expect(subframe.preventDefault).not.toHaveBeenCalled()
  })

  it('opens safe child windows without navigating the draft page', () => {
    const contents = createContents()
    const open = contents.setWindowOpenHandler.mock.calls[0]![0]
    for (const url of ['https://example.com/', 'about:blank']) {
      expect(open({ url })).toMatchObject({ action: 'allow', overrideBrowserWindowOptions: {
        webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webviewTag: false }
      } })
    }
    expect(open({ url: 'javascript:123' })).toEqual({ action: 'deny' })
    expect(contents.loadURL).not.toHaveBeenCalled()
  })

  it('loads new-tab links in the current tab instead of opening a window', () => {
    const contents = createContents()
    const open = contents.setWindowOpenHandler.mock.calls[0]![0]
    for (const disposition of ['foreground-tab', 'background-tab']) {
      expect(open({ url: 'https://example.com/result', disposition })).toEqual({ action: 'deny' })
    }
    expect(contents.loadURL).toHaveBeenCalledTimes(2)
    expect(contents.loadURL).toHaveBeenCalledWith('https://example.com/result')
    // Sized popups (sign-in windows) keep their opener; blank tabs are written to by their opener.
    expect(open({ url: 'https://example.com/login', disposition: 'new-window' })).toMatchObject({ action: 'allow' })
    expect(open({ url: 'about:blank', disposition: 'foreground-tab' })).toMatchObject({ action: 'allow' })
    expect(contents.loadURL).toHaveBeenCalledTimes(2)
    // Search engines link results through http redirectors; those open over https too.
    expect(open({ url: 'http://www.baidu.com/link?url=abc', disposition: 'foreground-tab' })).toEqual({ action: 'deny' })
    expect(contents.loadURL).toHaveBeenLastCalledWith('https://www.baidu.com/link?url=abc')
  })
})
