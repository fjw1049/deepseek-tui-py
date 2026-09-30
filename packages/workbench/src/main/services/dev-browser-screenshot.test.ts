import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { copyDevBrowserScreenshotToClipboard, resolveDevBrowserGuestWebContents } from './dev-browser-screenshot'

const electronMock = vi.hoisted(() => ({
  fromId: vi.fn(), writeImage: vi.fn(), createFromBuffer: vi.fn()
}))
vi.mock('electron', () => ({
  webContents: { fromId: electronMock.fromId },
  clipboard: { writeImage: electronMock.writeImage },
  nativeImage: { createFromBuffer: electronMock.createFromBuffer }
}))

const mainWindow = { isDestroyed: () => false, webContents: { id: 1 } } as never
function createGuest(): Record<string, unknown> {
  return {
    id: 42, isDestroyed: () => false, getType: () => 'webview',
    hostWebContents: { id: 1, isDestroyed: () => false },
    capturePage: vi.fn(async () => ({ isEmpty: () => false }))
  }
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.useRealTimers())

describe('resolveDevBrowserGuestWebContents', () => {
  it('rejects missing main window', () => {
    expect(resolveDevBrowserGuestWebContents(null, 42)).toEqual({
      ok: false,
      message: 'Main window unavailable.'
    })
  })

  it('rejects destroyed main window', () => {
    const mainWindow = {
      isDestroyed: () => true,
      webContents: { id: 1 }
    } as never

    expect(resolveDevBrowserGuestWebContents(mainWindow, 42)).toEqual({
      ok: false,
      message: 'Main window unavailable.'
    })
  })

  it('rejects unrelated WebContents even when the sender is the main window', () => {
    electronMock.fromId.mockReturnValue({ ...createGuest(), getType: () => 'window' })
    expect(resolveDevBrowserGuestWebContents(mainWindow, 42, 1).ok).toBe(false)
    electronMock.fromId.mockReturnValue({ ...createGuest(), hostWebContents: undefined })
    expect(resolveDevBrowserGuestWebContents(mainWindow, 42, 1).ok).toBe(false)
  })

  it('only captures a live guest attached to the requesting window', () => {
    const guest = createGuest()
    electronMock.fromId.mockReturnValue(guest)
    expect(resolveDevBrowserGuestWebContents(mainWindow, 42, 1)).toEqual({ ok: true, guest })
    expect(resolveDevBrowserGuestWebContents(mainWindow, 42, 2).ok).toBe(false)
    electronMock.fromId.mockReturnValue({ ...guest, hostWebContents: { id: 2, isDestroyed: () => false } })
    expect(resolveDevBrowserGuestWebContents(mainWindow, 42, 1).ok).toBe(false)
  })

  it('clears the timeout after copying a screenshot', async () => {
    vi.useFakeTimers()
    electronMock.fromId.mockReturnValue(createGuest())
    expect(await copyDevBrowserScreenshotToClipboard(mainWindow, 42, 1)).toEqual({ ok: true })
    expect(electronMock.writeImage).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('detaches its debugger on timeout and does not copy late results', async () => {
    vi.useFakeTimers()
    let attached = false
    let finishCapture!: (value: { data: string }) => void
    const debuggerSession = {
      isAttached: () => attached,
      attach: vi.fn(() => { attached = true }),
      detach: vi.fn(() => { attached = false }),
      sendCommand: vi.fn(() => new Promise((resolve) => { finishCapture = resolve }))
    }
    electronMock.fromId.mockReturnValue({
      ...createGuest(), debugger: debuggerSession,
      capturePage: vi.fn(async () => ({ isEmpty: () => true }))
    })
    const pending = copyDevBrowserScreenshotToClipboard(mainWindow, 42, 1)
    await vi.advanceTimersByTimeAsync(12_000)
    expect(await pending).toEqual({ ok: false, message: 'Screenshot timed out.' })
    expect(debuggerSession.detach).toHaveBeenCalledOnce()
    finishCapture({ data: 'late' })
    await Promise.resolve()
    expect(electronMock.writeImage).not.toHaveBeenCalled()
  })
})
