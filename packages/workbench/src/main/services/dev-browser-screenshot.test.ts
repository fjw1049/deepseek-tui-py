import { describe, expect, it } from 'vitest'
import { resolveDevBrowserGuestWebContents } from './dev-browser-screenshot'

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
})
