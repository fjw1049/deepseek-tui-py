// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AppSettingsV1 } from '@shared/app-settings'
import { defaultAppearanceSettings, mergeAppearanceSettings } from '@shared/appearance'
import { AppearanceSettingsPanel } from './AppearanceSettingsPanel'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key })
}))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

class FakeResizeObserver implements ResizeObserver {
  constructor(_callback: ResizeObserverCallback) {}
  disconnect(): void {}
  observe(): void {}
  unobserve(): void {}
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { platform: 'darwin' } })
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn()
  })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('AppearanceSettingsPanel', () => {
  it('reveals blur and opacity only for translucent macOS theme slots', async () => {
    const form = { theme: 'dark', appearance: defaultAppearanceSettings() } as AppSettingsV1
    await act(async () => root.render(createElement(AppearanceSettingsPanel, { form, onPatch: vi.fn() })))
    expect(container.querySelector('input[aria-label="themePackDarkTitle · themeBlur"]')).not.toBeNull()
    expect(container.querySelector('input[aria-label="themePackLightTitle · themeBlur"]')).toBeNull()
    Object.defineProperty(window, 'dsGui', { configurable: true, value: { platform: 'win32' } })
    await act(async () => root.render(createElement(AppearanceSettingsPanel, { form, onPatch: vi.fn() })))
    expect(container.querySelector('input[aria-label$=" · themeBlur"]')).toBeNull()
    expect((container.querySelector('[aria-label="themePackDarkTitle · themeTranslucent"]') as HTMLButtonElement).disabled).toBe(true)
  })

  it('returns manual blur to Auto and resets window preferences with the theme', async () => {
    const onPatch = vi.fn()
    const form = { theme: 'dark', appearance: mergeAppearanceSettings(defaultAppearanceSettings(), {
      translucency: { dark: { blur: 25, opacity: 55 } }
    }) } as AppSettingsV1
    await act(async () => root.render(createElement(AppearanceSettingsPanel, { form, onPatch })))
    const auto = container.querySelector('[aria-label="themePackDarkTitle · themeBlurAuto"]') as HTMLButtonElement
    await act(async () => auto.click())
    expect(onPatch).toHaveBeenLastCalledWith({ appearance: { translucency: { dark: { blur: null } } } })
    const reset = container.querySelector('[aria-label="themePackDarkTitle · themePackReset"]') as HTMLButtonElement
    await act(async () => reset.click())
    expect(onPatch.mock.lastCall?.[0].appearance.translucency.dark).toEqual({ opacity: 74, blur: null })
  })

  it('previews slider edits through separate per-variant appearance patches', async () => {
    const onPatch = vi.fn()
    const form = { theme: 'dark', appearance: defaultAppearanceSettings() } as AppSettingsV1
    await act(async () => root.render(createElement(AppearanceSettingsPanel, { form, onPatch })))
    for (const [key, value, field] of [['themeBlur', '24', 'blur'], ['themeOpacity', '55', 'opacity']]) {
      const input = container.querySelector(`input[aria-label="themePackDarkTitle · ${key}"]`) as HTMLInputElement
      await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
      })
      expect(onPatch).toHaveBeenLastCalledWith({ appearance: { translucency: { dark: { [field]: Number(value) } } } })
    }
  })

  it('requires confirmation before resetting every appearance setting', async () => {
    const onPatch = vi.fn()
    const form = {
      theme: 'light',
      uiFontScale: 'medium',
      uiFontFamily: 'system-native',
      appearance: defaultAppearanceSettings()
    } as AppSettingsV1

    await act(async () => {
      root.render(createElement(AppearanceSettingsPanel, { form, onPatch }))
    })

    const reset = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('appearanceRestoreDefaults')
    )!
    await act(async () => reset.click())
    expect(onPatch).not.toHaveBeenCalled()
    expect(reset.textContent).toContain('appearanceRestoreConfirm')

    await act(async () => reset.click())
    expect(onPatch).toHaveBeenCalledOnce()
    expect(onPatch).toHaveBeenCalledWith({
      theme: 'dark',
      uiFontScale: 'medium',
      uiFontFamily: 'system-native',
      appearance: defaultAppearanceSettings()
    })
  })
})
