// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { applyTheme } from '../../lib/apply-theme'
import { ThemeToggle } from './ThemeToggle'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root
const setSettings = vi.fn()

beforeEach(() => {
  setSettings.mockReset().mockImplementation(async (patch) => patch)
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { setSettings } })
  applyTheme('dark')
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  applyTheme('light')
})

it('saves and applies alternating themes with the matching icon and accessible label', async () => {
  await act(async () => root.render(createElement(ThemeToggle)))
  const button = container.querySelector('button')!
  expect(button.querySelector('.lucide-sun')).not.toBeNull()
  expect(button.getAttribute('aria-label')).toBe('themeToggleToLight')
  await act(async () => button.click())
  expect(setSettings).toHaveBeenLastCalledWith({ theme: 'light' })
  expect(document.documentElement.dataset.theme).toBe('light')
  expect(button.querySelector('.lucide-moon')).not.toBeNull()
  expect(button.title).toBe('themeToggleToDark')
  await act(async () => button.click())
  expect(setSettings).toHaveBeenLastCalledWith({ theme: 'dark' })
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(button.querySelector('.lucide-sun')).not.toBeNull()
})

it('follows the resolved system theme and switches to an explicit preference on click', async () => {
  let systemDark = false
  let onChange: (() => void) | undefined
  vi.spyOn(window, 'matchMedia').mockImplementation(() => ({
    matches: systemDark,
    addEventListener: (_event: string, listener: () => void) => { onChange = listener },
    removeEventListener: () => {}
  } as unknown as MediaQueryList))
  applyTheme('system')
  await act(async () => root.render(createElement(ThemeToggle)))
  const button = container.querySelector('button')!
  expect(button.querySelector('.lucide-moon')).not.toBeNull()
  await act(async () => { systemDark = true; onChange?.() })
  expect(button.querySelector('.lucide-sun')).not.toBeNull()
  await act(async () => button.click())
  expect(setSettings).toHaveBeenLastCalledWith({ theme: 'light' })
  vi.restoreAllMocks()
})

it('blocks repeat clicks while saving and preserves the theme if saving fails', async () => {
  let reject!: (error: Error) => void
  setSettings.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
  await act(async () => root.render(createElement(ThemeToggle)))
  const button = container.querySelector('button')!
  await act(async () => button.click())
  expect(button.disabled).toBe(true)
  await act(async () => button.click())
  expect(setSettings).toHaveBeenCalledTimes(1)
  await act(async () => reject(new Error('save failed')))
  expect(button.disabled).toBe(false)
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(button.querySelector('.lucide-sun')).not.toBeNull()
})
