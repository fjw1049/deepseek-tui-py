// @vitest-environment happy-dom
import * as monaco from 'monaco-editor'
import { afterEach, expect, it, vi } from 'vitest'
import { defaultAppearanceSettings, getThemePresetSeed, mergeAppearanceSettings } from '@shared/appearance'
import { buildChromeThemeCssVars } from '@shared/appearance-derive'
import { applyAppearance } from './apply-appearance'
import { ensureWorkspaceMonacoThemes } from './monaco-editor-setup'

afterEach(() => {
  applyAppearance(defaultAppearanceSettings())
  vi.restoreAllMocks()
})

it('refreshes editor chrome for custom palettes without a light/dark mode change', () => {
  applyAppearance(defaultAppearanceSettings())
  ensureWorkspaceMonacoThemes()
  const define = vi.spyOn(monaco.editor, 'defineTheme')
  const light = getThemePresetSeed('proof', 'light')!
  const dark = getThemePresetSeed('temple', 'dark')!
  applyAppearance(mergeAppearanceSettings(defaultAppearanceSettings(), { themes: { light, dark } }))
  ensureWorkspaceMonacoThemes()

  expect(define).toHaveBeenCalledTimes(4)
  for (const [name, definition] of define.mock.calls) {
    const variant = name.endsWith('dark') ? 'dark' : 'light'
    const theme = variant === 'dark' ? dark : light
    const vars = buildChromeThemeCssVars(theme, variant)
    const background = vars[name.includes('-ide-') ? '--bg-canvas' : '--bg-sidebar']
    expect(definition.colors['editor.background']).toBe(background)
    expect(definition.colors['minimap.background']).toBe(background)
    expect(definition.colors['editor.selectionBackground']).toContain(vars['--ds-accent'])
    expect(definition.colors['editorGutter.addedBackground']).toBe(theme.semanticColors.diffAdded)
    expect(definition.rules.find((rule) => rule.token === '')?.foreground).toBe(theme.ink.slice(1))
  }
  ensureWorkspaceMonacoThemes()
  expect(define).toHaveBeenCalledTimes(4)
})
