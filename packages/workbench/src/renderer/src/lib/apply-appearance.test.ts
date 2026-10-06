// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defaultAppearanceSettings, mergeAppearanceSettings } from '@shared/appearance'
import { applyAppearance, getWindowBlurUnavailable } from './apply-appearance'
import { applyTheme } from './apply-theme'

const setWindowMaterial = vi.fn(async () => true)
let dark = false
let onSystemChange: (() => void) | undefined

beforeEach(() => {
  setWindowMaterial.mockReset().mockResolvedValue(true)
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { platform: 'darwin', setWindowMaterial } })
  dark = false
  onSystemChange = undefined
  window.matchMedia = vi.fn(() => ({
    matches: dark,
    addEventListener: (_event: string, listener: () => void) => { onSystemChange = listener },
    removeEventListener: () => {}
  } as unknown as MediaQueryList))
  applyTheme('light')
  applyAppearance(defaultAppearanceSettings())
  setWindowMaterial.mockClear()
})

afterEach(() => {
  applyTheme('light')
  applyAppearance(defaultAppearanceSettings())
})

describe('native window material synchronization', () => {
  it('updates the active slot, ignores inactive edits, and follows automatic system theme changes', async () => {
    const appearance = mergeAppearanceSettings(defaultAppearanceSettings(), {
      themes: { light: { translucent: true } },
      translucency: { light: { blur: 10 }, dark: { blur: 40 } }
    })
    applyTheme('system')
    applyAppearance(appearance)
    await Promise.resolve()
    expect(setWindowMaterial).toHaveBeenLastCalledWith({ material: 'translucent', blurRadius: 10 })
    setWindowMaterial.mockClear()
    applyAppearance(mergeAppearanceSettings(appearance, { translucency: { dark: { blur: 55 } } }))
    expect(setWindowMaterial).not.toHaveBeenCalled()
    dark = true
    onSystemChange?.()
    await Promise.resolve()
    expect(setWindowMaterial).toHaveBeenLastCalledWith({ material: 'translucent', blurRadius: 55 })
  })

  it('restores Auto on opaque themes and does not call native APIs on other platforms', async () => {
    applyTheme('dark')
    const appearance = mergeAppearanceSettings(defaultAppearanceSettings(), { translucency: { dark: { blur: 64 } } })
    applyAppearance(appearance)
    applyAppearance(mergeAppearanceSettings(appearance, { themes: { dark: { translucent: false } } }))
    expect(setWindowMaterial).toHaveBeenLastCalledWith({ material: 'opaque', blurRadius: 0 })
    Object.defineProperty(window, 'dsGui', { configurable: true, value: { platform: 'win32', setWindowMaterial } })
    setWindowMaterial.mockClear()
    applyAppearance(appearance)
    expect(setWindowMaterial).not.toHaveBeenCalled()
    await Promise.resolve()
  })

  it('reports unavailable manual blur and clears the notice when choosing Auto', async () => {
    setWindowMaterial.mockResolvedValue(false)
    applyTheme('dark')
    const appearance = mergeAppearanceSettings(defaultAppearanceSettings(), { translucency: { dark: { blur: 30 } } })
    applyAppearance(appearance)
    await Promise.resolve()
    expect(getWindowBlurUnavailable()).toBe(true)
    applyAppearance(mergeAppearanceSettings(appearance, { translucency: { dark: { blur: null } } }))
    await Promise.resolve()
    expect(getWindowBlurUnavailable()).toBe(false)
  })

  it('ignores stale results when rapid edits revisit the same blur radius', async () => {
    const results: Array<(value: boolean) => void> = []
    setWindowMaterial.mockImplementation(() => new Promise<boolean>((resolve) => results.push(resolve)))
    applyTheme('dark')
    const base = defaultAppearanceSettings()
    applyAppearance(mergeAppearanceSettings(base, { translucency: { dark: { blur: 12 } } }))
    applyAppearance(mergeAppearanceSettings(base, { translucency: { dark: { blur: 30 } } }))
    applyAppearance(mergeAppearanceSettings(base, { translucency: { dark: { blur: 12 } } }))
    results.at(-1)?.(true)
    await Promise.resolve()
    results[0]?.(false)
    await Promise.resolve()
    expect(getWindowBlurUnavailable()).toBe(false)
  })
})
