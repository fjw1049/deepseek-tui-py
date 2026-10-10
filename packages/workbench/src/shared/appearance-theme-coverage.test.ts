import { describe, expect, it } from 'vitest'
import { defaultAppearanceSettings, getThemePresetSeed, listThemePresetsForVariant } from './appearance'
import { buildChromeThemeCssVars } from './appearance-derive'

describe('theme catalog coverage', () => {
  it('includes the remaining Synara presets only in their supported modes', () => {
    const missing = {
      absolutely: ['light', 'dark'], ayu: ['dark'], synara: ['light', 'dark'],
      lobster: ['dark'], material: ['dark'], 'night-owl': ['dark'],
      oscurange: ['dark'], proof: ['light'], sentry: ['dark'], temple: ['dark']
    }
    for (const [id, variants] of Object.entries(missing)) {
      for (const variant of ['light', 'dark'] as const) {
        expect(listThemePresetsForVariant(variant).some((preset) => preset.id === id), `${id}/${variant}`)
          .toBe(variants.includes(variant))
      }
    }
  })
})

describe('theme control coverage', () => {
  it.each(['light', 'dark'] as const)('adjusts %s controls, cards and interaction states with contrast', (variant) => {
    const theme = defaultAppearanceSettings().themes[variant]
    const low = buildChromeThemeCssVars({ ...theme, contrast: 0 }, variant)
    const high = buildChromeThemeCssVars({ ...theme, contrast: 100 }, variant)
    for (const token of ['--ds-material-control', '--ds-material-card', '--ds-material-card-hover', '--ds-surface-hover']) {
      expect(low[token], token).not.toBe(high[token])
    }
    expect(high['--ds-material-control']).not.toBe(high['--bg-canvas'])
  })

  it.each(['light', 'dark'] as const)('tracks custom %s semantic and accent colors on secondary surfaces', (variant) => {
    const seed = getThemePresetSeed('codex', variant)!
    const palette = buildChromeThemeCssVars(seed, variant)
    const edited = buildChromeThemeCssVars({ ...seed, accent: '#cc7733', ink: variant === 'light' ? '#223344' : '#ddeeff' }, variant)
    expect(edited['--ds-diff-hunk']).toBe(edited['--ds-accent'])
    expect(edited['--ds-diff-hunk']).not.toBe(palette['--ds-diff-hunk'])
    expect(edited['--ds-icon-muted']).not.toBe(palette['--ds-icon-muted'])
    expect(edited['--ds-warning']).toMatch(/^#[0-9a-f]{6}$/)
    expect(edited['--ds-warning-soft']).toMatch(/^rgba/)
  })
})
