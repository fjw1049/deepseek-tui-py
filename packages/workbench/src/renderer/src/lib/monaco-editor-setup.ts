import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'
import { CODE_CHROME, CODE_PALETTE, MONACO_SCOPE_SLOTS, type CodeAppearance } from './code-palette'
import { registerLexicalSemanticTokens } from './monaco-lexical-semantic-tokens'

let configured = false
let themesReady = false

export type WorkspaceMonacoThemeName =
  | 'ds-workspace-dark'
  | 'ds-workspace-light'
  | 'ds-ide-workspace-dark'
  | 'ds-ide-workspace-light'

// One palette for both surfaces: lib/code-palette.ts holds the slots, this file
// only maps them onto Monaco token names. Monarch tokens (keyword/string/
// number/comment/type/delimiter) and the semantic-token types the lexical
// provider emits (function/method/macro/decorator/parameter/class) both match
// the same `token` field once semanticHighlighting is on. Monaco appends the
// language to a token (`keyword.go`) and matches the longest dotted prefix, so
// one rule per scope covers every language that emits it.
export function themeRules(appearance: CodeAppearance): monaco.editor.ITokenThemeRule[] {
  const slots = CODE_PALETTE[appearance]
  return MONACO_SCOPE_SLOTS.map(([token, slot, fontStyle]) => {
    const style = slots[slot]
    const rule: monaco.editor.ITokenThemeRule = { token, foreground: style.color.slice(1) }
    const font = fontStyle ?? style.fontStyle
    if (font) rule.fontStyle = font
    return rule
  })
}
// Monaco-only chrome: line numbers and the hairline under the current line.
// Everything else comes from the shared palette (selection, gutter, diff tints).
const lightChrome = {
  ...CODE_CHROME.light,
  'editorLineNumber.foreground': '#6e7781',
  'editorLineNumber.activeForeground': '#24292f',
  'editor.lineHighlightBorder': '#00000000'
}
const darkChrome = {
  ...CODE_CHROME.dark,
  'editorLineNumber.foreground': '#858585',
  'editorLineNumber.activeForeground': '#ffffff',
  'editor.lineHighlightBorder': '#00000000'
}
const lightRules = themeRules('light')
const darkRules = themeRules('dark')

/**
 * Monaco theme ids for workspace editors.
 * Live colors are pinned by CSS to Appearance tokens
 * (`--ds-bg-sidebar` in chat, `--ds-bg-canvas` in IDE) — these hex values are
 * only fallbacks before the stylesheet override applies.
 */
export function ensureWorkspaceMonacoThemes(): void {
  if (themesReady) return
  themesReady = true
  // Chat-mode right panel / tool editor — overridden to `--ds-bg-sidebar`.
  monaco.editor.defineTheme('ds-workspace-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: darkRules,
    colors: {
      ...darkChrome,
      'editor.background': '#171717',
      'editorGutter.background': '#171717',
      'minimap.background': '#171717'
    }
  })
  monaco.editor.defineTheme('ds-workspace-light', {
    base: 'vs',
    inherit: true,
    rules: lightRules,
    colors: {
      ...lightChrome,
      'editor.background': '#f0f0f0',
      'editorGutter.background': '#f0f0f0',
      'minimap.background': '#f0f0f0'
    }
  })
  // IDE work surface — overridden to `--ds-bg-canvas` (appearance surface).
  monaco.editor.defineTheme('ds-ide-workspace-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: darkRules,
    colors: {
      ...darkChrome,
      'editor.background': '#111111',
      'editorGutter.background': '#111111',
      'minimap.background': '#111111'
    }
  })
  monaco.editor.defineTheme('ds-ide-workspace-light', {
    base: 'vs',
    inherit: true,
    rules: lightRules,
    colors: {
      ...lightChrome,
      'editor.background': '#ffffff',
      'editorGutter.background': '#ffffff',
      'minimap.background': '#ffffff'
    }
  })
}

export function workspaceMonacoTheme(ideCanvas = false): WorkspaceMonacoThemeName {
  ensureWorkspaceMonacoThemes()
  const dark = document.documentElement.getAttribute('data-theme') === 'dark'
  if (ideCanvas) {
    return dark ? 'ds-ide-workspace-dark' : 'ds-ide-workspace-light'
  }
  return dark ? 'ds-workspace-dark' : 'ds-workspace-light'
}

export function ensureMonacoConfigured(): void {
  if (configured) return
  configured = true

  self.MonacoEnvironment = {
    getWorker(_, label) {
      if (label === 'json') return new jsonWorker()
      if (label === 'css' || label === 'scss' || label === 'less') return new cssWorker()
      if (label === 'html' || label === 'handlebars' || label === 'razor') return new htmlWorker()
      if (label === 'typescript' || label === 'javascript') return new tsWorker()
      return new editorWorker()
    }
  }

  loader.config({ monaco })
  registerLexicalSemanticTokens()
}
