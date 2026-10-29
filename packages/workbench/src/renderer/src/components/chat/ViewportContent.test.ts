// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { ViewportContent } from './ViewportContent'

it('mounts nearby content, releases distant content, and keeps streams mounted', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  let intersect: (entries: unknown[]) => void = () => {}
  let resize: (entries: unknown[]) => void = () => {}
  let frame: FrameRequestCallback = () => {}
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frame = callback; return 1 })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const disconnect = vi.fn()
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: typeof intersect) { intersect = callback }
    observe() {}
    disconnect = disconnect
  })
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: typeof resize) { resize = callback }
    observe() {}
    disconnect = disconnect
  })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(ViewportContent, { children: 'expensive markdown' })))
    expect(host.textContent).toBe('')
    await act(async () => intersect([{ isIntersecting: true }]))
    expect(host.textContent).toBe('')
    await act(async () => frame(0))
    expect(host.textContent).toBe('expensive markdown')
    resize([{ borderBoxSize: [{ blockSize: 600 }] }])
    await act(async () => intersect([{ isIntersecting: false }]))
    expect(host.textContent).toBe('')
    expect((host.firstChild as HTMLElement).style.height).toBe('600px')
    await act(async () => root.render(createElement(ViewportContent, { active: true, children: 'live' })))
    expect(host.textContent).toBe('live')
  } finally {
    await act(async () => root.unmount())
    vi.unstubAllGlobals()
  }
  expect(disconnect).toHaveBeenCalled()
})
