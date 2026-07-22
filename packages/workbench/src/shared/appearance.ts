/**
 * Appearance settings model (Settings → Appearance).
 *
 * Ported from Synara's theme-pack concept: each light/dark variant stores a
 * small "chrome theme" (accent / surface / ink / contrast / translucency /
 * fonts) and the full palette is derived at runtime (see appearance-derive.ts).
 * The special preset id `default` means "use the app's built-in handcrafted
 * palette" — no CSS overrides are generated for it, so the default look stays
 * byte-identical to the pre-appearance-feature UI.
 */

export type ThemeVariant = 'light' | 'dark'
export type UiDensity = 'compact' | 'comfortable' | 'spacious'
export type TimestampFormat = 'locale' | '12-hour' | '24-hour'

export type ThemeSemanticColorsV1 = {
  diffAdded: string
  diffRemoved: string
  skill: string
}

export type ChromeThemeV1 = {
  /** Preset id from APPEARANCE_THEME_PRESETS, or 'custom' after manual edits. */
  presetId: string
  accent: string
  /** Background. */
  surface: string
  /** Foreground. */
  ink: string
  /** 0–100; baseline is 45 (light) / 60 (dark). */
  contrast: number
  /** Translucent (glass) sidebar & panels; false = opaque surfaces. */
  translucent: boolean
  /** UI font family CSS value; '' = app default stack. */
  uiFont: string
  /** Code font family CSS value; '' = app default stack. */
  codeFont: string
  semanticColors: ThemeSemanticColorsV1
}

export type AppearanceSettingsV1 = {
  themes: Record<ThemeVariant, ChromeThemeV1>
  uiDensity: UiDensity
  /** Chat/reading text size in px. */
  chatFontSizePx: number
  terminalFontSizePx: number
  /** '' = default monospace stack. */
  terminalFontFamily: string
  fontSmoothing: boolean
  timestampFormat: TimestampFormat
}

export type ChromeThemePatchV1 = Partial<ChromeThemeV1>
export type AppearancePatchV1 = Partial<Omit<AppearanceSettingsV1, 'themes'>> & {
  themes?: Partial<Record<ThemeVariant, ChromeThemePatchV1>>
}

export const CONTRAST_BASELINE: Record<ThemeVariant, number> = {
  light: 45,
  dark: 60
}

export const MIN_CHAT_FONT_SIZE_PX = 12
export const MAX_CHAT_FONT_SIZE_PX = 20
export const DEFAULT_CHAT_FONT_SIZE_PX = 15
export const MIN_TERMINAL_FONT_SIZE_PX = 10
export const MAX_TERMINAL_FONT_SIZE_PX = 22
export const DEFAULT_TERMINAL_FONT_SIZE_PX = 13

export const DEFAULT_THEME_PRESET_ID = 'default'
export const CUSTOM_THEME_PRESET_ID = 'custom'

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/

/**
 * Factory-default chrome themes (Settings → Appearance on first launch /
 * "Restore defaults"). Light ships as Notion + JetBrains Mono at full
 * contrast; dark ships as One with the same font/contrast/glass choices.
 * The legacy handcrafted Workbench palette remains available as the
 * `default` preset in the catalog.
 */
export const DEFAULT_CHROME_THEMES: Record<ThemeVariant, ChromeThemeV1> = {
  light: {
    presetId: 'notion',
    accent: '#3183d8',
    surface: '#ffffff',
    ink: '#37352f',
    contrast: 100,
    translucent: true,
    uiFont: '',
    codeFont: '"JetBrains Mono"',
    semanticColors: { diffAdded: '#008000', diffRemoved: '#a31515', skill: '#0000ff' }
  },
  dark: {
    presetId: 'one',
    accent: '#4d78cc',
    surface: '#282c34',
    ink: '#abb2bf',
    contrast: 100,
    translucent: true,
    uiFont: '',
    codeFont: '"JetBrains Mono"',
    semanticColors: { diffAdded: '#8cc265', diffRemoved: '#e05561', skill: '#c162de' }
  }
}

type PresetSeed = Omit<ChromeThemeV1, 'presetId'>

export type AppearanceThemePreset = {
  id: string
  label: string
  seeds: Partial<Record<ThemeVariant, PresetSeed>>
}

/** Legacy Workbench seeds that mirror the handcrafted index.css palette. */
const WORKBENCH_CHROME_SEEDS: Record<ThemeVariant, PresetSeed> = {
  light: {
    accent: '#0088ff',
    surface: '#ffffff',
    ink: '#262626',
    contrast: CONTRAST_BASELINE.light,
    translucent: true,
    uiFont: '',
    codeFont: '',
    semanticColors: { diffAdded: '#128a4a', diffRemoved: '#c92a2a', skill: '#7c3aed' }
  },
  dark: {
    accent: '#339cff',
    surface: '#111111',
    ink: '#ececec',
    contrast: CONTRAST_BASELINE.dark,
    translucent: true,
    uiFont: '',
    codeFont: '',
    semanticColors: { diffAdded: '#40c977', diffRemoved: '#fa423e', skill: '#ad7bf9' }
  }
}

function seed(
  variant: ThemeVariant,
  accent: string,
  surface: string,
  ink: string,
  semanticColors: ThemeSemanticColorsV1,
  extra: Partial<PresetSeed> = {}
): PresetSeed {
  return {
    accent,
    surface,
    ink,
    contrast: CONTRAST_BASELINE[variant],
    translucent: true,
    uiFont: '',
    codeFont: '',
    semanticColors,
    ...extra
  }
}

/**
 * Preset catalog ported from Synara's theme seed catalog (MIT). Values are the
 * normalized Codex theme seeds; a few presets carry font / opacity opinions.
 */
export const APPEARANCE_THEME_PRESETS: readonly AppearanceThemePreset[] = [
  {
    id: DEFAULT_THEME_PRESET_ID,
    label: 'Workbench',
    seeds: {
      light: { ...WORKBENCH_CHROME_SEEDS.light },
      dark: { ...WORKBENCH_CHROME_SEEDS.dark }
    }
  },
  {
    id: 'codex',
    label: 'Codex',
    seeds: {
      light: seed('light', '#0169cc', '#ffffff', '#0d0d0d', {
        diffAdded: '#00a240',
        diffRemoved: '#e02e2a',
        skill: '#751ed9'
      }),
      dark: seed('dark', '#0169cc', '#111111', '#fcfcfc', {
        diffAdded: '#00a240',
        diffRemoved: '#e02e2a',
        skill: '#b06dff'
      })
    }
  },
  {
    id: 'catppuccin',
    label: 'Catppuccin',
    seeds: {
      light: seed('light', '#8839ef', '#eff1f5', '#4c4f69', {
        diffAdded: '#40a02b',
        diffRemoved: '#d20f39',
        skill: '#8839ef'
      }),
      dark: seed('dark', '#cba6f7', '#1e1e2e', '#cdd6f4', {
        diffAdded: '#a6e3a1',
        diffRemoved: '#f38ba8',
        skill: '#cba6f7'
      })
    }
  },
  {
    id: 'dracula',
    label: 'Dracula',
    seeds: {
      dark: seed('dark', '#ff79c6', '#282a36', '#f8f8f2', {
        diffAdded: '#50fa7b',
        diffRemoved: '#ff5555',
        skill: '#ff79c6'
      })
    }
  },
  {
    id: 'everforest',
    label: 'Everforest',
    seeds: {
      light: seed('light', '#93b259', '#fdf6e3', '#5c6a72', {
        diffAdded: '#8da101',
        diffRemoved: '#f85552',
        skill: '#df69ba'
      }),
      dark: seed('dark', '#a7c080', '#2d353b', '#d3c6aa', {
        diffAdded: '#a7c080',
        diffRemoved: '#e67e80',
        skill: '#d699b6'
      })
    }
  },
  {
    id: 'github',
    label: 'GitHub',
    seeds: {
      light: seed('light', '#0969da', '#ffffff', '#1f2328', {
        diffAdded: '#1a7f37',
        diffRemoved: '#cf222e',
        skill: '#8250df'
      }),
      dark: seed('dark', '#1f6feb', '#0d1117', '#e6edf3', {
        diffAdded: '#3fb950',
        diffRemoved: '#f85149',
        skill: '#bc8cff'
      })
    }
  },
  {
    id: 'gruvbox',
    label: 'Gruvbox',
    seeds: {
      light: seed('light', '#458588', '#fbf1c7', '#3c3836', {
        diffAdded: '#3c3836',
        diffRemoved: '#cc241d',
        skill: '#b16286'
      }),
      dark: seed('dark', '#458588', '#282828', '#ebdbb2', {
        diffAdded: '#ebdbb2',
        diffRemoved: '#cc241d',
        skill: '#b16286'
      })
    }
  },
  {
    id: 'linear',
    label: 'Linear',
    seeds: {
      light: seed(
        'light',
        '#5e6ad2',
        '#fcfcfd',
        '#1b1b1b',
        { diffAdded: '#52a450', diffRemoved: '#c94446', skill: '#8160d8' },
        { uiFont: 'Inter', translucent: false }
      ),
      dark: seed(
        'dark',
        '#606acc',
        '#0f0f11',
        '#e3e4e6',
        { diffAdded: '#69c967', diffRemoved: '#ff7e78', skill: '#c2a1ff' },
        { uiFont: 'Inter', translucent: false }
      )
    }
  },
  {
    id: 'matrix',
    label: 'Matrix',
    seeds: {
      dark: seed(
        'dark',
        '#1eff5a',
        '#040805',
        '#b8ffca',
        { diffAdded: '#1eff5a', diffRemoved: '#fa423e', skill: '#1eff5a' },
        {
          uiFont: 'ui-monospace, "SFMono-Regular", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
          translucent: false
        }
      )
    }
  },
  {
    id: 'monokai',
    label: 'Monokai',
    seeds: {
      dark: seed('dark', '#99947c', '#272822', '#f8f8f2', {
        diffAdded: '#86b42b',
        diffRemoved: '#c4265e',
        skill: '#8c6bc8'
      })
    }
  },
  {
    id: 'nord',
    label: 'Nord',
    seeds: {
      dark: seed('dark', '#88c0d0', '#2e3440', '#d8dee9', {
        diffAdded: '#a3be8c',
        diffRemoved: '#bf616a',
        skill: '#b48ead'
      })
    }
  },
  {
    id: 'notion',
    label: 'Notion',
    seeds: {
      light: seed(
        'light',
        '#3183d8',
        '#ffffff',
        '#37352f',
        { diffAdded: '#008000', diffRemoved: '#a31515', skill: '#0000ff' },
        { translucent: false }
      ),
      dark: seed(
        'dark',
        '#3183d8',
        '#191919',
        '#d9d9d8',
        { diffAdded: '#4ec9b0', diffRemoved: '#fa423e', skill: '#3183d8' },
        { translucent: false }
      )
    }
  },
  {
    id: 'one',
    label: 'One',
    seeds: {
      light: seed('light', '#526fff', '#fafafa', '#383a42', {
        diffAdded: '#3bba54',
        diffRemoved: '#e45649',
        skill: '#526fff'
      }),
      dark: seed('dark', '#4d78cc', '#282c34', '#abb2bf', {
        diffAdded: '#8cc265',
        diffRemoved: '#e05561',
        skill: '#c162de'
      })
    }
  },
  {
    id: 'raycast',
    label: 'Raycast',
    seeds: {
      light: seed(
        'light',
        '#ff6363',
        '#ffffff',
        '#030303',
        { diffAdded: '#006b4f', diffRemoved: '#b12424', skill: '#9a1b6e' },
        { uiFont: 'Inter', codeFont: '"JetBrains Mono"', translucent: false }
      ),
      dark: seed(
        'dark',
        '#ff6363',
        '#101010',
        '#fefefe',
        { diffAdded: '#59d499', diffRemoved: '#ff6363', skill: '#cf2f98' },
        { uiFont: 'Inter', codeFont: '"JetBrains Mono"', translucent: false }
      )
    }
  },
  {
    id: 'rose-pine',
    label: 'Rose Pine',
    seeds: {
      light: seed('light', '#d7827e', '#faf4ed', '#575279', {
        diffAdded: '#56949f',
        diffRemoved: '#797593',
        skill: '#907aa9'
      }),
      dark: seed('dark', '#ea9a97', '#232136', '#e0def4', {
        diffAdded: '#9ccfd8',
        diffRemoved: '#908caa',
        skill: '#c4a7e7'
      })
    }
  },
  {
    id: 'solarized',
    label: 'Solarized',
    seeds: {
      light: seed('light', '#b58900', '#fdf6e3', '#657b83', {
        diffAdded: '#859900',
        diffRemoved: '#dc322f',
        skill: '#d33682'
      }),
      dark: seed('dark', '#d30102', '#002b36', '#839496', {
        diffAdded: '#859900',
        diffRemoved: '#dc322f',
        skill: '#d33682'
      })
    }
  },
  {
    id: 'tokyo-night',
    label: 'Tokyo Night',
    seeds: {
      dark: seed('dark', '#3d59a1', '#1a1b26', '#a9b1d6', {
        diffAdded: '#449dab',
        diffRemoved: '#914c54',
        skill: '#9d7cd8'
      })
    }
  },
  {
    id: 'vercel',
    label: 'Vercel',
    seeds: {
      light: seed(
        'light',
        '#006aff',
        '#ffffff',
        '#171717',
        { diffAdded: '#28a948', diffRemoved: '#eb001d', skill: '#a100f8' },
        {
          contrast: 40,
          uiFont: 'Geist, Inter',
          codeFont: '"Geist Mono", ui-monospace, "SFMono-Regular"',
          translucent: false
        }
      ),
      dark: seed(
        'dark',
        '#006efe',
        '#000000',
        '#ededed',
        { diffAdded: '#00ad3a', diffRemoved: '#f13342', skill: '#9540d5' },
        {
          contrast: 50,
          uiFont: 'Geist, Inter',
          codeFont: '"Geist Mono", ui-monospace, "SFMono-Regular"',
          translucent: false
        }
      )
    }
  },
  {
    id: 'vscode-plus',
    label: 'VS Code Plus',
    seeds: {
      light: seed('light', '#007acc', '#ffffff', '#000000', {
        diffAdded: '#008000',
        diffRemoved: '#ee0000',
        skill: '#0000ff'
      }),
      dark: seed('dark', '#007acc', '#1e1e1e', '#d4d4d4', {
        diffAdded: '#369432',
        diffRemoved: '#f44747',
        skill: '#000080'
      })
    }
  }
]

export function getThemePresetSeed(presetId: string, variant: ThemeVariant): ChromeThemeV1 | null {
  const preset = APPEARANCE_THEME_PRESETS.find((entry) => entry.id === presetId)
  const presetSeed = preset?.seeds[variant]
  if (!presetSeed) return null
  return { presetId, ...presetSeed }
}

export function listThemePresetsForVariant(variant: ThemeVariant): AppearanceThemePreset[] {
  return APPEARANCE_THEME_PRESETS.filter((preset) => preset.seeds[variant] != null)
}

export function defaultAppearanceSettings(): AppearanceSettingsV1 {
  return {
    themes: {
      light: { ...DEFAULT_CHROME_THEMES.light, semanticColors: { ...DEFAULT_CHROME_THEMES.light.semanticColors } },
      dark: { ...DEFAULT_CHROME_THEMES.dark, semanticColors: { ...DEFAULT_CHROME_THEMES.dark.semanticColors } }
    },
    uiDensity: 'comfortable',
    chatFontSizePx: DEFAULT_CHAT_FONT_SIZE_PX,
    terminalFontSizePx: DEFAULT_TERMINAL_FONT_SIZE_PX,
    terminalFontFamily: '',
    fontSmoothing: true,
    timestampFormat: 'locale'
  }
}

export function normalizeHexColor(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const trimmed = value.trim().toLowerCase()
  if (HEX_COLOR_RE.test(trimmed)) return trimmed
  // Expand shorthand #abc → #aabbcc for robustness.
  const short = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/.exec(trimmed)
  if (short) return `#${short[1]}${short[1]}${short[2]}${short[2]}${short[3]}${short[3]}`
  return fallback
}

function normalizeContrast(value: unknown, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(100, Math.max(0, Math.round(parsed)))
}

function normalizeFont(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function normalizeBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function normalizeIntInRange(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, Math.round(parsed)))
}

function normalizeSemanticColors(
  input: unknown,
  fallback: ThemeSemanticColorsV1
): ThemeSemanticColorsV1 {
  const raw =
    typeof input === 'object' && input !== null && !Array.isArray(input)
      ? (input as Partial<ThemeSemanticColorsV1>)
      : {}
  return {
    diffAdded: normalizeHexColor(raw.diffAdded, fallback.diffAdded),
    diffRemoved: normalizeHexColor(raw.diffRemoved, fallback.diffRemoved),
    skill: normalizeHexColor(raw.skill, fallback.skill)
  }
}

export function normalizeChromeTheme(input: unknown, variant: ThemeVariant): ChromeThemeV1 {
  const defaults = DEFAULT_CHROME_THEMES[variant]
  const raw =
    typeof input === 'object' && input !== null && !Array.isArray(input)
      ? (input as Partial<ChromeThemeV1>)
      : {}
  const presetId =
    typeof raw.presetId === 'string' && raw.presetId.trim()
      ? raw.presetId.trim().toLowerCase()
      : defaults.presetId
  return {
    presetId,
    accent: normalizeHexColor(raw.accent, defaults.accent),
    surface: normalizeHexColor(raw.surface, defaults.surface),
    ink: normalizeHexColor(raw.ink, defaults.ink),
    contrast: normalizeContrast(raw.contrast, defaults.contrast),
    translucent: normalizeBoolean(raw.translucent, defaults.translucent),
    // Empty string is a valid "use system/app default" choice; only fall back
    // when the field is absent (fresh / partial payloads).
    uiFont: 'uiFont' in raw ? normalizeFont(raw.uiFont) : defaults.uiFont,
    codeFont: 'codeFont' in raw ? normalizeFont(raw.codeFont) : defaults.codeFont,
    semanticColors: normalizeSemanticColors(raw.semanticColors, defaults.semanticColors)
  }
}

function normalizeUiDensity(value: unknown): UiDensity {
  return value === 'compact' || value === 'spacious' ? value : 'comfortable'
}

function normalizeTimestampFormat(value: unknown): TimestampFormat {
  return value === '12-hour' || value === '24-hour' ? value : 'locale'
}

export function normalizeAppearanceSettings(input: AppearancePatchV1 | undefined): AppearanceSettingsV1 {
  const defaults = defaultAppearanceSettings()
  const source = input ?? {}
  const themes =
    typeof source.themes === 'object' && source.themes !== null ? source.themes : {}
  return {
    themes: {
      light: normalizeChromeTheme(themes.light, 'light'),
      dark: normalizeChromeTheme(themes.dark, 'dark')
    },
    uiDensity: normalizeUiDensity(source.uiDensity),
    chatFontSizePx: normalizeIntInRange(
      source.chatFontSizePx,
      defaults.chatFontSizePx,
      MIN_CHAT_FONT_SIZE_PX,
      MAX_CHAT_FONT_SIZE_PX
    ),
    terminalFontSizePx: normalizeIntInRange(
      source.terminalFontSizePx,
      defaults.terminalFontSizePx,
      MIN_TERMINAL_FONT_SIZE_PX,
      MAX_TERMINAL_FONT_SIZE_PX
    ),
    terminalFontFamily: normalizeFont(source.terminalFontFamily),
    fontSmoothing: normalizeBoolean(source.fontSmoothing, defaults.fontSmoothing),
    timestampFormat: normalizeTimestampFormat(source.timestampFormat)
  }
}

export function mergeAppearanceSettings(
  current: AppearanceSettingsV1 | undefined,
  patch: AppearancePatchV1 | undefined
): AppearanceSettingsV1 {
  const base = current ?? defaultAppearanceSettings()
  if (!patch) return normalizeAppearanceSettings(base)
  return normalizeAppearanceSettings({
    ...base,
    ...patch,
    themes: {
      light: { ...base.themes.light, ...(patch.themes?.light ?? {}) },
      dark: { ...base.themes.dark, ...(patch.themes?.dark ?? {}) }
    }
  })
}

export function chromeThemeEquals(a: ChromeThemeV1, b: ChromeThemeV1): boolean {
  return (
    a.accent === b.accent &&
    a.surface === b.surface &&
    a.ink === b.ink &&
    a.contrast === b.contrast &&
    a.translucent === b.translucent &&
    a.uiFont === b.uiFont &&
    a.codeFont === b.codeFont &&
    a.semanticColors.diffAdded === b.semanticColors.diffAdded &&
    a.semanticColors.diffRemoved === b.semanticColors.diffRemoved &&
    a.semanticColors.skill === b.semanticColors.skill
  )
}

/** True when the variant is untouched — the built-in stylesheet should apply as-is. */
export function isDefaultChromeTheme(theme: ChromeThemeV1, variant: ThemeVariant): boolean {
  return chromeThemeEquals(theme, DEFAULT_CHROME_THEMES[variant])
}

// ─── Share strings ─────────────────────────────────────────────────────────
// Compatible with Synara / Codex web share packs (`codex-theme-v1:{json}`)
// where the payload theme uses { accent, surface, ink, contrast, fonts:{ui,code},
// opaqueWindows, semanticColors } — mapped to ChromeThemeV1 on import.

const THEME_SHARE_PREFIX = 'codex-theme-v1:'

type ThemeSharePayload = {
  codeThemeId: string
  variant: ThemeVariant
  theme: {
    accent: string
    surface: string
    ink: string
    contrast: number
    opaqueWindows: boolean
    fonts: { ui: string | null; code: string | null }
    semanticColors: ThemeSemanticColorsV1
  }
}

export function createThemeShareString(variant: ThemeVariant, theme: ChromeThemeV1): string {
  const payload: ThemeSharePayload = {
    codeThemeId: theme.presetId,
    variant,
    theme: {
      accent: theme.accent,
      surface: theme.surface,
      ink: theme.ink,
      contrast: theme.contrast,
      opaqueWindows: !theme.translucent,
      fonts: {
        ui: theme.uiFont || null,
        code: theme.codeFont || null
      },
      semanticColors: { ...theme.semanticColors }
    }
  }
  return `${THEME_SHARE_PREFIX}${JSON.stringify(payload)}`
}

export type ThemeShareParseResult =
  | { ok: true; variant: ThemeVariant; theme: ChromeThemeV1 }
  | { ok: false; error: 'format' | 'variant-mismatch' }

export function parseThemeShareString(
  raw: string,
  expectedVariant: ThemeVariant
): ThemeShareParseResult {
  const trimmed = raw.trim()
  if (!trimmed.startsWith(THEME_SHARE_PREFIX)) return { ok: false, error: 'format' }
  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed.slice(THEME_SHARE_PREFIX.length))
  } catch {
    return { ok: false, error: 'format' }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: 'format' }
  }
  const payload = parsed as Partial<ThemeSharePayload>
  const variant = payload.variant
  if (variant !== 'light' && variant !== 'dark') return { ok: false, error: 'format' }
  if (variant !== expectedVariant) return { ok: false, error: 'variant-mismatch' }
  const rawTheme = payload.theme
  if (typeof rawTheme !== 'object' || rawTheme === null) return { ok: false, error: 'format' }
  const defaults = DEFAULT_CHROME_THEMES[variant]
  const accent = normalizeHexColor(rawTheme.accent, '')
  const surface = normalizeHexColor(rawTheme.surface, '')
  const ink = normalizeHexColor(rawTheme.ink, '')
  if (!accent || !surface || !ink) return { ok: false, error: 'format' }
  const presetId =
    typeof payload.codeThemeId === 'string' && payload.codeThemeId.trim()
      ? payload.codeThemeId.trim().toLowerCase()
      : CUSTOM_THEME_PRESET_ID
  const theme = normalizeChromeTheme(
    {
      presetId,
      accent,
      surface,
      ink,
      contrast: rawTheme.contrast,
      translucent:
        typeof rawTheme.opaqueWindows === 'boolean' ? !rawTheme.opaqueWindows : defaults.translucent,
      uiFont: rawTheme.fonts?.ui ?? '',
      codeFont: rawTheme.fonts?.code ?? '',
      semanticColors: rawTheme.semanticColors
    },
    variant
  )
  return { ok: true, variant, theme }
}
