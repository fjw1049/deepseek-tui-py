// @vitest-environment happy-dom
/**
 * Component-level regression tests for DevBrowserPanel. Render the real
 * component (StrictMode, like the app) with a mocked dsGui bridge and fake
 * webview events, guarding against:
 * - "Maximum update depth exceeded" setState-in-effect cascades
 * - the allowpopups attribute being dropped by React (target=_blank breakage)
 * - auto-follow opening duplicate tabs after a redirect
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, StrictMode, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { DevBrowserPanel } from './DevBrowserPanel'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

function installDsGuiMock(): void {
  const w = window as unknown as { dsGui: unknown }
  w.dsGui = {
    openExternal: vi.fn(async () => {}),
    onDevBrowserOpenUrl: vi.fn(() => () => {})
  }
}

function lastWebview(): HTMLElement {
  const views = document.querySelectorAll('webview')
  return views[views.length - 1] as HTMLElement
}

function fire(view: HTMLElement, type: string, props: Record<string, unknown> = {}): void {
  const event = Object.assign(new Event(type), props)
  view.dispatchEvent(event)
}

describe('DevBrowserPanel', () => {
  beforeEach(() => {
    installDsGuiMock()
    document.body.innerHTML = ''
  })

  it('mounts with preferredUrl without update-depth loop', async () => {
    const errors: string[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      errors.push(args.map(String).join(' '))
    })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root: Root = createRoot(container)

    await act(async () => {
      root.render(
        createElement(
          StrictMode,
          null,
          createElement(DevBrowserPanel, {
            blocks: [],
            preferredUrl: 'http://127.0.0.1:5173/',
            onPreferredUrlConsumed: () => {}
          })
        )
      )
    })

    const view = lastWebview()
    expect(view).toBeTruthy()
    // The allowpopups attribute must actually reach the DOM (React 19 drops
    // boolean attributes on non-standard elements with a warning).
    expect(view.getAttribute('allowpopups')).toBe('true')

    // Simulate a realistic load sequence from Electron.
    await act(async () => {
      fire(view, 'did-start-loading')
    })
    await act(async () => {
      fire(view, 'did-navigate', { url: 'http://127.0.0.1:5173/' })
    })
    await act(async () => {
      fire(view, 'page-title-updated', { title: 'Vite App' })
    })
    await act(async () => {
      fire(view, 'did-stop-loading')
    })
    // In-page SPA navigation.
    await act(async () => {
      fire(view, 'did-navigate-in-page', { url: 'http://127.0.0.1:5173/docs' })
    })
    await act(async () => {
      fire(view, 'did-stop-loading')
    })

    const depthErrors = errors.filter((e) => e.includes('Maximum update depth'))
    if (errors.length) console.log('captured errors:', errors.slice(0, 5))
    expect(depthErrors).toEqual([])
    await act(async () => root.unmount())
    spy.mockRestore()
  })

  it('autoFollow + redirecting page does not loop', async () => {
    const store = new Map<string, string>([['deepseekgui.devPreview.autoFollow', 'true']])
    const fakeStorage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v)
    }
    Object.defineProperty(window, 'localStorage', { value: fakeStorage, configurable: true })
    const errors: string[] = []
    const spy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      errors.push(args.map(String).join(' '))
    })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root: Root = createRoot(container)

    const blocks = [
      {
        kind: 'assistant',
        id: 'a1',
        text: 'dev server ready\nLocal: http://localhost:5173/'
      }
    ] as never

    await act(async () => {
      root.render(createElement(StrictMode, null, createElement(DevBrowserPanel, { blocks })))
    })

    const view = lastWebview()
    // The page redirects: Electron reports the FINAL url via did-navigate.
    await act(async () => {
      fire(view, 'did-start-loading')
      fire(view, 'did-navigate', { url: 'http://localhost:5173/login' })
      fire(view, 'did-stop-loading')
    })

    const depthErrors = errors.filter((e) => e.includes('Maximum update depth'))
    // The redirect must NOT make auto-follow open a duplicate background tab
    // (previously the tabs.some(url) guard broke after navigation away).
    expect(document.querySelectorAll('webview')).toHaveLength(1)
    expect(depthErrors).toEqual([])
    await act(async () => root.unmount())
    spy.mockRestore()
  })
})
