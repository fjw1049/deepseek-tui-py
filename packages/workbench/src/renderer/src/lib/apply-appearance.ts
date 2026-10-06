/**
 * Runtime application of appearance settings.
 *
 * - Injects/updates a <style> element with derived theme tokens for the
 *   light/dark theme packs. The stylesheet is generated unconditionally —
 *   factory defaults go through the same derivation as custom themes.
 * - Sets root-level data attributes / CSS variables for density, chat font
 *   size, terminal typography, and font smoothing.
 * - Exposes a subscribe/get store so live consumers (xterm terminal,
 *   message timestamps) can react without prop drilling.
 */

import {
  defaultAppearanceSettings,
  type AppearanceSettingsV1,
  type EmptyHomeLayout,
  type TimestampFormat
} from '@shared/appearance'
import { buildAppearanceOverrideCss } from '@shared/appearance-derive'
import { THEME_CHANGED_EVENT } from './apply-theme'

const STYLE_ELEMENT_ID = 'ds-appearance-overrides'

let current: AppearanceSettingsV1 = defaultAppearanceSettings()
const listeners = new Set<() => void>()
let appearanceApplied = false
let lastWindowMaterial: string | null = null
let materialRequest = 0
let windowBlurUnavailable = false

export function getWindowBlurUnavailable(): boolean {
  return windowBlurUnavailable
}

function setWindowBlurUnavailable(value: boolean): void {
  if (windowBlurUnavailable === value) return
  windowBlurUnavailable = value
  for (const listener of listeners) listener()
}

function syncWindowMaterial(): void {
  if (!appearanceApplied || window.dsGui?.platform !== 'darwin') return
  const variant = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
  const blur = current.translucency[variant].blur
  const material = current.themes[variant].translucent && blur !== null ? 'translucent' : 'opaque'
  const blurRadius = material === 'translucent' ? blur! : 0
  const key = `${material}:${blurRadius}`
  if (lastWindowMaterial === key) return
  lastWindowMaterial = key
  const request = ++materialRequest
  if (typeof window.dsGui.setWindowMaterial !== 'function') {
    setWindowBlurUnavailable(material === 'translucent')
    return
  }
  void window.dsGui.setWindowMaterial({ material, blurRadius }).then(
    (applied) => {
      if (request === materialRequest) setWindowBlurUnavailable(material === 'translucent' && !applied)
    },
    () => {
      if (request !== materialRequest) return
      lastWindowMaterial = null
      setWindowBlurUnavailable(material === 'translucent')
    }
  )
}

if (typeof window !== 'undefined') window.addEventListener(THEME_CHANGED_EVENT, syncWindowMaterial)

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

export function getEmptyHomeLayout(): EmptyHomeLayout {
  return current.emptyHomeLayout
}

export function getTerminalFontSizePx(): number {
  return current.terminalFontSizePx
}

export function applyAppearance(appearance: AppearanceSettingsV1): void {
  current = appearance
  appearanceApplied = true
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
  // The IDE rail overrides this with its compact local reading size.
  root.style.setProperty('--ds-answer-font-size', `${appearance.chatFontSizePx}px`)

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

  syncWindowMaterial()
  for (const listener of listeners) listener()
}
