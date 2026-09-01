// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AppSettingsV1 } from '@shared/app-settings'
import { defaultAppearanceSettings } from '@shared/appearance'
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
