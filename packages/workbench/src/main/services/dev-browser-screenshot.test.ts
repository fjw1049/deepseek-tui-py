import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  captureDevBrowserScreenshotDataUrl, resolveDevBrowserGuestWebContents
} from './dev-browser-screenshot'

const electronMock = vi.hoisted(() => ({
  fromId: vi.fn(), createFromBuffer: vi.fn()
}))
vi.mock('electron', () => ({
  webContents: { fromId: electronMock.fromId },
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

  it('clears the timeout after capturing a screenshot', async () => {
    vi.useFakeTimers()
    electronMock.fromId.mockReturnValue({
      ...createGuest(),
      capturePage: vi.fn(async () => ({ isEmpty: () => false, getScaleFactors: () => [1], toPNG: () => Buffer.from('png') }))
    })
    expect((await captureDevBrowserScreenshotDataUrl(mainWindow, 42, 1)).ok).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('detaches its debugger on timeout', async () => {
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
    const pending = captureDevBrowserScreenshotDataUrl(mainWindow, 42, 1)
    await vi.advanceTimersByTimeAsync(12_000)
    expect(await pending).toEqual({ ok: false, message: 'Screenshot timed out.' })
    expect(debuggerSession.detach).toHaveBeenCalledOnce()
    finishCapture({ data: 'late' })
    await Promise.resolve()
  })
})

describe('captureDevBrowserScreenshotDataUrl', () => {
  it('returns a PNG data URL at the sharpest captured scale', async () => {
    const toPNG = vi.fn(() => Buffer.from('png'))
    electronMock.fromId.mockReturnValue({
      ...createGuest(),
      capturePage: vi.fn(async () => ({ isEmpty: () => false, getScaleFactors: () => [1, 2], toPNG }))
    })
    expect(await captureDevBrowserScreenshotDataUrl(mainWindow, 42, 1)).toEqual({
      ok: true, dataUrl: `data:image/png;base64,${Buffer.from('png').toString('base64')}`
    })
    expect(toPNG).toHaveBeenCalledWith({ scaleFactor: 2 })
  })

  it('refuses a guest owned by another window', async () => {
    electronMock.fromId.mockReturnValue(createGuest())
    expect(await captureDevBrowserScreenshotDataUrl(mainWindow, 42, 2)).toEqual({
      ok: false, message: 'Screenshot request came from an unexpected window.'
    })
  })
})
