import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
import { installMainWindowNavigationGuards, isAppDocumentUrl } from './main-window-guards'

function createContents(appUrl: string) {
  const contents = Object.assign(new EventEmitter(), { setWindowOpenHandler: vi.fn() })
  const openExternal = vi.fn()
  installMainWindowNavigationGuards(contents as unknown as Electron.WebContents, { appUrl, openExternal })
  const openHandler = contents.setWindowOpenHandler.mock.calls[0]![0] as (details: { url: string }) => { action: string }
  return { contents, openExternal, openHandler }
}

describe('main window navigation guards', () => {
  it('recognises the app document for dev servers and packaged files', () => {
    expect(isAppDocumentUrl('http://localhost:5173/#/settings', 'http://localhost:5173/')).toBe(true)
    expect(isAppDocumentUrl('http://localhost:5174/', 'http://localhost:5173/')).toBe(false)
    expect(isAppDocumentUrl('file:///app/out/renderer/index.html?x=1', 'file:///app/out/renderer/index.html')).toBe(true)
    expect(isAppDocumentUrl('file:///etc/passwd', 'file:///app/out/renderer/index.html')).toBe(false)
    expect(isAppDocumentUrl('not a url', 'file:///app/out/renderer/index.html')).toBe(false)
  })

  it('keeps the window on the app and hands web links to the OS browser', () => {
    const { contents, openExternal } = createContents('file:///app/out/renderer/index.html')
    const away = { preventDefault: vi.fn() }
    contents.emit('will-navigate', away, 'https://evil.example/')
    expect(away.preventDefault).toHaveBeenCalled()
    expect(openExternal).toHaveBeenCalledWith('https://evil.example/')

    const local = { preventDefault: vi.fn() }
    contents.emit('will-navigate', local, 'file:///Users/me/secret.html')
    expect(local.preventDefault).toHaveBeenCalled()
    expect(openExternal).toHaveBeenCalledTimes(1)

    const reload = { preventDefault: vi.fn() }
    contents.emit('will-navigate', reload, 'file:///app/out/renderer/index.html')
    expect(reload.preventDefault).not.toHaveBeenCalled()
  })

  it('blocks main-frame redirects off the app', () => {
    const { contents } = createContents('http://localhost:5173/')
    const redirect = { preventDefault: vi.fn() }
    contents.emit('will-redirect', redirect, 'https://evil.example/', false, true)
    expect(redirect.preventDefault).toHaveBeenCalled()
    const subframe = { preventDefault: vi.fn() }
    contents.emit('will-redirect', subframe, 'https://evil.example/', false, false)
    expect(subframe.preventDefault).not.toHaveBeenCalled()
  })

  it('denies new windows and opens web links externally', () => {
    const { openExternal, openHandler } = createContents('http://localhost:5173/')
    expect(openHandler({ url: 'https://docs.example/' })).toEqual({ action: 'deny' })
    expect(openHandler({ url: 'javascript:alert(1)' })).toEqual({ action: 'deny' })
    expect(openExternal.mock.calls).toEqual([['https://docs.example/']])
  })
})
