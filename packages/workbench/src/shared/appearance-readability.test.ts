import { expect, it } from 'vitest'
import { defaultAppearanceSettings } from './appearance'
import { buildChromeThemeCssVars } from './appearance-derive'

function rgb(color: string): number[] {
  return color.startsWith('#')
    ? [1, 3, 5].map((index) => parseInt(color.slice(index, index + 2), 16))
    : (color.match(/[\d.]+/g) ?? []).map(Number)
}

function luminance(channels: number[]): number {
  return channels.slice(0, 3).reduce((sum, channel, index) => {
    const value = channel / 255
    const linear = value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
    return sum + linear * [0.2126, 0.7152, 0.0722][index]
  }, 0)
}

function contrast(foreground: string, background: string): number {
  const fg = rgb(foreground)
  const bg = rgb(background)
  const alpha = fg[3] ?? 1
  const a = luminance(fg.slice(0, 3).map((channel, index) => channel * alpha + bg[index] * (1 - alpha)))
  const b = luminance(bg)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

it.each(['light', 'dark'] as const)('keeps default %s button and secondary reading text legible', (variant) => {
  const vars = buildChromeThemeCssVars(defaultAppearanceSettings().themes[variant], variant)
  expect(contrast(vars['--ds-accent-foreground'], vars['--ds-accent'])).toBeGreaterThanOrEqual(4.5)
  expect(contrast(vars['--text-tertiary'], vars['--bg-canvas'])).toBeGreaterThanOrEqual(4.5)
  expect(contrast(vars['--text-placeholder'], vars['--bg-canvas'])).toBeGreaterThanOrEqual(4.5)
})
