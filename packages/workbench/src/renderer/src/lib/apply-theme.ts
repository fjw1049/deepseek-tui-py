export type ThemePreference = 'system' | 'light' | 'dark'
export type UiFontScale = 'small' | 'medium' | 'large'
export type UiFontFamily = 'inter-noto' | 'system-native'

let removeSystemListener: (() => void) | null = null

function resolvedMode(pref: ThemePreference): 'light' | 'dark' {
  if (pref === 'dark') return 'dark'
  if (pref === 'light') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * Applies `data-theme` on `<html>` for Tailwind `dark:` variants and CSS variables.
 */
export function applyTheme(pref: ThemePreference): void {
  removeSystemListener?.()
  removeSystemListener = null

  const root = document.documentElement
  const apply = (): void => {
    root.setAttribute('data-theme', resolvedMode(pref))
  }

  if (pref === 'system') {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (): void => {
      apply()
    }
    mq.addEventListener('change', onChange)
    removeSystemListener = (): void => {
      mq.removeEventListener('change', onChange)
    }
  }

  apply()
}

export function applyUiFontScale(scale: UiFontScale): void {
  const root = document.documentElement
  const factor =
    scale === 'small'
      ? '0.82'
      : scale === 'large'
        ? '1'
        : '0.88'
  root.style.setProperty('--ds-ui-scale', factor)
}

export const UI_FONT_CHANGED_EVENT = 'deepseekgui:ui-font-changed'

export function readUiFontFamily(): string {
  const family = getComputedStyle(document.documentElement).getPropertyValue('--font-ui').trim()
  return family || "'Inter', 'Noto Sans SC', sans-serif"
}

/** Terminal/xterm must stay monospace — proportional UI fonts break column layout and FitAddon. */
export function readTerminalFontFamily(): string {
  const family = getComputedStyle(document.documentElement).getPropertyValue('--font-terminal').trim()
  return (
    family ||
    "'SF Mono', SFMono-Regular, ui-monospace, Menlo, Monaco, Consolas, 'Liberation Mono', monospace"
  )
}

export function applyUiFontFamily(family: UiFontFamily): void {
  document.documentElement.setAttribute('data-ui-font', family)
  window.dispatchEvent(new CustomEvent(UI_FONT_CHANGED_EVENT))
}
