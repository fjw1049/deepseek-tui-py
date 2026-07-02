/**
 * Runtime application of appearance settings.
 *
 * - Injects/updates a <style> element with derived theme tokens for
 *   customized light/dark theme packs (none when both are default).
 * - Sets root-level data attributes / CSS variables for density, chat font
 *   size, terminal typography, and font smoothing.
 * - Exposes a subscribe/get store so live consumers (xterm terminal,
 *   message timestamps) can react without prop drilling.
 */

import {
  defaultAppearanceSettings,
  type AppearanceSettingsV1,
  type TimestampFormat
} from '@shared/appearance'
import { buildAppearanceOverrideCss } from '@shared/appearance-derive'

const STYLE_ELEMENT_ID = 'ds-appearance-overrides'

let current: AppearanceSettingsV1 = defaultAppearanceSettings()
const listeners = new Set<() => void>()

export function getAppearanceSettings(): AppearanceSettingsV1 {
  return current
}

export function subscribeAppearance(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getTimestampFormat(): TimestampFormat {
  return current.timestampFormat
}

export function getTerminalFontSizePx(): number {
  return current.terminalFontSizePx
}

export function applyAppearance(appearance: AppearanceSettingsV1): void {
  current = appearance
  const root = document.documentElement

  const css = buildAppearanceOverrideCss(appearance)
  let styleEl = document.getElementById(STYLE_ELEMENT_ID) as HTMLStyleElement | null
  if (css) {
    if (!styleEl) {
      styleEl = document.createElement('style')
      styleEl.id = STYLE_ELEMENT_ID
    }
    if (styleEl.textContent !== css) styleEl.textContent = css
    // (Re-)append so the overrides stay after every stylesheet — ties on
    // specificity (e.g. --font-ui vs :root[data-ui-font=…]) resolve to us.
    document.head.appendChild(styleEl)
  } else if (styleEl) {
    styleEl.remove()
  }

  root.setAttribute('data-density', appearance.uiDensity)
  root.style.setProperty('--ds-chat-font-size', `${appearance.chatFontSizePx}px`)

  // Terminal font: index.css defines --font-terminal at :root; an inline
  // declaration on <html> wins whenever a custom family is configured.
  const terminalFamily = appearance.terminalFontFamily.trim()
  if (terminalFamily) {
    const stack = /monospace\s*$/i.test(terminalFamily)
      ? terminalFamily
      : `${terminalFamily}, 'SF Mono', SFMono-Regular, ui-monospace, Menlo, Monaco, Consolas, 'Liberation Mono', monospace`
    root.style.setProperty('--font-terminal', stack)
  } else {
    root.style.removeProperty('--font-terminal')
  }

  if (appearance.fontSmoothing) {
    root.removeAttribute('data-font-smoothing')
  } else {
    root.setAttribute('data-font-smoothing', 'off')
  }

  for (const listener of listeners) listener()
}
