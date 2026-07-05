import { describe, expect, it } from 'vitest'
import {
  DEFAULT_CHROME_THEMES,
  createThemeShareString,
  defaultAppearanceSettings,
  getThemePresetSeed,
  isDefaultChromeTheme,
  listThemePresetsForVariant,
  mergeAppearanceSettings,
  normalizeAppearanceSettings,
  normalizeHexColor,
  parseThemeShareString
} from './appearance'
import { buildAppearanceOverrideCss, buildChromeThemeCssVars } from './appearance-derive'

describe('normalizeAppearanceSettings', () => {
  it('produces safe defaults from undefined input', () => {
    const settings = normalizeAppearanceSettings(undefined)
    expect(settings).toEqual(defaultAppearanceSettings())
    expect(isDefaultChromeTheme(settings.themes.light, 'light')).toBe(true)
    expect(isDefaultChromeTheme(settings.themes.dark, 'dark')).toBe(true)
  })

  it('clamps sizes and contrast, rejects invalid colors', () => {
    const settings = normalizeAppearanceSettings({
      chatFontSizePx: 99,
      terminalFontSizePx: 1,
      themes: {
        light: { accent: 'not-a-color', contrast: 400 },
        dark: { surface: '#0a0A0A' }
      }
    })
    expect(settings.chatFontSizePx).toBe(20)
    expect(settings.terminalFontSizePx).toBe(10)
    expect(settings.themes.light.accent).toBe(DEFAULT_CHROME_THEMES.light.accent)
    expect(settings.themes.light.contrast).toBe(100)
    expect(settings.themes.dark.surface).toBe('#0a0a0a')
  })

  it('merges variant patches without dropping the sibling variant', () => {
    const base = defaultAppearanceSettings()
    const merged = mergeAppearanceSettings(base, { themes: { dark: { accent: '#ff0000' } } })
    expect(merged.themes.dark.accent).toBe('#ff0000')
    expect(merged.themes.light).toEqual(base.themes.light)
  })
})

describe('normalizeHexColor', () => {
  it('accepts 6-digit hex and expands shorthand', () => {
    expect(normalizeHexColor('#A1B2C3', '')).toBe('#a1b2c3')
    expect(normalizeHexColor('#abc', '')).toBe('#aabbcc')
    expect(normalizeHexColor('blue', '#111111')).toBe('#111111')
  })
})

describe('theme presets', () => {
  it('every preset seed variant normalizes cleanly', () => {
    for (const variant of ['light', 'dark'] as const) {
      for (const preset of listThemePresetsForVariant(variant)) {
        const seed = getThemePresetSeed(preset.id, variant)
        expect(seed).not.toBeNull()
        expect(seed!.presetId).toBe(preset.id)
        expect(seed!.accent).toMatch(/^#[0-9a-f]{6}$/)
        expect(seed!.surface).toMatch(/^#[0-9a-f]{6}$/)
        expect(seed!.ink).toMatch(/^#[0-9a-f]{6}$/)
      }
    }
  })

  it('the default preset matches the built-in chrome themes', () => {
    expect(getThemePresetSeed('default', 'light')).toEqual(DEFAULT_CHROME_THEMES.light)
    expect(getThemePresetSeed('default', 'dark')).toEqual(DEFAULT_CHROME_THEMES.dark)
  })
})

describe('theme share strings', () => {
  it('round-trips through create/parse', () => {
    const theme = getThemePresetSeed('codex', 'dark')!
    const share = createThemeShareString('dark', theme)
    expect(share.startsWith('codex-theme-v1:')).toBe(true)
    const parsed = parseThemeShareString(share, 'dark')
    expect(parsed).toEqual({ ok: true, variant: 'dark', theme })
  })

  it('rejects the wrong variant and garbage input', () => {
    const share = createThemeShareString('light', getThemePresetSeed('codex', 'light')!)
    expect(parseThemeShareString(share, 'dark')).toEqual({ ok: false, error: 'variant-mismatch' })
    expect(parseThemeShareString('nonsense', 'dark')).toEqual({ ok: false, error: 'format' })
  })

  it('imports synara/codex-web share packs (opaqueWindows mapping)', () => {
    const raw =
      'codex-theme-v1:' +
      JSON.stringify({
        codeThemeId: 'vercel',
        variant: 'dark',
        theme: {
          accent: '#006efe',
          surface: '#000000',
          ink: '#ededed',
          contrast: 50,
          opaqueWindows: true,
          fonts: { ui: 'Geist, Inter', code: null },
          semanticColors: { diffAdded: '#00ad3a', diffRemoved: '#f13342', skill: '#9540d5' }
        }
      })
    const parsed = parseThemeShareString(raw, 'dark')
    expect(parsed.ok).toBe(true)
    if (parsed.ok) {
      expect(parsed.theme.translucent).toBe(false)
      expect(parsed.theme.uiFont).toBe('Geist, Inter')
      expect(parsed.theme.presetId).toBe('vercel')
    }
  })
})

describe('appearance-derive', () => {
  it('emits no override CSS for default settings (zero regression)', () => {
    expect(buildAppearanceOverrideCss(defaultAppearanceSettings())).toBe('')
  })

  it('emits scoped override blocks only for customized variants', () => {
    const settings = mergeAppearanceSettings(defaultAppearanceSettings(), {
      themes: { dark: getThemePresetSeed('dracula', 'dark')! }
    })
    const css = buildAppearanceOverrideCss(settings)
    expect(css).toContain(":root[data-theme='dark']")
    expect(css).toContain(":root[data-theme='dark'] .ds-workbench-shell")
    expect(css).not.toContain(":root[data-theme='light']")
    expect(css).toContain('--ds-accent:')
  })

  it('derives sane light and dark palettes from three colors', () => {
    for (const variant of ['light', 'dark'] as const) {
      const theme = getThemePresetSeed('codex', variant)!
      const vars = buildChromeThemeCssVars(theme, variant)
      // Both variants: the content canvas IS the theme surface and the
      // sidebar takes the lifted panel mix. (In light the panel mixes toward
      // white, so a pure-white surface yields an identical sidebar — only
      // dark can assert the sidebar actually differs.)
      expect(vars['--bg-canvas']).toBe(theme.surface)
      if (variant === 'dark') {
        expect(vars['--bg-sidebar']).not.toBe(theme.surface)
      }
      expect(vars['--text-primary']).toBe(theme.ink)
      expect(vars['--ds-diff-added']).toBe(theme.semanticColors.diffAdded)
      // Every declared token resolves to a non-empty value.
      for (const [name, value] of Object.entries(vars)) {
        expect(value, name).toBeTruthy()
      }
    }
    // Dark accents brighten via the focus mix; light keeps the raw accent.
    const lightVars = buildChromeThemeCssVars(getThemePresetSeed('codex', 'light')!, 'light')
    expect(lightVars['--ds-accent']).toBe('#0169cc')
    const darkVars = buildChromeThemeCssVars(getThemePresetSeed('codex', 'dark')!, 'dark')
    expect(darkVars['--ds-accent']).not.toBe('#0169cc')
  })

  it('maps theme pack fonts to UI, mono, and chat-code tokens', () => {
    const theme = { ...getThemePresetSeed('raycast', 'dark')! }
    const vars = buildChromeThemeCssVars(theme, 'dark')
    expect(vars['--font-ui']).toContain('Inter')
    expect(vars['--font-mono']).toContain('JetBrains Mono')
    expect(vars['--ds-chat-code-font']).toContain('JetBrains Mono')
    // No font tokens leak when the pack leaves fonts empty.
    const bare = buildChromeThemeCssVars(getThemePresetSeed('dracula', 'dark')!, 'dark')
    expect(bare['--font-ui']).toBeUndefined()
    expect(bare['--ds-chat-code-font']).toBeUndefined()
  })

  it('opaque themes disable the glass blur', () => {
    const translucent = buildChromeThemeCssVars(getThemePresetSeed('codex', 'dark')!, 'dark')
    expect(translucent['--glass-blur']).toBe('8px')
    const opaque = buildChromeThemeCssVars(
      { ...getThemePresetSeed('codex', 'dark')!, translucent: false },
      'dark'
    )
    expect(opaque['--glass-blur']).toBe('0px')
  })
})
