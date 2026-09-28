// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { HoverMarqueeText } from './HoverMarqueeText'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const originalAnimate = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'animate')

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  if (originalAnimate) Object.defineProperty(HTMLElement.prototype, 'animate', originalAnimate)
  else Reflect.deleteProperty(HTMLElement.prototype, 'animate')
  document.body.innerHTML = ''
})

it('fades overflowing text and scrolls it after hover dwell', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('ResizeObserver', class {
    observe(): void {}
    disconnect(): void {}
  })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(100)
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(200)
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({ transform: 'none' } as CSSStyleDeclaration)
  const animation = { cancel: vi.fn(), onfinish: null }
  const animate = vi.fn().mockReturnValue(animation)
  Object.defineProperty(HTMLElement.prototype, 'animate', { configurable: true, value: animate })

  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(createElement(HoverMarqueeText, {
    className: 'min-w-0 flex-1', text: 'A long title', title: 'A long title'
  })))
  const viewport = container.querySelector('span')!
  expect(viewport.classList.contains('ds-sidebar-title-fade')).toBe(true)

  await act(async () => viewport.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })))
  await act(async () => vi.advanceTimersByTimeAsync(350))
  expect(animate).toHaveBeenCalledWith(
    [{ transform: 'translateX(0)' }, { transform: 'translateX(-100px)' }],
    { duration: 100 / 42 * 1000, easing: 'linear', fill: 'forwards' }
  )
  expect(viewport.classList.contains('ds-sidebar-title-fade')).toBe(false)

  await act(async () => viewport.dispatchEvent(new MouseEvent('mouseout', { bubbles: true })))
  expect(viewport.classList.contains('ds-sidebar-title-fade')).toBe(true)
  await act(async () => root.unmount())
})
