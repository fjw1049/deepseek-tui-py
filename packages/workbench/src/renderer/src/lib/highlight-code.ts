import { renderFallbackHtml } from './code-fallback'
import type { ThemeRegistration, ThemeRegistrationRaw } from 'shiki'
import { CODE_CHROME, CODE_PALETTE, SHIKI_SCOPE_SLOTS, type CodeAppearance } from './code-palette'
import { normalizeLanguage } from '../components/chat/code-language'

/**
 * Both chat themes come from lib/code-palette.ts — the same slots the Monaco
 * editor consumes — so a file keeps its colors as it moves between the editor
 * and a chat block. The built-in `github-light` this replaces was the light
 * half of that drift.
 */
function shikiTheme(appearance: CodeAppearance, name: string): ThemeRegistration {
  const slots = CODE_PALETTE[appearance]
  const background = appearance === 'dark' ? '#181818' : '#ffffff'
  // One TextMate settings entry per distinct style, scopes grouped under it.
  const groups = new Map<string, { scope: string[]; settings: Record<string, string> }>()
  for (const [scope, slot, fontStyle] of SHIKI_SCOPE_SLOTS) {
    const style = slots[slot]
    const font = fontStyle ?? style.fontStyle ?? ''
    const settings: Record<string, string> = { foreground: style.color }
    if (font) settings.fontStyle = font
    if (style.background) settings.background = style.background
    const key = JSON.stringify(settings)
    const group = groups.get(key)
    if (group) group.scope.push(scope)
    else groups.set(key, { scope: [scope], settings })
  }
  return {
    name,
    displayName: name,
    type: appearance,
    fg: slots.ink.color,
    bg: background,
    colors: {
      ...CODE_CHROME[appearance],
      'editor.background': background,
      'terminal.ansiGreen': slots.added.color,
      'terminal.ansiRed': slots.removed.color,
      'terminal.ansiBlue': slots.changed.color,
      'terminal.ansiMagenta': slots.function.color
    },
    settings: [
      { settings: { foreground: slots.ink.color, background } },
      ...groups.values()
    ]
  } satisfies ThemeRegistration as ThemeRegistrationRaw as ThemeRegistration
}

const SHIKI_THEMES = {
  light: shikiTheme('light', 'ds-light'),
  dark: shikiTheme('dark', 'codex')
}

let shikiPromise: Promise<typeof import('shiki')> | null = null
const highlightCache = new Map<string, string>()
const inflightHighlights = new Map<string, Promise<string>>()
const HIGHLIGHT_CACHE_MAX = 48

function trimHighlightCache(): void {
  while (highlightCache.size > HIGHLIGHT_CACHE_MAX || Array.from(highlightCache, ([key, value]) => key.length + value.length).reduce((a, b) => a + b, 0) > 4_000_000) {
    const oldest = highlightCache.keys().next().value
    if (oldest === undefined) break
    highlightCache.delete(oldest)
  }
}

function loadShiki(): Promise<typeof import('shiki')> {
  shikiPromise ??= import('shiki').catch((error) => { shikiPromise = null; throw error })
  return shikiPromise
}

export async function highlightCodeHtml(code: string, language: string): Promise<string> {
  const normalized = normalizeLanguage(language)
  const cacheKey = `${normalized || 'plain'}\u0000${code}`
  const cached = highlightCache.get(cacheKey)
  if (cached) return cached

  const inflight = inflightHighlights.get(cacheKey)
  if (inflight) return inflight

  const task = (async () => {
    if (!normalized) {
      const fallback = renderFallbackHtml(code)
      highlightCache.set(cacheKey, fallback)
      trimHighlightCache()
      return fallback
    }

    try {
      const { codeToHtml } = await loadShiki()
      const html = await codeToHtml(code, {
        lang: normalized,
        themes: SHIKI_THEMES
      })
      highlightCache.set(cacheKey, html)
      trimHighlightCache()
      return html
    } catch (error) {
      // Common cause in Electron: CSP missing 'wasm-unsafe-eval' for Oniguruma.
      // Do not cache failures — CSP/HMR fixes should be able to retry.
      console.warn('[SharedCodeBlock] Shiki highlight failed; using plain text', error)
      return renderFallbackHtml(code)
    }
  })()

  inflightHighlights.set(cacheKey, task)
  try {
    return await task
  } finally {
    inflightHighlights.delete(cacheKey)
  }
}

