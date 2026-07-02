/**
 * Derives the full workbench design-token palette from a ChromeThemeV1
 * (accent / surface / ink / contrast). The mixing math is ported from
 * Synara's theme.logic.ts (itself mirroring Codex Electron's chrome-theme
 * derivation), re-targeted at the `--ds-*` / `--glass-*` / material tokens
 * defined in index.css.
 *
 * Custom themes are applied by injecting a <style> element whose selectors
 * out-specify both the `:root` / `[data-theme='dark']` token blocks and the
 * `[data-theme='dark'] .ds-workbench-shell` re-declarations.
 */

import {
  CONTRAST_BASELINE,
  isDefaultChromeTheme,
  type AppearanceSettingsV1,
  type ChromeThemeV1,
  type ThemeVariant
} from './appearance'

type Rgb = { r: number; g: number; b: number }

const WHITE: Rgb = { r: 255, g: 255, b: 255 }
const BLACK: Rgb = { r: 0, g: 0, b: 0 }

// Same curvature constants as Synara: values below the baseline soften fast,
// values above steepen so the top of the slider has visible effect.
const CONTRAST_CURVE_BELOW_BASELINE = 0.7
const CONTRAST_CURVE_ABOVE_BASELINE = 2
const SURFACE_UNDER_BASE_ALPHA: Record<ThemeVariant, number> = { dark: 0.16, light: 0.04 }
const SURFACE_UNDER_CONTRAST_STEP: Record<ThemeVariant, number> = { dark: 0.0015, light: 0.0012 }
const PANEL_BASE_ALPHA: Record<ThemeVariant, number> = { dark: 0.03, light: 0.18 }
const PANEL_CONTRAST_STEP: Record<ThemeVariant, number> = { dark: 0.03, light: 0.008 }

function parseHex(value: string): Rgb {
  const hex = value.slice(1)
  return {
    r: Number.parseInt(hex.slice(0, 2), 16),
    g: Number.parseInt(hex.slice(2, 4), 16),
    b: Number.parseInt(hex.slice(4, 6), 16)
  }
}

function mixRgb(from: Rgb, to: Rgb, amount: number): Rgb {
  const t = Math.min(1, Math.max(0, amount))
  return {
    r: Math.round(from.r + (to.r - from.r) * t),
    g: Math.round(from.g + (to.g - from.g) * t),
    b: Math.round(from.b + (to.b - from.b) * t)
  }
}

function hex(color: Rgb): string {
  const channel = (v: number): string => v.toString(16).padStart(2, '0')
  return `#${channel(color.r)}${channel(color.g)}${channel(color.b)}`
}

function rgba(color: Rgb, alpha: number): string {
  const a = Math.min(1, Math.max(0, alpha))
  return `rgba(${color.r}, ${color.g}, ${color.b}, ${Number(a.toFixed(3))})`
}

function normalizeContrastStrength(value: number, variant: ThemeVariant): number {
  const baseline = CONTRAST_BASELINE[variant]
  const baselineRatio = baseline / 100
  const curved = value / 100 + ((value - baseline) / 60) * CONTRAST_CURVE_BELOW_BASELINE
  if (value <= baseline) return curved
  return baselineRatio + (curved - baselineRatio) * CONTRAST_CURVE_ABOVE_BASELINE
}

/**
 * Full token map for a customized theme. Keys are CSS custom property names
 * from index.css; values are resolved colors.
 */
export function buildChromeThemeCssVars(
  theme: ChromeThemeV1,
  variant: ThemeVariant
): Record<string, string> {
  const light = variant === 'light'
  const c = normalizeContrastStrength(theme.contrast, variant)
  const surface = parseHex(theme.surface)
  const ink = parseHex(theme.ink)
  const accent = parseHex(theme.accent)
  const anchor = light ? WHITE : ink

  // Layered surfaces (Synara: surfaceUnder / panel / elevated / editor).
  const surfaceUnder = mixRgb(
    surface,
    light ? ink : BLACK,
    SURFACE_UNDER_BASE_ALPHA[variant] + (theme.contrast - CONTRAST_BASELINE[variant]) * SURFACE_UNDER_CONTRAST_STEP[variant]
  )
  const panel = mixRgb(surface, anchor, PANEL_BASE_ALPHA[variant] + c * PANEL_CONTRAST_STEP[variant])
  const elevated1 = mixRgb(surface, anchor, light ? 0.08 + c * 0.08 : 0.06 + c * 0.05)
  const elevated2 = mixRgb(surface, anchor, light ? 0.16 + c * 0.12 : 0.08 + c * 0.08)

  // Text tiers.
  const textSecondary = rgba(ink, 0.65 + c * 0.1)
  const textTertiary = rgba(ink, 0.45 + c * 0.1)

  // Borders.
  const borderSoft = rgba(ink, (light ? 0.09 : 0.1) + c * 0.04)
  const borderMuted = rgba(ink, (light ? 0.07 : 0.06) + c * 0.02)
  const borderStrong = rgba(ink, (light ? 0.09 : 0.16) + c * 0.06)

  // Dark accents brighten through a focus mix (Codex behavior) so low-value
  // accents stay legible on dark surfaces.
  const focusBase = mixRgb(accent, WHITE, 0.3 + c * 0.15)
  const accentDisplay = light ? accent : focusBase

  const diffAdded = parseHex(theme.semanticColors.diffAdded)
  const diffRemoved = parseHex(theme.semanticColors.diffRemoved)
  const skill = parseHex(theme.semanticColors.skill)

  const glass = theme.translucent
  const glassBg = glass ? rgba(panel, light ? 0.66 : 0.58) : hex(panel)
  const glassBgStrong = glass ? rgba(panel, light ? 0.78 : 0.7) : hex(elevated1)
  const glassBorder = rgba(ink, light ? 0.08 : 0.09)
  const glassHighlight = light ? rgba(WHITE, 0.5) : rgba(WHITE, 0.06)

  const vars: Record<string, string> = {
    '--bg-app': hex(surfaceUnder),
    '--bg-sidebar': hex(panel),
    '--bg-canvas': hex(surface),
    '--ds-sidebar-dot': rgba(ink, light ? 0.03 : 0.028),
    '--ds-canvas-dot': rgba(ink, 0.04),

    '--surface-1': rgba(surface, 0.92),
    '--surface-2': hex(elevated1),
    '--surface-3': hex(elevated2),
    '--border-soft': borderSoft,
    '--border-strong': borderStrong,
    '--text-primary': theme.ink,
    '--text-secondary': textSecondary,
    '--text-tertiary': textTertiary,
    '--text-placeholder': rgba(ink, 0.42 + c * 0.08),

    '--ds-surface-subtle': hex(mixRgb(surface, anchor, light ? 0.09 : 0.04 + c * 0.04)),
    '--ds-surface-hover': rgba(ink, light ? 0.05 : 0.1),
    '--ds-border-muted': borderMuted,
    '--ds-bubble-user': rgba(ink, light ? 0.06 : 0.08),
    '--ds-bubble-user-fg': theme.ink,

    '--ds-accent': hex(accentDisplay),
    '--ds-accent-soft': rgba(accentDisplay, light ? 0.14 : 0.18),
    '--ds-selection': rgba(accentDisplay, light ? 0.18 : 0.24),

    '--ds-success': theme.semanticColors.diffAdded,
    '--ds-danger': theme.semanticColors.diffRemoved,
    '--ds-diff-added': theme.semanticColors.diffAdded,
    '--ds-diff-added-soft': rgba(diffAdded, light ? 0.1 : 0.16),
    '--ds-diff-removed': theme.semanticColors.diffRemoved,
    '--ds-diff-removed-soft': rgba(diffRemoved, light ? 0.1 : 0.16),
    '--ds-skill': theme.semanticColors.skill,
    '--ds-skill-soft': rgba(skill, light ? 0.12 : 0.16),
    '--ds-success-soft': rgba(diffAdded, light ? 0.14 : 0.18),
    '--ds-danger-soft': rgba(diffRemoved, light ? 0.12 : 0.18),

    '--ds-stage-gradient': `linear-gradient(180deg, ${hex(elevated1)} 0%, ${hex(surface)} 100%)`,
    '--ds-topbar-bg': `linear-gradient(180deg, ${rgba(panel, 0.86)} 0%, ${rgba(panel, 0.62)} 58%, ${rgba(panel, 0.34)} 100%)`,
    '--ds-sidebar-gradient': `linear-gradient(180deg, ${hex(panel)} 0%, ${hex(panel)} 100%)`,
    '--ds-sidebar-border': rgba(ink, light ? 0.06 : 0.07),

    '--ds-card-soft': rgba(elevated1, light ? 0.82 : 0.9),
    '--ds-card-strong': rgba(elevated2, 0.96),
    '--ds-card-muted': rgba(elevated1, light ? 0.9 : 0.86),
    '--ds-card-ghost': rgba(surfaceUnder, light ? 0.62 : 0.72),
    '--ds-card-hover': rgba(elevated2, 0.98),
    '--ds-chip-bg': rgba(elevated1, light ? 0.92 : 0.94),
    '--ds-chip-muted-bg': hex(elevated1),
    '--ds-chip-hover': rgba(elevated2, 0.98),
    '--ds-chip-border': borderSoft,
    '--ds-chip-active': `linear-gradient(180deg, ${rgba(accentDisplay, light ? 0.16 : 0.18)}, ${rgba(accentDisplay, light ? 0.08 : 0.1)})`,
    '--ds-kbd-bg': rgba(elevated1, light ? 0.9 : 0.94),
    '--ds-code-bg': hex(mixRgb(surface, anchor, light ? 0.04 : 0.033)),
    '--ds-pre-bg': hex(mixRgb(surface, anchor, light ? 0.035 : 0)),
    '--ds-table-head-bg': rgba(elevated1, light ? 0.96 : 0.94),
    '--ds-scrollbar-thumb': rgba(ink, light ? 0.2 : 0.28),
    '--ds-scrollbar-thumb-hover': rgba(ink, light ? 0.3 : 0.38),

    '--glass-bg': glassBg,
    '--glass-bg-strong': glassBgStrong,
    '--glass-border': glassBorder,
    '--glass-highlight': glassHighlight,
    '--glass-card': glass ? rgba(light ? panel : WHITE, light ? 0.55 : 0.05) : hex(elevated1),
    '--glass-card-hover': glass ? rgba(light ? panel : WHITE, light ? 0.82 : 0.09) : hex(elevated2),
    '--glass-blur': glass ? (light ? '22px' : '30px') : '0px',

    '--ds-material-page': glass ? rgba(panel, light ? 0.54 : 0.55) : hex(surface),
    '--ds-material-panel': glass ? rgba(panel, light ? 0.72 : 0.7) : hex(panel),
    '--ds-material-card': glass
      ? light
        ? rgba(WHITE, 0.46)
        : rgba(WHITE, 0.045)
      : hex(elevated1),
    '--ds-material-card-hover': glass
      ? light
        ? rgba(WHITE, 0.72)
        : rgba(WHITE, 0.075)
      : hex(elevated2),
    '--ds-material-control': light ? rgba(WHITE, 0.52) : rgba(WHITE, 0.055),
    '--ds-material-stroke': light ? rgba(WHITE, 0.72) : rgba(WHITE, 0.075),

    '--app-wallpaper': `linear-gradient(180deg, ${hex(surfaceUnder)} 0%, ${hex(
      mixRgb(surfaceUnder, light ? ink : BLACK, 0.03)
    )} 100%)`
  }

  if (theme.uiFont) {
    // --font-display chains to var(--font-ui) in index.css, so one override is enough.
    vars['--font-ui'] = withUiFallback(theme.uiFont)
  }
  if (theme.codeFont) {
    // Markdown code blocks read --font-mono (which defaults to var(--font-ui)).
    vars['--font-mono'] = withMonoFallback(theme.codeFont)
  }

  return vars
}

function withUiFallback(family: string): string {
  const generic = /(sans-serif|serif|monospace|system-ui)\s*$/i.test(family)
  return generic ? family : `${family}, 'Inter', 'Noto Sans SC', sans-serif`
}

function withMonoFallback(family: string): string {
  const generic = /monospace\s*$/i.test(family)
  return generic ? family : `${family}, 'SF Mono', 'JetBrains Mono', monospace`
}

function cssBlock(selector: string, vars: Record<string, string>): string {
  const body = Object.entries(vars)
    .map(([name, value]) => `  ${name}: ${value};`)
    .join('\n')
  return `${selector} {\n${body}\n}`
}

/**
 * Builds the stylesheet text applied for customized themes. Returns '' when
 * both variants are still the built-in default (no overrides → the
 * handcrafted index.css palette stays exactly as-is).
 */
export function buildAppearanceOverrideCss(appearance: AppearanceSettingsV1): string {
  const blocks: string[] = []
  for (const variant of ['light', 'dark'] as const) {
    const theme = appearance.themes[variant]
    if (isDefaultChromeTheme(theme, variant)) continue
    const vars = buildChromeThemeCssVars(theme, variant)
    // The second selector out-specifies `[data-theme='dark'] .ds-workbench-shell`,
    // which re-declares many tokens on the workbench shell element.
    blocks.push(
      cssBlock(`:root[data-theme='${variant}']`, vars),
      cssBlock(`:root[data-theme='${variant}'] .ds-workbench-shell`, vars)
    )
  }
  return blocks.join('\n\n')
}
