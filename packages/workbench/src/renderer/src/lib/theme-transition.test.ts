// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { transitionTheme } from './theme-transition'

const original = Object.getOwnPropertyDescriptor(document, 'startViewTransition')
afterEach(() => {
  if (original) Object.defineProperty(document, 'startViewTransition', original)
  else Reflect.deleteProperty(document, 'startViewTransition')
  vi.restoreAllMocks()
  document.documentElement.removeAttribute('data-theme')
})

it('reveals from the supplied origin and cleans up after the transition', async () => {
  let finish!: () => void
  const finished = new Promise<void>((resolve) => { finish = resolve })
  const start = vi.fn((update: () => void) => {
    update()
    return { ready: Promise.resolve(), finished }
  })
  Object.defineProperty(document, 'startViewTransition', { configurable: true, value: start })
  const pending = transitionTheme('dark', { x: 24, y: 80 })
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(document.documentElement.classList.contains('ds-theme-transition')).toBe(true)
  expect(document.head.textContent).toContain('mask-position: 24px 80px')
  await transitionTheme('light', { x: 0, y: 0 })
  expect(start).toHaveBeenCalledTimes(1)
  finish()
  await pending
  expect(document.documentElement.classList.contains('ds-theme-transition')).toBe(false)
  expect(document.head.textContent).not.toContain('@keyframes ds-theme-reveal')
})

it('applies immediately when reduced motion is requested', async () => {
  const start = vi.fn()
  Object.defineProperty(document, 'startViewTransition', { configurable: true, value: start })
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
  await transitionTheme('light', { x: 0, y: 0 })
  expect(start).not.toHaveBeenCalled()
  expect(document.documentElement.dataset.theme).toBe('light')
})

it('still applies the theme and removes styles when capture fails', async () => {
  Object.defineProperty(document, 'startViewTransition', { configurable: true, value: () => { throw new Error('capture unavailable') } })
  await transitionTheme('dark', { x: 0, y: 0 })
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(document.documentElement.classList.contains('ds-theme-transition')).toBe(false)
  expect(document.head.textContent).not.toContain('@keyframes ds-theme-reveal')
})
